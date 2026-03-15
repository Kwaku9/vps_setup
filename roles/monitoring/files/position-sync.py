#!/usr/bin/env python3
"""
Position Sync — Options Lifecycle Tracker

Syncs live IBKR portfolio positions to PostgreSQL and sends Telegram alerts
when positions hit exit thresholds (21 DTE, 50% profit, gamma risk, stop loss).

Designed to run as cron Mon-Fri at 9:45 AM ET and 4:15 PM ET.

Strategy exit rules (30-90 DTE options):
  - GAMMA_RISK:     dte < 14 AND abs(delta) > 0.50   (priority 1 — emergency)
  - STOP_LOSS:      pnl_pct <= -100%                  (priority 2 — action)
  - DTE_EXIT:       dte <= 21                         (priority 2 — action)
  - TAKE_PROFIT:    pnl_pct >= 50%                    (priority 2 — action)
  - APPROACHING_DTE: 21 < dte <= 28                   (priority 3 — warning)

Dependencies: Python 3.x stdlib only (no pip packages).
"""

import json
import logging
import os
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, date

# Configuration
IBEAM_BASE = "https://127.0.0.1:5055/v1/api"
PG_CONTAINER = "postgres"
PG_USER = "postgres"
PG_DB = "enterprise"
PODMAN = "/usr/bin/podman"

# Snapshot batching
SNAPSHOT_BATCH_SIZE = 20
SNAPSHOT_DELAY = 2.5   # seconds between subscribe and read
BATCH_DELAY = 1.0      # seconds between batches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("position-sync")

# SSL context for self-signed IBeam cert
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# IBKR API helpers (reused from ivscan-daily.py)
# ---------------------------------------------------------------------------

def ib_request(path, method="GET", body=None):
    """Make a request to the IBeam gateway."""
    url = f"{IBEAM_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        log.warning("HTTP %d on %s %s", e.code, method, path)
        return None
    except Exception as e:
        log.warning("Request failed %s %s: %s", method, path, e)
        return None


def check_session():
    """Verify IBeam is authenticated."""
    data = ib_request("/tickle")
    if not data:
        return False
    auth = data.get("iserver", {}).get("authStatus", {})
    if not auth.get("authenticated") or not auth.get("connected"):
        log.error("IBeam not authenticated: %s", auth)
        return False
    log.info("IBeam session OK (user=%s)", data.get("userId"))
    return True


def parse_iv(value):
    """Parse IV from snapshot field — may be string like '35.5%' or number."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("%", "").strip()
        if not value:
            return None
        try:
            v = float(value)
        except ValueError:
            return None
    else:
        v = float(value)
    if v > 1:
        v /= 100.0
    return v


def parse_float(value):
    """Parse a numeric field from snapshot data."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("C", "H", "N/A", "--"):
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return float(value)


# ---------------------------------------------------------------------------
# DB schema management
# ---------------------------------------------------------------------------

