#!/usr/bin/env python3
"""Five-minute MarketWatch alert and shadow-paper runner.

This process has no broker-order code. It reads completed IBKR bars, emits a
Telegram alert when the frozen strategy produces a candidate, and maintains a
local shadow ledger using the same pessimistic fill rules as the backtest.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import math
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import snapshot
from strategy import CONFIG, evaluate_live


ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
STATE_PATH = Path(os.getenv("MARKETWATCH_STATE_PATH", "/var/lib/marketwatch/state.json"))
JOURNAL_PATH = Path(os.getenv("MARKETWATCH_JOURNAL_PATH", "/var/lib/marketwatch/paper-trades.jsonl"))
LOCK_PATH = Path(os.getenv("MARKETWATCH_LOCK_PATH", "/var/lib/marketwatch/run.lock"))
ALERT_URL = os.getenv("MARKETWATCH_ALERT_URL", "http://127.0.0.1:7555/api/v2/alerts")
ALERT_TOKEN = os.getenv("MARKETWATCH_ALERT_TOKEN", "")
PAPER_INITIAL_EQUITY = float(os.getenv("MARKETWATCH_PAPER_EQUITY", "7549.84"))
PAPER_ENABLED = os.getenv("MARKETWATCH_PAPER_ENABLED", "0").lower() in {"1", "true", "yes"}


def default_state() -> dict:
    return {
        "schema": 2,
        "strategy_id": CONFIG.strategy_id,
        "paper_equity": PAPER_INITIAL_EQUITY,
        "pending": None,
        "position": None,
        "traded_dates": [],
        "last_signal_asof": None,
        "last_paper_bar_epoch": 0,
        "last_error_key": None,
        "last_error_alert_epoch": 0,
    }


def load_state() -> dict:
    state = default_state()
    if STATE_PATH.exists():
        loaded = json.loads(STATE_PATH.read_text())
        if loaded.get("strategy_id") != CONFIG.strategy_id:
            raise RuntimeError("state strategy_id does not match deployed strategy")
        state.update(loaded)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, STATE_PATH)
    STATE_PATH.chmod(0o600)


def journal(event: dict) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at": dt.datetime.now(UTC).isoformat(), **event}
    with JOURNAL_PATH.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    JOURNAL_PATH.chmod(0o600)


def send_alert(name: str, summary: str, description: str, *, dry_run: bool) -> dict:
    alert = {
        "status": "firing",
        "labels": {
            "alertname": name,
            "severity": "warning",
            "service": "marketwatch",
            "strategy": CONFIG.strategy_id,
        },
        "annotations": {"summary": summary, "description": description},
        "startsAt": dt.datetime.now(UTC).isoformat(),
    }
    if dry_run:
        return {"dry_run": True, "alert": alert}
    if not ALERT_TOKEN:
        raise RuntimeError("MARKETWATCH_ALERT_TOKEN is unset")
    request = Request(
        ALERT_URL,
        data=json.dumps([alert]).encode(),
        headers={
            "Authorization": f"Bearer {ALERT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        body = json.loads(response.read())
    if body.get("status") != "ok":
        raise RuntimeError(f"alert gateway rejected message: {body}")
    return body


def candidate_description(candidate: dict) -> str:
    e = candidate["evidence"]
    return (
        f"Research alert only; no broker order. Next-bar buy limit "
        f"{candidate['entry']['limit']:.2f}, stop {candidate['stop']:.2f}, "
        f"target {candidate['target']:.2f} ({candidate['target_r']:.2f}R), "
        f"cancel after one bar. Anchor {e['anchor']:.2f} "
        f"({e['anchor_pct_of_impulse_high']:.2f}% of opening-drive high); "
        f"breakout relative volume {e['breakout_relative_volume']:.2f}x."
    )


def commission(quantity: int) -> float:
    return max(CONFIG.minimum_commission, quantity * CONFIG.commission_per_share)


def exit_position(state: dict, bar: dict, price: float, reason: str, alerts: list, dry_run: bool) -> None:
    position = state["position"]
    quantity = position["quantity"]
    net_pnl = (
        (price - position["entry"]) * quantity
        - position["entry_commission"]
        - commission(quantity)
    )
    initial_risk = position["risk_per_share"] * quantity
    state["paper_equity"] = round(state["paper_equity"] + net_pnl, 2)
    event = {
        "event": "paper_exit",
        "strategy_id": CONFIG.strategy_id,
        "symbol": CONFIG.symbol,
        "date": bar["date"],
        "bar_epoch_ms": bar["epoch_ms"],
        "reason": reason,
        "entry": position["entry"],
        "exit": round(price, 4),
        "quantity": quantity,
        "net_pnl": round(net_pnl, 2),
        "net_r": round(net_pnl / initial_risk, 5),
        "paper_equity": state["paper_equity"],
    }
    journal(event)
    alerts.append(send_alert(
        "MarketWatchPaperExit",
        f"SPY shadow exit: {reason} at {price:.2f}",
        f"Paper P&L ${net_pnl:+,.2f} ({event['net_r']:+.2f}R); "
        f"shadow equity ${state['paper_equity']:,.2f}. No broker order was sent.",
        dry_run=dry_run,
    ))
    state["position"] = None


def process_paper_bars(state: dict, bars: list[dict], alerts: list, dry_run: bool) -> None:
    """Advance pending/position state over every newly completed bar."""
    for index, bar in enumerate(bars):
        epoch = int(bar["epoch_ms"])
        if epoch <= int(state.get("last_paper_bar_epoch", 0)):
            continue

        pending = state.get("pending")
        if pending and epoch >= pending["valid_bar_epoch_ms"]:
            if epoch == pending["valid_bar_epoch_ms"] and bar["l"] <= pending["limit"]:
                if bar["o"] <= pending["limit"]:
                    entry = min(
                        pending["limit"],
                        bar["o"] * (1 + CONFIG.slippage_bps_each_side / 10_000),
                    )
                else:
                    entry = pending["limit"]
                risk_per_share = entry - pending["stop"]
                if risk_per_share <= 0:
                    journal({"event": "paper_entry_cancelled", "strategy_id": CONFIG.strategy_id,
                             "symbol": CONFIG.symbol, "date": bar["date"],
                             "bar_epoch_ms": epoch, "reason": "entry_at_or_below_stop"})
                    state["pending"] = None
                    state["last_paper_bar_epoch"] = epoch
                    continue
                quantity = min(
                    math.floor(state["paper_equity"] * CONFIG.risk_fraction / risk_per_share),
                    math.floor(state["paper_equity"] / entry),
                )
                if quantity >= 1:
                    state["position"] = {
                        "entry_date": bar["date"],
                        "session_dates": [bar["date"]],
                        "entry_epoch_ms": epoch,
                        "entry": round(entry, 4),
                        "quantity": quantity,
                        "risk_per_share": risk_per_share,
                        "stop": pending["stop"],
                        "target": pending["target"],
                        "entry_commission": commission(quantity),
                    }
                    state["traded_dates"] = (state.get("traded_dates", []) + [bar["date"]])[-250:]
                    fill = state["position"]
                    journal({"event": "paper_fill", "strategy_id": CONFIG.strategy_id,
                             "symbol": CONFIG.symbol, "bar_epoch_ms": epoch, **fill})
                    alerts.append(send_alert(
                        "MarketWatchPaperEntry",
                        f"SPY shadow fill: {quantity} at {entry:.2f}",
                        f"Paper only. Stop {fill['stop']:.2f}, target {fill['target']:.2f}; "
                        f"risk budget {CONFIG.risk_fraction:.2%}. No broker order was sent.",
                        dry_run=dry_run,
                    ))
            else:
                journal({"event": "paper_limit_missed", "strategy_id": CONFIG.strategy_id,
                         "symbol": CONFIG.symbol, "date": bar["date"],
                         "bar_epoch_ms": epoch, "limit": pending["limit"]})
            state["pending"] = None

        position = state.get("position")
        if position:
            if bar["date"] not in position["session_dates"]:
                position["session_dates"].append(bar["date"])
            # Pessimistic OHLC ordering: a bar touching both records the stop.
            is_opening_bar = index == 0
            if is_opening_bar and bar["o"] <= position["stop"]:
                price = bar["o"] * (1 - CONFIG.slippage_bps_each_side / 10_000)
                exit_position(state, bar, price, "gap_stop", alerts, dry_run)
            elif bar["l"] <= position["stop"]:
                price = position["stop"] * (1 - CONFIG.slippage_bps_each_side / 10_000)
                exit_position(state, bar, price, "stop", alerts, dry_run)
            elif is_opening_bar and bar["o"] >= position["target"]:
                price = bar["o"] * (1 - CONFIG.slippage_bps_each_side / 10_000)
                exit_position(state, bar, price, "gap_target", alerts, dry_run)
            elif bar["h"] >= position["target"]:
                price = position["target"] * (1 - CONFIG.slippage_bps_each_side / 10_000)
                exit_position(state, bar, price, "target", alerts, dry_run)
            elif (len(position["session_dates"]) >= CONFIG.max_hold_sessions
                  and index + 1 >= snapshot.FULL_SESSION_BARS):
                price = bar["c"] * (1 - CONFIG.slippage_bps_each_side / 10_000)
                exit_position(state, bar, price, "time", alerts, dry_run)

        state["last_paper_bar_epoch"] = epoch


def run_once(*, dry_run: bool = False, force: bool = False, now: dt.datetime | None = None) -> dict:
    now = (now or dt.datetime.now(ET)).astimezone(ET)
    if not force and (now.weekday() >= 5 or not dt.time(9, 35) <= now.time() <= dt.time(16, 1)):
        return {"status": "outside-market-window", "asof": now.isoformat()}

    state = load_state()
    market = snapshot.analyze(CONFIG.symbol, include_bars=True)
    market_date = market["asof"][:10]
    if market_date != now.date().isoformat() and not force:
        return {"status": "no-current-session", "market_asof": market["asof"]}

    alerts: list[dict] = []
    if PAPER_ENABLED:
        process_paper_bars(state, market["bars"], alerts, dry_run)

    candidate = None
    if (
        state.get("last_signal_asof") != market["asof"]
        and not state.get("pending")
        and not state.get("position")
        and market_date not in state.get("traded_dates", [])
    ):
        candidate = evaluate_live(market)
        if candidate:
            last_epoch = int(market["last_bar"]["epoch_ms"])
            if PAPER_ENABLED:
                state["pending"] = {
                    "created_asof": market["asof"],
                    "valid_bar_epoch_ms": last_epoch + snapshot.BAR_MINUTES * 60_000,
                    "limit": candidate["entry"]["limit"],
                    "stop": candidate["stop"],
                    "target": candidate["target"],
                }
            journal({"event": "trade_candidate", "candidate": candidate})
            alerts.append(send_alert(
                "MarketWatchTradeCandidate",
                f"SPY buyer-breakout candidate at {market['asof']}",
                candidate_description(candidate),
                dry_run=dry_run,
            ))
    state["last_signal_asof"] = market["asof"]
    state["last_error_key"] = None
    save_state(state)
    return {
        "status": "ok",
        "market_asof": market["asof"],
        "bars_complete": market["bars_complete"],
        "candidate": candidate,
        "paper_pending": state["pending"],
        "paper_position": state["position"],
        "paper_equity": state["paper_equity"],
        "paper_mode": PAPER_ENABLED,
        "alerts": alerts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="do not call Telegram")
    parser.add_argument("--force", action="store_true", help="run outside the market window")
    args = parser.parse_args()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "already-running"}))
            return 0
        try:
            result = run_once(dry_run=args.dry_run, force=args.force)
            print(json.dumps(result, sort_keys=True))
            return 0
        except Exception as exc:
            # Persist and rate-limit an operational warning to once per hour per
            # error text. If alerting itself is broken, stderr/cron still records it.
            message = f"{type(exc).__name__}: {exc}"
            try:
                state = load_state()
                now_epoch = int(dt.datetime.now(UTC).timestamp())
                if (state.get("last_error_key") != message
                        or now_epoch - int(state.get("last_error_alert_epoch", 0)) >= 3600):
                    send_alert("MarketWatchMonitorError", "MarketWatch five-minute check failed",
                               message, dry_run=args.dry_run)
                    state["last_error_key"] = message
                    state["last_error_alert_epoch"] = now_epoch
                    save_state(state)
            except Exception as alert_exc:
                print(f"alert failure: {alert_exc}", file=sys.stderr)
            print(message, file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
