#!/usr/bin/env python3
"""Frozen shadow-paper rules for the SPY opening-drive percentage retest.

Research/alert only. This module cannot submit a broker order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StrategyConfig:
    strategy_id: str = "spy-orb-percentage-retest-v0-paper"
    symbol: str = "SPY"
    impulse_discount_bps: float = 20.0       # entry anchor = 99.80% of drive high
    entry_limit_buffer_bps: float = 2.0
    min_stop_bps: float = 5.0
    max_stop_bps: float = 50.0               # preservation stop <= 0.50%
    min_target_r: float = 2.5
    prior_day_high_proximity: float = 0.98
    prior_week_high_proximity: float = 0.97
    min_breakout_relative_volume: float = 1.0
    breakout_volume_lookback: int = 20
    first_entry_bar: int = 3                 # first reclaim bar starts at 09:45
    last_confirmation_bar: int = 29          # 11:55-12:00 bar
    max_hold_sessions: int = 3
    risk_fraction: float = 0.0025             # 0.25% equity; no same-day retry
    slippage_bps_each_side: float = 1.0
    commission_per_share: float = 0.005
    minimum_commission: float = 1.0


CONFIG = StrategyConfig()


def clv(bar: dict) -> float:
    spread = float(bar["h"]) - float(bar["l"])
    return 0.0 if spread <= 0 else (
        2 * float(bar["c"]) - float(bar["l"]) - float(bar["h"])
    ) / spread


def evaluate_live(state: dict, config: StrategyConfig = CONFIG) -> dict | None:
    """Return a next-bar plan only when the latest closed bar reclaims the anchor."""
    if state.get("symbol") != config.symbol or state.get("source") == "fallback-daily":
        return None
    bars = state.get("bars", [])
    n = len(bars)
    if n < 4 or n - 1 > config.last_confirmation_bar:
        return None
    b1, b2, b3 = bars[:3]
    levels = state.get("levels", {})
    prior_high = float(levels["prior_high"])
    prior_week_high = float(levels["prior_week_high"])
    prior_close = float(state["prev_close"])
    relative_volume = state.get("opening", {}).get("breakout_relative_volume")
    if relative_volume is None:
        return None

    # The directional premise is fixed at 09:45 ET from completed bars only.
    if not (
        float(b2["c"]) > float(b1["h"])
        and float(b2["l"]) >= float(b1["l"])
        and float(b3["c"]) > float(b2["c"])
        and float(b3["c"]) > float(b3["o"])
        and prior_close >= prior_high * config.prior_day_high_proximity
        and prior_close >= prior_week_high * config.prior_week_high_proximity
        and float(relative_volume) >= config.min_breakout_relative_volume
    ):
        return None

    impulse_high = max(float(bar["h"]) for bar in (b1, b2, b3))
    anchor = impulse_high * (1 - config.impulse_discount_bps / 10_000)
    if anchor >= float(b3["c"]):
        return None

    latest_index = n - 1
    latest = bars[-1]
    touched = any(float(bar["l"]) <= anchor for bar in bars[config.first_entry_bar:n])
    if not (
        touched
        and float(latest["c"]) > anchor
        and float(latest["c"]) > float(latest["o"])
        and clv(latest) >= 0.5
    ):
        return None

    entry = float(latest["c"]) * (1 + config.entry_limit_buffer_bps / 10_000)
    stop = float(latest["l"])
    risk = entry - stop
    risk_bps = risk / entry * 10_000
    if not config.min_stop_bps <= risk_bps <= config.max_stop_bps:
        return None
    minimum_target = entry + config.min_target_r * risk
    resistance = list(levels.get("known_resistance", [])) + [impulse_high, prior_high, prior_week_high]
    targets = sorted(set(float(level) for level in resistance if float(level) >= minimum_target))
    if not targets:
        return None
    target = targets[0]

    return {
        "kind": "trade_candidate",
        "status": "RESEARCH_ONLY",
        "strategy_id": config.strategy_id,
        "symbol": config.symbol,
        "side": "BUY",
        "signal_asof": state["asof"],
        "signal_bar_start": latest["time"],
        "entry": {
            "instruction": "next five-minute bar; buy limit; cancel if not filled",
            "limit": round(entry, 4),
        },
        "stop": round(stop, 4),
        "target": round(target, 4),
        "target_r": round((target - entry) / risk, 4),
        "time_exit": "close of the third trading session",
        "risk_fraction": config.risk_fraction,
        "evidence": {
            "anchor": round(anchor, 4),
            "anchor_pct_of_impulse_high": round(anchor / impulse_high * 100, 2),
            "impulse_high": round(impulse_high, 4),
            "prior_day_high": round(prior_high, 4),
            "prior_week_high": round(prior_week_high, 4),
            "breakout_relative_volume": round(float(relative_volume), 3),
            "confirmation_bar": latest_index,
            "signal_bar_low": round(float(latest["l"]), 4),
            "stop_distance_bps": round(risk_bps, 2),
        },
        "config": asdict(config),
    }
