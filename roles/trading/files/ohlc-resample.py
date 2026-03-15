#!/usr/bin/env python3
"""ATLAS OHLC Resampler — builds higher timeframe bars from available data in VictoriaMetrics.

Uses the lowest available timeframe as source for each target:
  - If 1m exists: resample to 5m, 15m, 30m, 1h, 4h, 1d, 1w
  - If 5m exists (but not 1m for that range): resample to 15m, 30m, 1h, 4h, 1d, 1w
  - If 15m exists: resample to 30m, 1h, 4h, 1d, 1w
  - If 30m exists: resample to 1h, 4h, 1d, 1w

Usage:
    ohlc-resample.py SPY                    # Resample all timeframes from best source
    ohlc-resample.py SPY 1h,4h,1d           # Resample specific timeframes only
    ohlc-resample.py SPY --source mt5       # Specify source label (default: mt5)
    ohlc-resample.py SPY --chunk-by-year    # Process one year at a time (prevents OOM on 2M+ bars)
    ohlc-resample.py --all                  # Resample all symbols
"""

import json
import sys
import requests
from datetime import datetime, timezone
from calendar import timegm

VM_URL = "http://127.0.0.1:8428"
BATCH_SIZE = 10000

# Timeframes ordered from lowest to highest, with their duration in seconds
TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}

# Which source timeframes can produce which targets
# (a source can resample to any timeframe with a larger period that divides evenly)
RESAMPLE_TARGETS = {
    "1m":  ["5m", "15m", "30m", "1h", "4h", "1d", "1w"],
    "5m":  ["15m", "30m", "1h", "4h", "1d", "1w"],
    "15m": ["30m", "1h", "4h", "1d", "1w"],
    "30m": ["1h", "4h", "1d", "1w"],
    "1h":  ["4h", "1d", "1w"],
    "4h":  ["1d", "1w"],
}


