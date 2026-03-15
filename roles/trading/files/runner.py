#!/usr/bin/env python3
"""ATLAS Backtrader Runner — executes strategies against VictoriaMetrics OHLC data."""

import argparse
import importlib.util
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone

import backtrader as bt
import numpy as np
import pandas as pd
import requests

VM_URL = os.environ.get("VICTORIAMETRICS_URL", "http://victoriametrics:8428")
PG_DSN = os.environ.get("PG_DSN", "postgresql://postgres:postgres@shared-db-pod:5432/postgres")


class TradeRecorder(bt.Analyzer):
    """Records individual trades with entry/exit details."""

    def __init__(self):
        self.trades = []
        self._open_trades = {}

    def notify_trade(self, trade):
        if trade.isopen:
            self._open_trades[trade.ref] = {
                "entry_date": self.data.datetime.datetime(0).isoformat(),
                "entry_price": trade.price,
                "direction": "long" if trade.size > 0 else "short",
                "size": abs(trade.size),
            }
        elif trade.isclosed:
            open_trade = self._open_trades.pop(trade.ref, {})
            open_trade.update({
                "exit_date": self.data.datetime.datetime(0).isoformat(),
                "exit_price": trade.price,
                "pnl": round(trade.pnl, 2),
                "pnl_pct": round(trade.pnl / (trade.price * abs(trade.size)) * 100, 4) if (trade.price and trade.size) else 0,
                "commission": round(trade.commission, 2),
                "bars_held": trade.barlen or 0,
            })
            self.trades.append(open_trade)

    def get_analysis(self):
        return {"trades": self.trades}


class EquityCurveRecorder(bt.Analyzer):
    """Records daily equity curve."""

    def __init__(self):
        self.equity_curve = []

    def next(self):
        self.equity_curve.append({
            "date": self.data.datetime.datetime(0).isoformat(),
            "value": round(self.strategy.broker.getvalue(), 2),
        })

    def get_analysis(self):
        return {"equity_curve": self.equity_curve}


def fetch_ohlc_from_vm(symbol, timeframe, start, end):
    """Fetch OHLC data from VictoriaMetrics using /api/v1/export.

    Uses the export API (no point limit) instead of query_range.
    Merges data from all sources (mt5, dataset, ibkr) by timestamp,
    preferring the latest-written value for overlapping timestamps.
    """
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    metrics = {}
    for field in ["open", "high", "low", "close", "volume"]:
        field_data = {}
        # Export streams JSONL (one line per series) — merges all sources
        resp = requests.get(
            f"{VM_URL}/api/v1/export",
            params={
                "match[]": f'ohlc_{field}{{symbol="{symbol}",timeframe="{timeframe}"}}',
                "start": start_iso,
                "end": end_iso,
                "format": "json",
            },
            timeout=300,
            stream=True,
        )
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                d = json.loads(line)
                for ts_ms, val in zip(d["timestamps"], d["values"]):
                    ts = ts_ms // 1000  # ms -> seconds
                    field_data[ts] = val  # later source overwrites earlier
        metrics[field] = field_data

    if not metrics.get("close"):
        print(f"ERROR: No OHLC data found for {symbol} {timeframe} in VictoriaMetrics", file=sys.stderr)
        sys.exit(1)

    timestamps = sorted(metrics["close"].keys())
    rows = []
    for ts in timestamps:
        rows.append({
            "datetime": datetime.fromtimestamp(ts, tz=timezone.utc),
            "open": metrics.get("open", {}).get(ts, 0),
            "high": metrics.get("high", {}).get(ts, 0),
            "low": metrics.get("low", {}).get(ts, 0),
            "close": metrics["close"][ts],
            "volume": metrics.get("volume", {}).get(ts, 0),
        })

    df = pd.DataFrame(rows)
    df.set_index("datetime", inplace=True)
    df = df[df["close"] > 0]
    print(f"Loaded {len(df)} bars for {symbol} {timeframe} from VictoriaMetrics")
    return df


def load_strategy(strategy_path):
    """Dynamically load a strategy class from a .py file."""
    spec = importlib.util.spec_from_file_location("user_strategy", strategy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["user_strategy"] = module

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, bt.Strategy) and attr is not bt.Strategy:
            return attr

    print(f"ERROR: No Strategy subclass found in {strategy_path}", file=sys.stderr)
    sys.exit(1)


