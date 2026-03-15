#!/usr/bin/env python3
"""ATLAS MetaTrader 5 OHLC Ingestion — parses CSV exports and stores in VictoriaMetrics.

Handles native MT5 export format:
  - Tab-separated or comma-separated
  - Angle-bracket headers: <DATE>, <TIME>, <OPEN>, <HIGH>, <LOW>, <CLOSE>, <TICKVOL>, <VOL>, <SPREAD>
  - Broker timezone conversion to UTC (default: EET)
  - Uses <TICKVOL> as volume (real tick volume), ignores <VOL> (always 0 for CFDs)
  - Batched import to VictoriaMetrics (10,000 bars per batch to avoid timeouts)
"""

import csv
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests

VM_URL = "http://127.0.0.1:8428"
BATCH_SIZE = 10000

MT5_TIMEFRAME_MAP = {
    "M1": "1m", "M5": "5m", "M15": "15m",
    "H1": "1h", "H4": "4h", "D1": "1d", "W1": "1w",
    "MN1": "1M",
}

# Common broker timezone offsets (hours ahead of UTC)
# EET (Eastern European Time) = UTC+2, EEST (summer) = UTC+3
# Most MT5 brokers use EET/EEST which follows Helsinki timezone
TIMEZONE_OFFSETS = {
    "EET": "Europe/Helsinki",   # UTC+2 / UTC+3 (DST)
    "EST": "US/Eastern",        # UTC-5 / UTC-4 (DST)
    "CST": "US/Central",        # UTC-6 / UTC-5 (DST)
    "UTC": "UTC",
    "GMT": "UTC",
}


def eet_to_utc(dt_naive, tz_name="EET"):
    """Convert a naive datetime from broker timezone to UTC.

    Uses a simplified DST rule for EET (matches EU DST):
    - Last Sunday of March at 03:00 local -> clocks forward (UTC+3)
    - Last Sunday of October at 04:00 local -> clocks back (UTC+2)
    """
    if tz_name in ("UTC", "GMT"):
        return dt_naive.replace(tzinfo=timezone.utc)

    if tz_name in ("EST", "US/Eastern"):
        # US DST: 2nd Sunday March -> 1st Sunday November
        std_offset = -5
        dst_offset = -4
        dst_start = _nth_weekday(dt_naive.year, 3, 6, 2)   # 2nd Sunday March
        dst_end = _nth_weekday(dt_naive.year, 11, 6, 1)     # 1st Sunday November
    elif tz_name in ("CST", "US/Central"):
        std_offset = -6
        dst_offset = -5
        dst_start = _nth_weekday(dt_naive.year, 3, 6, 2)
        dst_end = _nth_weekday(dt_naive.year, 11, 6, 1)
    else:
        # EET/EEST (EU DST rules)
        std_offset = 2
        dst_offset = 3
        dst_start = _last_weekday(dt_naive.year, 3, 6)   # Last Sunday March
        dst_end = _last_weekday(dt_naive.year, 10, 6)     # Last Sunday October

    # Check if we're in DST
    dst_start_dt = datetime(dt_naive.year, dst_start.month, dst_start.day, 3, 0)
    dst_end_dt = datetime(dt_naive.year, dst_end.month, dst_end.day, 4, 0)

    if dst_start_dt <= dt_naive < dst_end_dt:
        offset = dst_offset
    else:
        offset = std_offset

    return (dt_naive - timedelta(hours=offset)).replace(tzinfo=timezone.utc)