def fetch_ohlc_data(symbol, timeframe, source="mt5", start_ts=None, end_ts=None):
    """Fetch OHLC data from VictoriaMetrics using export API.

    Args:
        symbol: Symbol name (e.g. "SPY")
        timeframe: Timeframe string (e.g. "1m")
        source: Data source label (default: "mt5")
        start_ts: Optional start timestamp (unix seconds) for time-bounded fetch
        end_ts: Optional end timestamp (unix seconds) for time-bounded fetch
    """
    metrics = {}
    for field in ["open", "high", "low", "close", "volume"]:
        query = f'ohlc_{field}{{symbol="{symbol}",timeframe="{timeframe}",source="{source}"}}'
        params = {"match[]": query, "format": "json"}
        if start_ts is not None:
            # VictoriaMetrics export API accepts RFC3339 or unix timestamp in seconds
            params["start"] = start_ts
        if end_ts is not None:
            params["end"] = end_ts

        resp = requests.get(
            f"{VM_URL}/api/v1/export",
            params=params,
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()

        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            timestamps = data.get("timestamps", [])
            values = data.get("values", [])
            metrics[field] = list(zip(
                [t // 1000 for t in timestamps],
                values
            ))
            break

    if not metrics.get("close"):
        return None

    # Build aligned records
    field_maps = {f: dict(pairs) for f, pairs in metrics.items()}
    ts_set = set(ts for ts, _ in metrics["close"])

    records = []
    for ts in sorted(ts_set):
        if ts not in field_maps.get("open", {}):
            continue
        records.append({
            "timestamp": ts,
            "open": field_maps["open"].get(ts, 0),
            "high": field_maps["high"].get(ts, 0),
            "low": field_maps["low"].get(ts, 0),
            "close": field_maps["close"].get(ts, 0),
            "volume": field_maps.get("volume", {}).get(ts, 0),
        })

    return records


def get_available_timeframes(symbol, source="mt5"):
    """Check which timeframes have data for a symbol."""
    available = {}
    for tf in TIMEFRAME_SECONDS:
        query = f'ohlc_close{{symbol="{symbol}",timeframe="{tf}",source="{source}"}}'
        resp = requests.get(
            f"{VM_URL}/api/v1/query",
            params={"query": f'count_over_time({query}[100y])'},
            timeout=30,
        )
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        if results:
            count = int(float(results[0]["value"][1]))
            if count > 0:
                available[tf] = count
    return available


def resample(records, target_seconds):
    """Resample OHLCV records into a higher timeframe."""
    if not records:
        return []

    groups = {}
    for r in records:
        bucket = (r["timestamp"] // target_seconds) * target_seconds
        if bucket not in groups:
            groups[bucket] = {
                "timestamp": bucket,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
            }
        else:
            g = groups[bucket]
            g["high"] = max(g["high"], r["high"])
            g["low"] = min(g["low"], r["low"])
            g["close"] = r["close"]
            g["volume"] += r["volume"]

    return [groups[k] for k in sorted(groups.keys())]


def records_to_prometheus(symbol, timeframe, source, records):
    """Convert records to Prometheus line protocol."""
    lines = []
    labels = f'symbol="{symbol}",timeframe="{timeframe}",source="{source}"'
    for r in records:
        ts = r["timestamp"]
        lines.append(f'ohlc_open{{{labels}}} {r["open"]} {ts}')
        lines.append(f'ohlc_high{{{labels}}} {r["high"]} {ts}')
        lines.append(f'ohlc_low{{{labels}}} {r["low"]} {ts}')
        lines.append(f'ohlc_close{{{labels}}} {r["close"]} {ts}')
        lines.append(f'ohlc_volume{{{labels}}} {r["volume"]} {ts}')
    return "\n".join(lines)


def import_to_vm(prom_data):
    """Import to VictoriaMetrics in batches (5000 bars = 25000 lines per batch)."""
    if not prom_data:
        return 0
    lines = prom_data.strip().split("\n")
    total = 0
    chunk = 5000 * 5  # 5000 bars * 5 metrics each = 25000 lines
    for i in range(0, len(lines), chunk):
        batch = "\n".join(lines[i:i + chunk])
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{VM_URL}/api/v1/import/prometheus",
                    data=batch.encode(),
                    headers={"Content-Type": "text/plain"},
                    timeout=120,
                )
                resp.raise_for_status()
                total += len(batch.strip().split("\n"))
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < 2:
                    import time
                    time.sleep(2)
                else:
                    raise
    return total


def get_all_symbols(source="mt5"):
    """Find all symbols in VictoriaMetrics."""
    resp = requests.get(
        f"{VM_URL}/api/v1/label/symbol/values",
        timeout=30,
    )
    resp.raise_for_status()
    return sorted(resp.json().get("data", []))


def plan_resampling(available_tfs, requested_targets):
    """Plan which source timeframes to use for each target.

    Uses ALL available sources that can produce a target, not just one.
    Each source covers a different date range, so we resample from all of them.
    VictoriaMetrics merges overlapping timestamps (idempotent writes).

    Returns: {target_tf: [source_tf1, source_tf2, ...]}
    """
    plan = {}  # target_tf -> [source_tfs]

    for target in requested_targets:
        target_secs = TIMEFRAME_SECONDS.get(target)
        if not target_secs:
            continue
        sources = []
        for src in ["1m", "5m", "15m", "30m", "1h", "4h"]:
            if src not in available_tfs:
                continue
            if target in RESAMPLE_TARGETS.get(src, []):
                sources.append(src)
        if sources:
            plan[target] = sources

    return plan


def process_source_chunked(symbol, src_tf, source, target_tfs, year_start=2008, year_end=2026):
    """Process a source timeframe year-by-year to avoid OOM on large datasets.

    Instead of loading all 2M+ bars into memory at once, fetches one year
    at a time, resamples, and imports. Each year's data is discarded before
    loading the next.

    Args:
        symbol: Symbol name
        src_tf: Source timeframe (e.g. "1m")
        source: Source label (e.g. "mt5")
        target_tfs: Set of target timeframes to resample to
        year_start: First year to process (inclusive)
        year_end: Last year to process (inclusive)
    """
    total_bars_loaded = 0
    total_bars_resampled = {}  # target_tf -> count

    for year in range(year_start, year_end + 1):
        # Unix timestamps for year boundaries
        start_ts = timegm(datetime(year, 1, 1, tzinfo=timezone.utc).timetuple())
        end_ts = timegm(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timetuple())

        records = fetch_ohlc_data(symbol, src_tf, source, start_ts=start_ts, end_ts=end_ts)
        if not records:
            continue

        total_bars_loaded += len(records)
        start_dt = datetime.fromtimestamp(records[0]["timestamp"], tz=timezone.utc)
        end_dt = datetime.fromtimestamp(records[-1]["timestamp"], tz=timezone.utc)
        print(f"    {year}: loaded {len(records):,} {src_tf} bars ({start_dt.date()} to {end_dt.date()})")

        for target_tf in sorted(target_tfs, key=lambda x: TIMEFRAME_SECONDS.get(x, 0)):
            target_secs = TIMEFRAME_SECONDS[target_tf]
            resampled = resample(records, target_secs)

            if not resampled:
                continue

            prom_data = records_to_prometheus(symbol, target_tf, source, resampled)
            count = import_to_vm(prom_data)
            total_bars_resampled[target_tf] = total_bars_resampled.get(target_tf, 0) + len(resampled)

        # records go out of scope here, freeing memory for next year

    if total_bars_loaded > 0:
        print(f"    Totals: {total_bars_loaded:,} {src_tf} bars processed year-by-year")
        for tf in sorted(total_bars_resampled, key=lambda x: TIMEFRAME_SECONDS.get(x, 0)):
            print(f"      {src_tf} -> {tf}: {total_bars_resampled[tf]:,} bars")

    return total_bars_loaded


def process_source_bulk(symbol, src_tf, source, target_tfs):
    """Process a source timeframe by loading all data at once (original behavior)."""
    records = fetch_ohlc_data(symbol, src_tf, source)
    if not records:
        print(f"  ERROR: Failed to load {src_tf} data")
        return 0

    start_dt = datetime.fromtimestamp(records[0]["timestamp"], tz=timezone.utc)
    end_dt = datetime.fromtimestamp(records[-1]["timestamp"], tz=timezone.utc)
    print(f"  Loaded {len(records):,} {src_tf} bars ({start_dt.date()} to {end_dt.date()})")

    for target_tf in sorted(target_tfs, key=lambda x: TIMEFRAME_SECONDS.get(x, 0)):
        target_secs = TIMEFRAME_SECONDS[target_tf]
        resampled = resample(records, target_secs)

        if not resampled:
            print(f"    {target_tf}: no bars produced")
            continue

        prom_data = records_to_prometheus(symbol, target_tf, source, resampled)
        count = import_to_vm(prom_data)
        r_start = datetime.fromtimestamp(resampled[0]["timestamp"], tz=timezone.utc).date()
        r_end = datetime.fromtimestamp(resampled[-1]["timestamp"], tz=timezone.utc).date()
        print(f"    {src_tf} -> {target_tf}: {len(resampled):,} bars ({r_start} to {r_end}) -> {count:,} metrics")

    return len(records)


def main():
    if len(sys.argv) < 2:
        print("Usage: ohlc-resample.py <symbol> [timeframes] [--source SOURCE] [--chunk-by-year]")
        print("       ohlc-resample.py SPY")
        print("       ohlc-resample.py SPY 30m,1h,4h,1d,1w")
        print("       ohlc-resample.py SPY --chunk-by-year          # Year-by-year to prevent OOM")
        print("       ohlc-resample.py --all")
        print("       ohlc-resample.py --all --chunk-by-year")
        print(f"\nTarget timeframes: 5m, 15m, 30m, 1h, 4h, 1d, 1w")
        sys.exit(1)

    # Parse --source flag
    source = "mt5"
    args = list(sys.argv[1:])
    if "--source" in args:
        idx = args.index("--source")
        if idx + 1 < len(args):
            source = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    # Parse --chunk-by-year flag
    chunk_by_year = False
    if "--chunk-by-year" in args:
        chunk_by_year = True
        args.remove("--chunk-by-year")

    # Handle --all
    if args[0] == "--all":
        symbols = get_all_symbols(source)
        if not symbols:
            print("No symbols found")
            sys.exit(0)
        print(f"Found symbols: {', '.join(symbols)}")
        requested_targets = None  # auto
    else:
        symbols = [args[0].upper()]
        requested_targets = args[1].split(",") if len(args) > 1 else None

    if chunk_by_year:
        print("Mode: year-by-year chunked processing (OOM-safe for large datasets)")

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"Resampling {symbol} (source={source})")
        print(f"{'='*60}")

        # Check what data exists
        available = get_available_timeframes(symbol, source)
        if not available:
            print(f"  No data found for {symbol}")
            continue

        print(f"  Available data:")
        for tf, count in sorted(available.items(), key=lambda x: TIMEFRAME_SECONDS.get(x[0], 0)):
            print(f"    {tf:>4s}: {count:>9,} bars")

        # Determine targets
        if requested_targets:
            targets = requested_targets
        else:
            # Auto: generate all possible higher timeframes
            targets = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"]

        # Plan: which source for each target
        plan = plan_resampling(available, targets)
        if not plan:
            print("  Nothing to resample")
            continue

        print(f"\n  Resampling plan:")
        for target, srcs in sorted(plan.items(), key=lambda x: TIMEFRAME_SECONDS.get(x[0], 0)):
            print(f"    {' + '.join(srcs)} -> {target}")

        # Group by source to avoid re-fetching the same data
        sources_needed = {}
        for target, srcs in plan.items():
            for src in srcs:
                sources_needed.setdefault(src, set()).add(target)

        for src_tf in sorted(sources_needed.keys(), key=lambda x: TIMEFRAME_SECONDS.get(x, 0)):
            target_tfs = sources_needed[src_tf]

            if chunk_by_year:
                print(f"\n  Processing {src_tf} data year-by-year...")
                process_source_chunked(symbol, src_tf, source, target_tfs)
            else:
                print(f"\n  Loading {src_tf} data...")
                process_source_bulk(symbol, src_tf, source, target_tfs)

    print("\nDone.")


if __name__ == "__main__":
    main()