def compute_metrics(cerebro_result, initial_cash, equity_curve, trades):
    """Compute comprehensive performance metrics."""
    final_value = cerebro_result[0].broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100

    equity_values = [e["value"] for e in equity_curve]
    if not equity_values:
        equity_values = [initial_cash]

    # Drawdown
    peak = equity_values[0]
    max_dd = 0
    dd_start = 0
    max_dd_duration = 0
    current_dd_start = 0
    for i, val in enumerate(equity_values):
        if val > peak:
            peak = val
            if current_dd_start > 0:
                max_dd_duration = max(max_dd_duration, i - current_dd_start)
            current_dd_start = 0
        else:
            dd = (peak - val) / peak * 100
            if dd > max_dd:
                max_dd = dd
            if current_dd_start == 0:
                current_dd_start = i

    # Returns for Sharpe/Sortino
    daily_returns = []
    for i in range(1, len(equity_values)):
        if equity_values[i - 1] > 0:
            daily_returns.append((equity_values[i] - equity_values[i - 1]) / equity_values[i - 1])

    sharpe = 0
    sortino = 0
    if daily_returns:
        avg_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns)
        if std_ret > 0:
            sharpe = round((avg_ret / std_ret) * math.sqrt(252), 4)
        downside = np.std([r for r in daily_returns if r < 0]) if any(r < 0 for r in daily_returns) else 0
        if downside > 0:
            sortino = round((avg_ret / downside) * math.sqrt(252), 4)

    # Trade stats
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # CAGR
    days = len(equity_values)
    years = days / 252 if days > 0 else 1
    cagr = ((final_value / initial_cash) ** (1 / years) - 1) * 100 if years > 0 and initial_cash > 0 else 0

    # Monthly returns
    monthly = {}
    for e in equity_curve:
        month = e["date"][:7]
        if month not in monthly:
            monthly[month] = {"start": e["value"], "end": e["value"]}
        monthly[month]["end"] = e["value"]
    monthly_returns = []
    for month, vals in sorted(monthly.items()):
        if vals["start"] > 0:
            monthly_returns.append({
                "month": month,
                "return_pct": round((vals["end"] - vals["start"]) / vals["start"] * 100, 4),
            })

    return {
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return, 4),
        "cagr_pct": round(cagr, 4),
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown_pct": round(max_dd, 4),
        "max_drawdown_duration_days": max_dd_duration,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "total_trades": len(trades),
        "avg_trade_pnl": round(np.mean([t["pnl"] for t in trades]), 2) if trades else 0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "largest_win": round(max((t["pnl"] for t in trades), default=0), 2),
        "largest_loss": round(min((t["pnl"] for t in trades), default=0), 2),
        "commission_total": round(sum(t.get("commission", 0) for t in trades), 2),
        "monthly_returns": monthly_returns,
    }


