from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import monitor
import snapshot
from strategy import evaluate_live


ET = ZoneInfo("America/New_York")


def epoch(day: int, hour: int, minute: int) -> int:
    return int(dt.datetime(2026, 9, day, hour, minute, tzinfo=ET).timestamp() * 1000)


def bar(day: int, index: int, volume: float = 100.0) -> dict:
    start = dt.datetime(2026, 8, day, 9, 30, tzinfo=ET) + dt.timedelta(minutes=5 * index)
    return {
        "date": start.date().isoformat(), "time": start.strftime("%H:%M"),
        "epoch_ms": int(start.timestamp() * 1000),
        "o": 100.0, "h": 100.2, "l": 99.8, "c": 100.1, "v": volume,
    }


def eligible_state() -> dict:
    return {
        "symbol": "SPY", "source": "IBKR RTH Trades", "bars_complete": 4,
        "asof": "2026-09-09 09:50 ET", "prev_close": 100.0,
        "opening": {"breakout_relative_volume": 1.2},
        "levels": {"prior_high": 100.0, "prior_week_high": 101.0,
                   "known_resistance": [101.2, 102.0]},
        "bars": [
            {"time": "09:30", "o": 100.0, "h": 100.2, "l": 99.8, "c": 100.1},
            {"time": "09:35", "o": 100.1, "h": 100.5, "l": 99.9, "c": 100.3},
            {"time": "09:40", "o": 100.3, "h": 100.7, "l": 100.2, "c": 100.6},
            {"time": "09:45", "o": 100.5, "h": 100.63, "l": 100.45, "c": 100.62},
        ],
    }


class SnapshotTests(unittest.TestCase):
    def test_only_closed_bars_are_usable(self):
        raw = [{"epoch_ms": epoch(9, 10, 0)}, {"epoch_ms": epoch(9, 10, 5)}]
        now = dt.datetime(2026, 9, 9, 10, 9, 59, tzinfo=ET)
        self.assertEqual(snapshot.closed_five_minute_bars(raw, now), raw[:1])

    def test_projection_uses_same_bar_historical_curve(self):
        current = [bar(20, i) for i in range(10)]
        history = []
        for day in range(10, 20):
            history.extend(bar(day, i) for i in range(78))
        result = snapshot.time_normalized_projection(current, history)
        self.assertAlmostEqual(result["expected_fraction"], 10 / 78)
        self.assertAlmostEqual(result["same_time_ratio_pct"], 100.0)
        self.assertAlmostEqual(result["projected"], 7800.0)

    def test_prior_week_and_resistance_use_completed_days(self):
        history = [
            {"date": f"2026-08-{day:02d}", "h": 100.0 + day / 10}
            for day in range(3, 15)
        ]
        high = snapshot.prior_completed_week_high(history, "2026-08-17")
        self.assertEqual(high, 101.4)
        self.assertIn(101.4, snapshot.known_resistance_levels(history, high))


class StrategyTests(unittest.TestCase):
    def test_all_gates_produce_research_candidate(self):
        candidate = evaluate_live(eligible_state())
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["status"], "RESEARCH_ONLY")
        self.assertGreaterEqual(candidate["target_r"], 2.5)
        self.assertEqual(candidate["stop"], 100.45)

    def test_touch_without_bullish_reclaim_does_not_enter(self):
        state = eligible_state()
        state["bars"][-1].update({"o": 100.6, "h": 100.62, "l": 100.4, "c": 100.45})
        self.assertIsNone(evaluate_live(state))

    def test_fallback_tape_never_produces_candidate(self):
        self.assertIsNone(evaluate_live({"symbol": "SPY", "source": "fallback-daily"}))


class ShadowPaperTests(unittest.TestCase):
    @patch.object(monitor, "journal")
    @patch.object(monitor, "send_alert", return_value={"status": "ok"})
    def test_next_bar_limit_fill_creates_cash_capped_position(self, _alert, _journal):
        state = monitor.default_state()
        state["pending"] = {
            "created_asof": "2026-09-09 09:50 ET",
            "valid_bar_epoch_ms": epoch(9, 9, 50),
            "limit": 100.65, "stop": 100.45, "target": 101.2,
        }
        next_bar = {
            "date": "2026-09-09", "time": "09:50", "epoch_ms": epoch(9, 9, 50),
            "o": 100.64, "h": 101.0, "l": 100.5, "c": 100.9, "v": 1000,
        }
        alerts = []
        monitor.process_paper_bars(state, [next_bar], alerts, dry_run=True)
        self.assertIsNone(state["pending"])
        self.assertEqual(state["position"]["entry"], 100.65)
        self.assertEqual(state["position"]["quantity"], 75)
        self.assertEqual(state["position"]["session_dates"], ["2026-09-09"])
        self.assertEqual(len(alerts), 1)

    @patch.object(monitor, "journal")
    @patch.object(monitor, "send_alert", return_value={"status": "ok"})
    def test_position_times_out_at_third_session_close(self, _alert, _journal):
        state = monitor.default_state()
        state["position"] = {
            "entry_date": "2026-09-09", "session_dates": ["2026-09-09", "2026-09-10"],
            "entry_epoch_ms": epoch(9, 9, 50), "entry": 100.0, "quantity": 10,
            "risk_per_share": 1.0, "stop": 99.0, "target": 102.0,
            "entry_commission": 1.0,
        }
        bars = [bar(11, i) for i in range(78)]
        monitor.process_paper_bars(state, bars, [], dry_run=True)
        self.assertIsNone(state["position"])
        self.assertEqual(_journal.call_args.args[0]["reason"], "time")


if __name__ == "__main__":
    unittest.main()