def run_sql(sql):
    """Execute SQL via podman exec -i postgres."""
    result = subprocess.run(
        [PODMAN, "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB],
        input=sql,
        capture_output=True,
        text=True,
    )
    return result


def ensure_schema():
    """Create trading.open_positions table if not exists."""
    sql = """
    CREATE SCHEMA IF NOT EXISTS trading;

    CREATE TABLE IF NOT EXISTS trading.open_positions (
        id               SERIAL PRIMARY KEY,
        account_id       VARCHAR(20) NOT NULL,
        conid            INTEGER NOT NULL,
        ticker           VARCHAR(10) NOT NULL,
        underlying_conid INTEGER,
        put_call         VARCHAR(1),
        strike           NUMERIC(10,2),
        expiry           DATE,
        dte              INTEGER,
        quantity         INTEGER NOT NULL DEFAULT 0,
        avg_cost         NUMERIC(12,4),
        market_price     NUMERIC(12,4),
        market_value     NUMERIC(12,2),
        unrealized_pnl   NUMERIC(12,2),
        pnl_pct          NUMERIC(8,2),
        iv               NUMERIC(8,4),
        delta            NUMERIC(8,4),
        gamma            NUMERIC(8,6),
        theta            NUMERIC(8,4),
        vega             NUMERIC(8,4),
        exit_signal      VARCHAR(20),
        exit_priority    INTEGER DEFAULT 0,
        status           VARCHAR(10) NOT NULL DEFAULT 'OPEN',
        opened_at        TIMESTAMP DEFAULT NOW(),
        last_synced      TIMESTAMP DEFAULT NOW(),
        closed_at        TIMESTAMP,
        CONSTRAINT uq_open_positions_acct_conid UNIQUE (account_id, conid)
    );
    """
    result = run_sql(sql)
    if result.returncode != 0:
        log.error("Schema creation failed: %s", result.stderr.strip())
        return False
    log.info("DB schema verified (trading.open_positions)")
    return True


# ---------------------------------------------------------------------------
# Portfolio fetching
# ---------------------------------------------------------------------------

def get_account_id():
    """Get the first portfolio account ID."""
    data = ib_request("/portfolio/accounts")
    if not data or not isinstance(data, list) or len(data) == 0:
        log.error("No portfolio accounts returned")
        return None
    acct = data[0]
    if isinstance(acct, dict):
        acct_id = acct.get("accountId", acct.get("id", str(acct)))
    else:
        acct_id = str(acct)
    log.info("Using account: %s", acct_id)
    return acct_id


def fetch_all_positions(account_id):
    """Fetch all portfolio positions (paginated)."""
    all_positions = []
    page = 0
    while True:
        data = ib_request(f"/portfolio/{account_id}/positions/{page}")
        if not data or not isinstance(data, list) or len(data) == 0:
            break
        all_positions.extend(data)
        log.info("  Fetched page %d: %d positions", page, len(data))
        page += 1
        if len(data) < 30:  # IBKR pages are typically 30 items
            break
        time.sleep(0.5)
    log.info("Total positions fetched: %d", len(all_positions))
    return all_positions


def filter_options(positions):
    """Keep only option positions (assetClass=OPT)."""
    options = []
    for pos in positions:
        asset_class = pos.get("assetClass", "")
        if asset_class == "OPT":
            options.append(pos)
    log.info("Option positions: %d (filtered from %d total)", len(options), len(positions))
    return options


# ---------------------------------------------------------------------------
# Greeks snapshot
# ---------------------------------------------------------------------------

def fetch_greeks_batch(conids):
    """Fetch greeks for a batch of conids via market data snapshot.
    Fields: 7283=IV%, 7308=delta, 7309=gamma, 7310=theta, 7311=vega"""
    conid_str = ",".join(str(c) for c in conids)
    fields = "7283,7308,7309,7310,7311"

    # First call subscribes
    ib_request(f"/iserver/marketdata/snapshot?conids={conid_str}&fields={fields}")
    time.sleep(SNAPSHOT_DELAY)
    # Second call gets data
    data = ib_request(f"/iserver/marketdata/snapshot?conids={conid_str}&fields={fields}")
    if not data:
        return {}

    results = {}
    for item in data:
        cid = item.get("conid", item.get("conidEx", ""))
        if isinstance(cid, str) and "@" in cid:
            cid = int(cid.split("@")[0])
        else:
            cid = int(cid) if cid else 0

        results[cid] = {
            "iv": parse_iv(item.get("7283")),
            "delta": parse_float(item.get("7308")),
            "gamma": parse_float(item.get("7309")),
            "theta": parse_float(item.get("7310")),
            "vega": parse_float(item.get("7311")),
        }
    return results


def fetch_all_greeks(conids):
    """Fetch greeks for all option conids in batches."""
    all_greeks = {}
    batches = [conids[i:i + SNAPSHOT_BATCH_SIZE]
               for i in range(0, len(conids), SNAPSHOT_BATCH_SIZE)]
    log.info("Fetching greeks: %d conids in %d batches", len(conids), len(batches))

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            time.sleep(BATCH_DELAY)
        greeks = fetch_greeks_batch(batch)
        all_greeks.update(greeks)
        if (batch_idx + 1) % 5 == 0 or batch_idx == len(batches) - 1:
            log.info("  Greeks batch %d/%d done", batch_idx + 1, len(batches))

    return all_greeks


# ---------------------------------------------------------------------------
# Exit signal evaluation
# ---------------------------------------------------------------------------

def evaluate_exit_signal(dte, pnl_pct, delta):
    """Determine exit signal and priority for a position.
    Returns (signal, priority) or (None, 0)."""
    # Priority 1: emergency
    if dte is not None and delta is not None:
        if dte < 14 and abs(delta) > 0.50:
            return "GAMMA_RISK", 1

    # Priority 2: action required
    if pnl_pct is not None and pnl_pct <= -100.0:
        return "STOP_LOSS", 2

    if dte is not None and dte <= 21:
        return "DTE_EXIT", 2

    if pnl_pct is not None and pnl_pct >= 50.0:
        return "TAKE_PROFIT", 2

    # Priority 3: warning
    if dte is not None and 21 < dte <= 28:
        return "APPROACHING_DTE", 3

    return None, 0


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------

def parse_expiry(pos):
    """Extract expiry date from position data. Returns (date_obj, dte) or (None, None)."""
    # IBKR returns expiry in various formats
    expiry_str = pos.get("expiry", pos.get("lastTradingDay", ""))
    if not expiry_str:
        return None, None

    # Try YYYYMMDD format
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            exp_date = datetime.strptime(str(expiry_str), fmt).date()
            dte = (exp_date - date.today()).days
            return exp_date, dte
        except ValueError:
            continue

    return None, None


def build_records(account_id, options, greeks_map):
    """Build position records with computed fields."""
    records = []

    for pos in options:
        conid = int(pos.get("conid", 0))
        if conid == 0:
            continue

        # Extract position fields
        ticker = pos.get("ticker", pos.get("contractDesc", "???"))
        # Clean ticker: "AAPL 280321C00230000" -> "AAPL"
        if " " in ticker:
            ticker = ticker.split()[0]

        underlying_conid = pos.get("underConid", pos.get("undConid"))
        put_call = pos.get("putOrCall", pos.get("right", ""))
        if put_call:
            put_call = put_call[0].upper()  # "CALL" -> "C", "PUT" -> "P"

        strike = parse_float(pos.get("strike"))
        expiry_date, dte = parse_expiry(pos)
        quantity = int(pos.get("position", pos.get("size", 0)))
        avg_cost = parse_float(pos.get("avgCost", pos.get("avgPrice")))
        market_price = parse_float(pos.get("mktPrice", pos.get("marketPrice")))
        market_value = parse_float(pos.get("mktValue", pos.get("marketValue")))
        unrealized_pnl = parse_float(pos.get("unrealizedPnl", pos.get("unrealPnl")))

        # Compute PnL %
        pnl_pct = None
        if unrealized_pnl is not None and avg_cost is not None and quantity != 0:
            total_cost = abs(avg_cost * quantity)
            if total_cost > 0.01:
                pnl_pct = round((unrealized_pnl / total_cost) * 100, 2)

        # Merge greeks
        g = greeks_map.get(conid, {})
        iv = g.get("iv")
        delta_val = g.get("delta")
        gamma = g.get("gamma")
        theta = g.get("theta")
        vega = g.get("vega")

        # Evaluate exit signal
        exit_signal, exit_priority = evaluate_exit_signal(dte, pnl_pct, delta_val)

        records.append({
            "account_id": account_id,
            "conid": conid,
            "ticker": ticker[:10],
            "underlying_conid": underlying_conid,
            "put_call": put_call,
            "strike": strike,
            "expiry": expiry_date,
            "dte": dte,
            "quantity": quantity,
            "avg_cost": avg_cost,
            "market_price": market_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "pnl_pct": pnl_pct,
            "iv": iv,
            "delta": delta_val,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "exit_signal": exit_signal,
            "exit_priority": exit_priority,
        })

        signal_str = f" -> {exit_signal}" if exit_signal else ""
        log.info(
            "  %s %s%s %.0f %dd qty=%d pnl=%.1f%%%s",
            ticker, put_call or "?",
            f" {strike:.0f}" if strike else "",
            market_price or 0,
            dte or 0,
            quantity,
            pnl_pct or 0,
            signal_str,
        )

    return records


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def sql_val(val, fmt=None):
    """Format a value for SQL insertion."""
    if val is None:
        return "NULL"
    if isinstance(val, str):
        return f"'{val.replace(chr(39), chr(39)+chr(39))}'"
    if isinstance(val, date):
        return f"'{val.isoformat()}'"
    if fmt:
        return fmt.format(val)
    return str(val)


def upsert_positions(records):
    """UPSERT position records into PostgreSQL."""
    if not records:
        log.info("No option positions to upsert")
        return

    values = []
    for r in records:
        vals = (
            f"({sql_val(r['account_id'])}, {r['conid']}, {sql_val(r['ticker'])}, "
            f"{sql_val(r['underlying_conid'])}, {sql_val(r['put_call'])}, "
            f"{sql_val(r['strike'], '{:.2f}')}, {sql_val(r['expiry'])}, "
            f"{sql_val(r['dte'])}, {r['quantity']}, "
            f"{sql_val(r['avg_cost'], '{:.4f}')}, "
            f"{sql_val(r['market_price'], '{:.4f}')}, "
            f"{sql_val(r['market_value'], '{:.2f}')}, "
            f"{sql_val(r['unrealized_pnl'], '{:.2f}')}, "
            f"{sql_val(r['pnl_pct'], '{:.2f}')}, "
            f"{sql_val(r['iv'], '{:.4f}')}, "
            f"{sql_val(r['delta'], '{:.4f}')}, "
            f"{sql_val(r['gamma'], '{:.6f}')}, "
            f"{sql_val(r['theta'], '{:.4f}')}, "
            f"{sql_val(r['vega'], '{:.4f}')}, "
            f"{sql_val(r['exit_signal'])}, {r['exit_priority']}, "
            f"'OPEN', NOW())"
        )
        values.append(vals)

    sql = (
        "INSERT INTO trading.open_positions\n"
        "    (account_id, conid, ticker, underlying_conid, put_call,\n"
        "     strike, expiry, dte, quantity, avg_cost,\n"
        "     market_price, market_value, unrealized_pnl, pnl_pct,\n"
        "     iv, delta, gamma, theta, vega,\n"
        "     exit_signal, exit_priority, status, last_synced)\n"
        "VALUES\n"
        + ",\n".join(values) + "\n"
        "ON CONFLICT (account_id, conid) DO UPDATE SET\n"
        "    ticker=EXCLUDED.ticker,\n"
        "    underlying_conid=EXCLUDED.underlying_conid,\n"
        "    put_call=EXCLUDED.put_call,\n"
        "    strike=EXCLUDED.strike,\n"
        "    expiry=EXCLUDED.expiry,\n"
        "    dte=EXCLUDED.dte,\n"
        "    quantity=EXCLUDED.quantity,\n"
        "    avg_cost=EXCLUDED.avg_cost,\n"
        "    market_price=EXCLUDED.market_price,\n"
        "    market_value=EXCLUDED.market_value,\n"
        "    unrealized_pnl=EXCLUDED.unrealized_pnl,\n"
        "    pnl_pct=EXCLUDED.pnl_pct,\n"
        "    iv=EXCLUDED.iv,\n"
        "    delta=EXCLUDED.delta,\n"
        "    gamma=EXCLUDED.gamma,\n"
        "    theta=EXCLUDED.theta,\n"
        "    vega=EXCLUDED.vega,\n"
        "    exit_signal=EXCLUDED.exit_signal,\n"
        "    exit_priority=EXCLUDED.exit_priority,\n"
        "    status='OPEN',\n"
        "    last_synced=NOW(),\n"
        "    closed_at=NULL;\n"
    )

    result = run_sql(sql)
    if result.returncode != 0:
        log.error("UPSERT failed: %s", result.stderr.strip())
    else:
        log.info("Upserted %d positions", len(records))


def mark_stale_positions(account_id, current_conids):
    """Mark positions not in current sync as CLOSED or EXPIRED.
    Safety: skip if API returned zero positions (transient failure guard)."""
    if not current_conids:
        log.warning("Zero positions from API — skipping stale detection (safety)")
        return

    conid_list = ",".join(str(c) for c in current_conids)
    sql = (
        f"UPDATE trading.open_positions\n"
        f"SET status = CASE\n"
        f"        WHEN expiry <= CURRENT_DATE THEN 'EXPIRED'\n"
        f"        ELSE 'CLOSED'\n"
        f"    END,\n"
        f"    closed_at = NOW(),\n"
        f"    last_synced = NOW()\n"
        f"WHERE account_id = '{account_id}'\n"
        f"  AND status = 'OPEN'\n"
        f"  AND conid NOT IN ({conid_list});\n"
    )
    result = run_sql(sql)
    if result.returncode != 0:
        log.error("Stale detection failed: %s", result.stderr.strip())
    else:
        # Parse rows affected
        output = result.stdout.strip()
        log.info("Stale detection: %s", output if output else "no stale positions")


# ---------------------------------------------------------------------------
# Telegram alerts
# ---------------------------------------------------------------------------

def send_telegram_alerts(records):
    """Send Telegram alert for positions with exit signals."""
    signaled = [r for r in records if r["exit_signal"]]
    if not signaled:
        log.info("No exit signals — no alert sent")
        return

    signaled.sort(key=lambda r: r["exit_priority"])

    now = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    lines = [f"<b>Position Alert</b>  {now}\n"]

    # Group by priority
    groups = {
        1: ("URGENT", []),
        2: ("ACTION", []),
        3: ("WATCH", []),
    }
    for r in signaled:
        p = r["exit_priority"]
        if p in groups:
            groups[p][1].append(r)

    for priority in (1, 2, 3):
        label, items = groups[priority]
        if not items:
            continue
        lines.append(f"\n<b>[{label}]</b>")
        for r in items:
            pc = r["put_call"] or "?"
            strike_str = f"{r['strike']:.0f}" if r["strike"] else "?"
            dte_str = f"{r['dte']}d" if r["dte"] is not None else "?d"
            pnl_str = f"{r['pnl_pct']:+.1f}%" if r["pnl_pct"] is not None else "N/A"
            delta_str = f"d:{r['delta']:.2f}" if r["delta"] is not None else ""
            lines.append(
                f"  {r['ticker']:6s} {r['quantity']:+d} "
                f"{strike_str}{pc} {dte_str} "
                f"PnL:{pnl_str} {delta_str} "
                f"{r['exit_signal']}"
            )

    msg = "\n".join(lines)
    log.info("Sending Telegram alert (%d signals)", len(signaled))

    try:
        result = subprocess.run(
            ["/usr/local/bin/telegram-notify", msg, "HTML"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning("telegram-notify failed: %s", result.stderr.strip())
        else:
            log.info("Telegram alert sent")
    except FileNotFoundError:
        log.warning("telegram-notify not found — alert not sent")
    except subprocess.TimeoutExpired:
        log.warning("telegram-notify timed out")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("Position Sync — %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    log.info("=" * 60)

    # Step 1: Check IBeam session
    if not check_session():
        log.error("IBeam session check failed. Exiting.")
        sys.exit(1)

    # Step 2: Ensure DB schema
    if not ensure_schema():
        log.error("Schema setup failed. Exiting.")
        sys.exit(1)

    # Step 3: Get account ID
    account_id = get_account_id()
    if not account_id:
        log.error("Could not get account ID. Exiting.")
        sys.exit(1)

    # Step 4: Fetch all positions
    log.info("--- Fetching positions ---")
    positions = fetch_all_positions(account_id)
    if not positions:
        log.info("No positions in portfolio")
        # Still run stale detection with empty set (but safety guard will skip)
        mark_stale_positions(account_id, [])
        log.info("Sync complete (empty portfolio)")
        return

    # Step 5: Filter to options only
    options = filter_options(positions)
    if not options:
        log.info("No option positions found")
        mark_stale_positions(account_id, [])
        log.info("Sync complete (no options)")
        return

    # Step 6: Fetch greeks for all option conids
    log.info("--- Fetching greeks ---")
    opt_conids = [int(pos.get("conid", 0)) for pos in options if pos.get("conid")]
    greeks_map = fetch_all_greeks(opt_conids)
    greeks_hit = sum(1 for c in opt_conids if c in greeks_map)
    log.info("Greeks: %d/%d conids with data", greeks_hit, len(opt_conids))

    # Step 7: Build records with computed fields
    log.info("--- Building records ---")
    records = build_records(account_id, options, greeks_map)
    log.info("Built %d position records", len(records))

    # Step 8: UPSERT to PostgreSQL
    log.info("--- DB upsert ---")
    upsert_positions(records)

    # Step 9: Mark stale positions
    log.info("--- Stale detection ---")
    current_conids = [r["conid"] for r in records]
    mark_stale_positions(account_id, current_conids)

    # Step 10: Send Telegram alerts
    log.info("--- Alerts ---")
    send_telegram_alerts(records)

    # Summary
    elapsed = time.time() - start_time
    signaled = sum(1 for r in records if r["exit_signal"])
    log.info("=" * 60)
    log.info("SYNC COMPLETE — %d positions, %d signals in %.1fs",
             len(records), signaled, elapsed)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