def _last_weekday(year, month, weekday):
    """Find last occurrence of weekday (0=Mon, 6=Sun) in month."""
    if month == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime(year, month + 1, 1) - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _nth_weekday(year, month, weekday, n):
    """Find nth occurrence of weekday (0=Mon, 6=Sun) in month."""
    first = datetime(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def parse_filename(filepath):
    """Extract symbol and timeframe from filename.

    Handles patterns:
      SPY_M1.csv
      US500_M1_202511191329_202603060408.csv (MT5 long format)
    """
    basename = os.path.basename(filepath).replace(".csv", "")

    # Try SYMBOL_TIMEFRAME_dates pattern (MT5 long export name)
    match = re.match(r"^([A-Z0-9]+)_([A-Z0-9]+)_\d+_\d+$", basename, re.IGNORECASE)
    if match:
        symbol = match.group(1).upper()
        mt5_tf = match.group(2).upper()
        timeframe = MT5_TIMEFRAME_MAP.get(mt5_tf, mt5_tf.lower())
        return symbol, timeframe

    # Try SYMBOL_TIMEFRAME pattern
    match = re.match(r"^([A-Z0-9]+)_([A-Z0-9]+)$", basename, re.IGNORECASE)
    if match:
        symbol = match.group(1).upper()
        mt5_tf = match.group(2).upper()
        timeframe = MT5_TIMEFRAME_MAP.get(mt5_tf, mt5_tf.lower())
        return symbol, timeframe

    return None, None


def parse_csv(filepath, broker_tz="EET"):
    """Parse MT5 CSV export into OHLCV records with timezone conversion."""
    records = []
    with open(filepath, "r") as f:
        # Detect delimiter (tab or comma)
        sample = f.read(2048)
        f.seek(0)
        delimiter = "\t" if "\t" in sample else ","

        reader = csv.reader(f, delimiter=delimiter)
        header = None

        for row in reader:
            if not row:
                continue

            # Detect header row (angle-bracket or plain)
            first = row[0].strip().lower().replace("<", "").replace(">", "")
            if first in ("date", "time", "datetime"):
                header = [h.strip().lower().replace("<", "").replace(">", "") for h in row]
                continue

            # Auto-assign header if none found
            if header is None:
                if len(row) >= 9:
                    header = ["date", "time", "open", "high", "low", "close", "tickvol", "vol", "spread"]
                elif len(row) >= 7:
                    header = ["date", "time", "open", "high", "low", "close", "tickvol"]
                elif len(row) >= 6:
                    header = ["date", "time", "open", "high", "low", "close"]
                else:
                    continue

            data = dict(zip(header, [v.strip() for v in row]))

            # Parse timestamp
            date_str = data.get("date", "")
            time_str = data.get("time", "")

            try:
                # Try combined datetime formats
                combined = f"{date_str} {time_str}".strip() if time_str else date_str
                dt_naive = None
                for fmt in ["%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
                            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                            "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"]:
                    try:
                        dt_naive = datetime.strptime(combined, fmt)
                        break
                    except ValueError:
                        continue

                if dt_naive is None:
                    # Try date-only
                    for fmt in ["%Y.%m.%d", "%Y-%m-%d"]:
                        try:
                            dt_naive = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue

                if dt_naive is None:
                    continue

                # Convert from broker timezone to UTC
                dt_utc = eet_to_utc(dt_naive, broker_tz)

                # Use tickvol as volume (real tick count), fall back to vol
                volume = data.get("tickvol", data.get("vol", data.get("volume", "0")))

                records.append({
                    "timestamp": int(dt_utc.timestamp()),
                    "open": float(data.get("open", 0)),
                    "high": float(data.get("high", 0)),
                    "low": float(data.get("low", 0)),
                    "close": float(data.get("close", 0)),
                    "volume": float(volume),
                })
            except (ValueError, KeyError, TypeError):
                continue

    return records


def records_to_prometheus(symbol, timeframe, records, source="mt5"):
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
    """Import to VictoriaMetrics."""
    if not prom_data:
        return 0
    resp = requests.post(
        f"{VM_URL}/api/v1/import/prometheus",
        data=prom_data.encode(),
        headers={"Content-Type": "text/plain"},
        timeout=120,
    )
    resp.raise_for_status()
    return len(prom_data.strip().split("\n"))


def main():
    if len(sys.argv) < 2:
        print("Usage: mt5-ohlc-ingest.py <csv_file> [symbol] [timeframe] [--tz TIMEZONE] [--source SOURCE]")
        print()
        print("Examples:")
        print("  mt5-ohlc-ingest.py /path/to/SPY_M1.csv")
        print("  mt5-ohlc-ingest.py /path/to/US500_M1_202511191329_202603060408.csv SPY 1m")
        print("  mt5-ohlc-ingest.py /path/to/data.csv EURUSD 1h --tz EST")
        print()
        print("Symbol/timeframe auto-detected from filename if not provided.")
        print(f"Supported timezones: {', '.join(TIMEZONE_OFFSETS.keys())} (default: EET)")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    # Parse optional --tz flag
    broker_tz = "EET"
    args = sys.argv[2:]
    if "--tz" in args:
        tz_idx = args.index("--tz")
        if tz_idx + 1 < len(args):
            broker_tz = args[tz_idx + 1].upper()
            args = args[:tz_idx] + args[tz_idx + 2:]

    # Parse optional --source flag (default: mt5)
    source = "mt5"
    if "--source" in args:
        src_idx = args.index("--source")
        if src_idx + 1 < len(args):
            source = args[src_idx + 1].lower()
            args = args[:src_idx] + args[src_idx + 2:]

    # Get symbol and timeframe
    if len(args) >= 2:
        symbol = args[0].upper()
        timeframe = args[1]
    else:
        symbol, timeframe = parse_filename(filepath)
        if not symbol:
            print("ERROR: Could not extract symbol/timeframe from filename.", file=sys.stderr)
            print("Provide explicitly: mt5-ohlc-ingest.py file.csv SPY 1m", file=sys.stderr)
            sys.exit(1)

    # Map US500 -> SPY for consistency
    symbol_map = {"US500": "SPY", "US30": "DJI", "US100": "QQQ", "USTEC": "QQQ"}
    display_symbol = symbol
    symbol = symbol_map.get(symbol, symbol)
    if display_symbol != symbol:
        print(f"Mapping {display_symbol} -> {symbol}")

    print(f"Parsing {filepath}...")
    print(f"Symbol: {symbol} | Timeframe: {timeframe} | Source: {source} | Timezone: {broker_tz}")

    records = parse_csv(filepath, broker_tz)
    if not records:
        print("ERROR: No valid OHLCV records parsed from file", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(records)} bars")
    print(f"Date range: {datetime.fromtimestamp(records[0]['timestamp'], tz=timezone.utc)} to {datetime.fromtimestamp(records[-1]['timestamp'], tz=timezone.utc)}")

    # Import in batches to avoid timeout on large files
    total_lines = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        prom_data = records_to_prometheus(symbol, timeframe, batch, source)
        count = import_to_vm(prom_data)
        total_lines += count
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Batch {batch_num}/{total_batches}: {len(batch)} bars -> {count} metrics")

    print(f"\nComplete: {len(records)} bars for {symbol} {timeframe} ({total_lines} metric lines)")


if __name__ == "__main__":
    main()