def store_results_pg(results):
    """Store backtest results in PostgreSQL."""
    try:
        import psycopg2
        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trading.backtest_results
            (run_id, strategy_name, strategy_params, symbol, timeframe,
             start_date, end_date, initial_cash, final_value, total_return_pct,
             cagr_pct, sharpe_ratio, sortino_ratio, max_drawdown_pct,
             max_drawdown_duration_days, win_rate, profit_factor, total_trades,
             avg_trade_pnl, avg_win, avg_loss, commission_total,
             equity_curve, monthly_returns)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            results["run_id"], results["strategy_name"],
            json.dumps(results.get("strategy_params", {})),
            results["symbol"], results["timeframe"],
            results["start_date"], results["end_date"],
            results["initial_cash"], results["final_value"],
            results["total_return_pct"], results["cagr_pct"],
            results["sharpe_ratio"], results["sortino_ratio"],
            results["max_drawdown_pct"], results["max_drawdown_duration_days"],
            results["win_rate"], results["profit_factor"],
            results["total_trades"], results["avg_trade_pnl"],
            results["avg_win"], results["avg_loss"],
            results["commission_total"],
            json.dumps(results.get("equity_curve", [])),
            json.dumps(results.get("monthly_returns", [])),
        ))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Results stored in PostgreSQL: run_id={results['run_id']}")
    except Exception as e:
        print(f"WARNING: Failed to store in PostgreSQL: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="ATLAS Backtrader Runner")
    parser.add_argument("--strategy", required=True, help="Path to strategy .py file")
    parser.add_argument("--symbol", default="SPY", help="Trading symbol")
    parser.add_argument("--timeframe", default="1d", help="Primary OHLC timeframe")
    parser.add_argument("--resample", default="", help="Comma-separated higher timeframes to resample from 1m (e.g., 5m,15m,1h,4h,1d)")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--cash", type=float, default=25000, help="Initial cash")
    parser.add_argument("--commission", type=float, default=0.65, help="Commission per trade ($)")
    parser.add_argument("--output", default="/results/result.json", help="Output JSON path")
    parser.add_argument("--store-pg", action="store_true", help="Store results in PostgreSQL")
    parser.add_argument("--warmup-start", default="", help="Earlier start date for indicator warmup (data loaded from here, metrics from --start)")
    args = parser.parse_args()

    resample_tfs = [tf.strip() for tf in args.resample.split(",") if tf.strip()] if args.resample else []

    data_start = args.warmup_start if args.warmup_start else args.start
    warmup_active = bool(args.warmup_start)

    print(f"ATLAS Backtrader Runner")
    print(f"Strategy: {args.strategy}")
    print(f"Symbol: {args.symbol} | Timeframe: {args.timeframe}")
    if resample_tfs:
        print(f"Resampled timeframes: {', '.join(resample_tfs)} (built from 1m bars)")
    if warmup_active:
        print(f"Warmup: {data_start} to {args.start} (indicators only)")
    print(f"Period: {args.start} to {args.end}")
    print(f"Cash: ${args.cash:,.2f} | Commission: ${args.commission}")
    print("---")

    # If resampling requested, always fetch 1m data and let Backtrader resample
    if resample_tfs:
        base_tf = "1m"
    else:
        base_tf = args.timeframe

    df = fetch_ohlc_from_vm(args.symbol, base_tf, data_start, args.end)
    strategy_cls = load_strategy(args.strategy)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls)

    # Backtrader timeframe + compression mapping
    TF_MAP = {
        "1m":  (bt.TimeFrame.Minutes, 1),
        "5m":  (bt.TimeFrame.Minutes, 5),
        "15m": (bt.TimeFrame.Minutes, 15),
        "1h":  (bt.TimeFrame.Minutes, 60),
        "4h":  (bt.TimeFrame.Minutes, 240),
        "1d":  (bt.TimeFrame.Days, 1),
        "1w":  (bt.TimeFrame.Weeks, 1),
    }

    data0 = bt.feeds.PandasData(dataname=df)

    if resample_tfs:
        # Add base 1m data
        cerebro.adddata(data0, name=f"{args.symbol}_1m")

        # Add resampled higher timeframes
        for tf in resample_tfs:
            if tf not in TF_MAP:
                print(f"WARNING: Unknown timeframe '{tf}' for resampling, skipping")
                continue
            bt_tf, compression = TF_MAP[tf]
            cerebro.resampledata(data0, name=f"{args.symbol}_{tf}",
                                 timeframe=bt_tf, compression=compression)
            print(f"  Added resampled data: {args.symbol}_{tf}")
    else:
        cerebro.adddata(data0)

    cerebro.broker.setcash(args.cash)
    cerebro.broker.setcommission(commission=args.commission, commtype=bt.CommInfoBase.COMM_FIXED)

    cerebro.addanalyzer(TradeRecorder, _name="trade_recorder")
    cerebro.addanalyzer(EquityCurveRecorder, _name="equity_curve")

    result = cerebro.run()
    strat = result[0]

    trade_analysis = strat.analyzers.trade_recorder.get_analysis()
    equity_analysis = strat.analyzers.equity_curve.get_analysis()

    trades = trade_analysis["trades"]
    equity_curve = equity_analysis["equity_curve"]

    # When warmup is active, filter equity and trades to the actual evaluation period
    if warmup_active:
        eval_start = args.start
        equity_curve = [e for e in equity_curve if e["date"] >= eval_start]
        trades = [t for t in trades if t.get("exit_date", t.get("entry_date", "")) >= eval_start]
        # Reset initial cash to the equity value at evaluation start
        if equity_curve:
            args.cash = equity_curve[0]["value"]

    metrics = compute_metrics(result, args.cash, equity_curve, trades)

    run_id = str(uuid.uuid4())
    strategy_name = strategy_cls.__name__
    strategy_params = {k: v for k, v in strategy_cls.params._getitems()} if hasattr(strategy_cls.params, '_getitems') else {}

    output = {
        "run_id": run_id,
        "strategy_name": strategy_name,
        "strategy_params": strategy_params,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "start_date": args.start,
        "end_date": args.end,
        "initial_cash": args.cash,
        **metrics,
        "trades": trades,
        "equity_curve": equity_curve,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n=== RESULTS ===")
    print(f"Strategy: {strategy_name}")
    print(f"Final Value: ${metrics['final_value']:,.2f}")
    print(f"Total Return: {metrics['total_return_pct']:.2f}%")
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"Sortino Ratio: {metrics['sortino_ratio']:.2f}")
    print(f"Max Drawdown: {metrics['max_drawdown_pct']:.2f}%")
    print(f"Win Rate: {metrics['win_rate']:.1%}")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"Total Trades: {metrics['total_trades']}")
    print(f"Output: {args.output}")

    if args.store_pg:
        store_results_pg(output)


if __name__ == "__main__":
    main()
