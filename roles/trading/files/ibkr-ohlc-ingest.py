#!/usr/bin/env python3
"""ATLAS IBKR OHLC Ingestion — fetches historical data from IBeam and stores in VictoriaMetrics."""

import json
import sys
import time
from datetime import datetime, timezone

import requests

GATEWAY_URL = "http://127.0.0.1:5055/v1/api"
VM_URL = "http://127.0.0.1:8428"

BAR_SIZE_MAP = {
    "1m": ("1 min", "1 D"),
    "5m": ("5 mins", "5 D"),
    "15m": ("15 mins", "10 D"),
    "1h": ("1 hour", "1 M"),
    "4h": ("4 hours", "3 M"),
    "1d": ("1 day", "1 Y"),
    "1w": ("1W", "5 Y"),
}

# IBKR pacing: max 6 requests per 2 seconds
REQUEST_DELAY = 0.35


def check_session():
    """Verify IBeam gateway session is active."""
    try:
        resp = requests.get(f"{GATEWAY_URL}/tickle", timeout=10, verify=False)
        data = resp.json()
        if not data.get("session"):
            print("ERROR: No active IBeam session. Restart ibeam container and authenticate.", file=sys.stderr)
            sys.exit(1)
        print(f"Session active: {data.get('session')}")
    except Exception as e:
        print(f"ERROR: Cannot reach IBeam gateway: {e}", file=sys.stderr)
        sys.exit(1)


def resolve_conid(symbol):
    """Resolve symbol to IBKR conid."""
    known = {
        "SPY": 756733,
        "QQQ": 320227571,
        "IWM": 9579970,
    }
    if symbol in known:
        return known[symbol]

    resp = requests.get(f"{GATEWAY_URL}/iserver/secdef/search", params={"symbol": symbol}, timeout=15, verify=False)
    results = resp.json()
    if results:
        conid = results[0].get("conid")
        if conid:
            return int(conid)
    print(f"ERROR: Could not resolve conid for {symbol}", file=sys.stderr)
    sys.exit(1)


def fetch_history(conid, bar_size, duration, outside_rth=False):
    """Fetch historical OHLC data from IBKR HMDS."""
    params = {
        "conid": conid,
        "period": duration,
        "bar": bar_size,
        "outsideRth": str(outside_rth).lower(),
    }
    resp = requests.get(f"{GATEWAY_URL}/hmds/history", params=params, timeout=30, verify=False)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def bars_to_prometheus(symbol, timeframe, bars):
    """Convert IBKR bars to Prometheus line protocol for VictoriaMetrics import."""
    lines = []
    for bar in bars:
        # IBKR timestamps are in milliseconds
        ts_str = bar.get("t", "")
        if not ts_str:
            continue

        # Parse IBKR timestamp format (yyyyMMdd-HH:mm:ss or epoch ms)
        try:
            if isinstance(ts_str, (int, float)):
                ts_ms = int(ts_str)
            elif "-" in str(ts_str) and ":" in str(ts_str):
                dt = datetime.strptime(str(ts_str), "%Y%m%d-%H:%M:%S").replace(tzinfo=timezone.utc)
                ts_ms = int(dt.timestamp() * 1000)
            else:
                ts_ms = int(ts_str)
        except (ValueError, TypeError):
            continue

        ts_s = ts_ms // 1000

        o = bar.get("o", 0)
        h = bar.get("h", 0)
        l = bar.get("l", 0)
        c = bar.get("c", 0)
        v = bar.get("v", 0)

        labels = f'symbol="{symbol}",timeframe="{timeframe}",source="ibkr"'
        lines.append(f"ohlc_open{{{labels}}} {o} {ts_s}")
        lines.append(f"ohlc_high{{{labels}}} {h} {ts_s}")
        lines.append(f"ohlc_low{{{labels}}} {l} {ts_s}")
        lines.append(f"ohlc_close{{{labels}}} {c} {ts_s}")
        lines.append(f"ohlc_volume{{{labels}}} {v} {ts_s}")

    return "\n".join(lines)


def import_to_vm(prom_data):
    """Import Prometheus line protocol data into VictoriaMetrics."""
    if not prom_data:
        return 0
    resp = requests.post(
        f"{VM_URL}/api/v1/import/prometheus",
        data=prom_data.encode(),
        headers={"Content-Type": "text/plain"},
        timeout=30,
    )
    resp.raise_for_status()
    lines = len(prom_data.strip().split("\n"))
    return lines


def ingest_symbol(symbol, timeframe):
    """Ingest OHLC data for a single symbol and timeframe."""
    if timeframe not in BAR_SIZE_MAP:
        print(f"ERROR: Unknown timeframe '{timeframe}'. Use: {', '.join(BAR_SIZE_MAP.keys())}", file=sys.stderr)
        return 0

    bar_size, duration = BAR_SIZE_MAP[timeframe]
    conid = resolve_conid(symbol)
    print(f"Fetching {symbol} (conid={conid}) {timeframe} bars (period={duration})...")

    time.sleep(REQUEST_DELAY)
    bars = fetch_history(conid, bar_size, duration)

    if not bars:
        print(f"WARNING: No bars returned for {symbol} {timeframe}")
        return 0

    print(f"Got {len(bars)} bars from IBKR")
    prom_data = bars_to_prometheus(symbol, timeframe, bars)
    count = import_to_vm(prom_data)
    print(f"Imported {count} metric lines to VictoriaMetrics")
    return len(bars)


def main():
    if len(sys.argv) < 3:
        print("Usage: ibkr-ohlc-ingest.py <symbol> <timeframe> [symbol2 timeframe2 ...]")
        print("       ibkr-ohlc-ingest.py --batch SPY,QQQ,AAPL 1d,1h,4h")
        print(f"Timeframes: {', '.join(BAR_SIZE_MAP.keys())}")
        sys.exit(1)

    check_session()

    if sys.argv[1] == "--batch":
        symbols = sys.argv[2].split(",")
        timeframes = sys.argv[3].split(",") if len(sys.argv) > 3 else ["1d"]
        total = 0
        for sym in symbols:
            for tf in timeframes:
                total += ingest_symbol(sym.strip(), tf.strip())
                time.sleep(REQUEST_DELAY)
        print(f"\nBatch complete: {total} total bars ingested")
    else:
        args = sys.argv[1:]
        if len(args) % 2 != 0:
            print("ERROR: Arguments must be in pairs: <symbol> <timeframe>", file=sys.stderr)
            sys.exit(1)
        total = 0
        for i in range(0, len(args), 2):
            total += ingest_symbol(args[i], args[i + 1])
            time.sleep(REQUEST_DELAY)
        print(f"\nComplete: {total} total bars ingested")


if __name__ == "__main__":
    main()
