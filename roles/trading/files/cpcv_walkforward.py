#!/usr/bin/env python3
"""
CPCV Walk-Forward Validation for ATLAS Trading System.

Combinatorial Purged Cross-Validation with walk-forward optimization.
Runs on VPS host, invokes backtrader container via podman for each fold.

Usage:
    python3 /opt/compose/backtrader-build/cpcv_walkforward.py
    python3 /opt/compose/backtrader-build/cpcv_walkforward.py --parallel 4
    python3 /opt/compose/backtrader-build/cpcv_walkforward.py --train-years 3 --test-months 6
"""

import argparse
import json
import math
import os
import subprocess
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
STRATEGY_FILE = "/opt/compose/backtrader-strategies/exhaustion_confluence_v3.py"
RESULTS_DIR = "/opt/compose/backtrader-results"
CONTAINER_IMAGE = "backtrader-atlas:latest"
SYMBOL = "SPY"
TIMEFRAME = "1d"
INITIAL_CASH = 25000
COMMISSION = 0.65
WARMUP_DAYS = 365  # Calendar days of extra data before OOS window for indicator warmup

# Environment overrides for runner.py inside container
# (container names not in pods aren't resolvable by pod name)
RUNNER_ENV = {
    "VICTORIAMETRICS_URL": os.environ.get(
        "VICTORIAMETRICS_URL", "http://metrics-pod:8428"
    ),
    "PG_DSN": os.environ.get(
        "PG_DSN", "postgresql://postgres:postgres@postgres:5432/enterprise"
    ),
}

DATA_START = date(2008, 1, 1)
HOLDOUT_START = date(2024, 1, 1)
HOLDOUT_END = date(2026, 3, 6)

PG_DSN = "postgresql://postgres:postgres@postgres:5432/enterprise"

# ---------------------------------------------------------------------------
# Fold generation
# ---------------------------------------------------------------------------

def generate_folds(data_start, holdout_start, train_years, test_months, step_months, purge_days):
    """Generate train/test fold date ranges with purge gap.

    Returns list of dicts with keys:
        fold, train_start, train_end, test_start, test_end
    """
    folds = []
    fold_num = 0
    cursor = data_start

    while True:
        train_start = cursor
        train_end_raw = date(
            train_start.year + train_years,
            train_start.month,
            train_start.day,
        )
        # Clamp to avoid exceeding holdout boundary
        train_end = min(train_end_raw, holdout_start - timedelta(days=purge_days + 1))

        if train_end <= train_start:
            break

        test_start = train_end + timedelta(days=purge_days)
        test_end_raw = _add_months(test_start, test_months)
        test_end = min(test_end_raw, holdout_start - timedelta(days=1))

        if test_start >= holdout_start or test_end <= test_start:
            break

        fold_num += 1
        folds.append({
            "fold": fold_num,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })

        # Step forward
        cursor = _add_months(cursor, step_months)
        if cursor >= holdout_start:
            break

    return folds


def _add_months(d, months):
    """Add calendar months to a date."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, 28)  # safe for all months
    return date(year, month, day)


# ---------------------------------------------------------------------------
# Podman runner
# ---------------------------------------------------------------------------

def run_backtest(label, strategy_path, symbol, timeframe, start_date, end_date,
                 cash, commission, output_path, warmup_start=None):
    """Run a single backtest via podman and return parsed JSON results.

    Returns (label, results_dict) on success, (label, None) on failure.
    If warmup_start is provided, data is loaded from that date but metrics
    are calculated only from start_date onwards.
    """
    env_args = []
    for k, v in RUNNER_ENV.items():
        env_args.extend(["-e", f"{k}={v}"])
    cmd = [
        "podman", "run", "--rm",
        "--network", "enterprise_network",
        *env_args,
        "-v", "/opt/compose/backtrader-strategies:/strategies:Z",
        "-v", f"{RESULTS_DIR}:/results:Z",
        CONTAINER_IMAGE,
        "--strategy", f"/strategies/{os.path.basename(strategy_path)}",
        "--symbol", symbol,
        "--timeframe", timeframe,
        "--start", start_date,
        "--end", end_date,
        "--cash", str(cash),
        "--commission", str(commission),
        "--output", f"/results/{os.path.basename(output_path)}",
        "--store-pg",
    ]
    if warmup_start:
        cmd.extend(["--warmup-start", warmup_start])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            print(f"  [FAIL] {label}: exit code {result.returncode}", file=sys.stderr)
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    print(f"         {line}", file=sys.stderr)
            return (label, None)

        # Parse output JSON
        if os.path.exists(output_path):
            with open(output_path) as f:
                data = json.load(f)
            return (label, data)
        else:
            print(f"  [FAIL] {label}: output file not found at {output_path}", file=sys.stderr)
            return (label, None)

    except subprocess.TimeoutExpired:
        print(f"  [FAIL] {label}: timed out after 300s", file=sys.stderr)
        return (label, None)
    except Exception as e:
        print(f"  [FAIL] {label}: {e}", file=sys.stderr)
        return (label, None)


def run_fold(fold, batch_id, strategy_path, symbol, timeframe, cash, commission):
    """Run train + test for a single fold. Returns fold result dict."""
    fold_num = fold["fold"]
    ts = fold["train_start"].isoformat()
    te = fold["train_end"].isoformat()
    os_start = fold["test_start"].isoformat()
    os_end = fold["test_end"].isoformat()

    print(f"  Fold {fold_num:2d}: TRAIN {ts} -> {te}  |  TEST {os_start} -> {os_end}")

    # In-sample (train)
    is_output = os.path.join(RESULTS_DIR, f"cpcv_{batch_id}_fold{fold_num}_IS.json")
    is_label = f"Fold {fold_num} IS"
    _, is_data = run_backtest(
        is_label, strategy_path, symbol, timeframe, ts, te, cash, commission, is_output
    )

    # Out-of-sample (test) — with warmup buffer for indicator lookback
    oos_output = os.path.join(RESULTS_DIR, f"cpcv_{batch_id}_fold{fold_num}_OOS.json")
    oos_label = f"Fold {fold_num} OOS"
    warmup_date = (fold["test_start"] - timedelta(days=WARMUP_DAYS)).isoformat()
    _, oos_data = run_backtest(
        oos_label, strategy_path, symbol, timeframe, os_start, os_end, cash, commission,
        oos_output, warmup_start=warmup_date
    )

    return {
        "fold": fold_num,
        "train_start": ts,
        "train_end": te,
        "test_start": os_start,
        "test_end": os_end,
        "is_data": is_data,
        "oos_data": oos_data,
    }


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio
# ---------------------------------------------------------------------------

def deflated_sharpe_ratio(observed_sharpe, num_trials, avg_sharpe, var_sharpe,
                          skew_returns, kurt_returns, backtest_length):
    """Compute Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Returns probability that observed Sharpe is genuine (0-1).
    """
    if var_sharpe <= 0 or num_trials <= 1 or backtest_length <= 1:
        return 0.0

    # Expected maximum Sharpe under null (Euler-Mascheroni correction)
    euler_mascheroni = 0.5772
    e_max_sharpe = avg_sharpe + math.sqrt(var_sharpe) * (
        (1 - euler_mascheroni) * _norm_ppf(1 - 1 / num_trials)
        + euler_mascheroni * _norm_ppf(1 - 1 / (num_trials * math.e))
    )

    # Standard error of Sharpe estimate
    sr_std = math.sqrt(
        (1 - skew_returns * observed_sharpe
         + ((kurt_returns - 1) / 4) * observed_sharpe ** 2)
        / (backtest_length - 1)
    )

    if sr_std <= 0:
        return 0.0

    z = (observed_sharpe - e_max_sharpe) / sr_std
    return _norm_cdf(z)


def _norm_cdf(x):
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_ppf(p):
    """Approximate inverse normal CDF (Beasley-Springer-Moro)."""
    if p <= 0:
        return -6.0
    if p >= 1:
        return 6.0
    # Rational approximation for central region
    if 0.5 - abs(p - 0.5) > 1e-10:
        t = math.sqrt(-2 * math.log(min(p, 1 - p)))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
        if p < 0.5:
            return -result
        return result
    return 0.0


# ---------------------------------------------------------------------------
# PostgreSQL storage
# ---------------------------------------------------------------------------

def create_cpcv_tables():
    """Create CPCV tables in PostgreSQL via podman exec."""
    sql = """
    CREATE TABLE IF NOT EXISTS trading.cpcv_folds (
        id SERIAL PRIMARY KEY,
        batch_id UUID NOT NULL,
        fold_number INT NOT NULL,
        train_start DATE,
        train_end DATE,
        test_start DATE,
        test_end DATE,
        purge_days INT DEFAULT 5,
        is_return_pct NUMERIC(12,4),
        is_sharpe NUMERIC(8,4),
        is_sortino NUMERIC(8,4),
        is_max_dd_pct NUMERIC(8,4),
        is_win_rate NUMERIC(8,4),
        is_profit_factor NUMERIC(8,4),
        is_trades INT,
        is_run_id UUID,
        oos_return_pct NUMERIC(12,4),
        oos_sharpe NUMERIC(8,4),
        oos_sortino NUMERIC(8,4),
        oos_max_dd_pct NUMERIC(8,4),
        oos_win_rate NUMERIC(8,4),
        oos_profit_factor NUMERIC(8,4),
        oos_trades INT,
        oos_run_id UUID,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_cpcv_folds_batch ON trading.cpcv_folds(batch_id);

    CREATE TABLE IF NOT EXISTS trading.cpcv_summary (
        id SERIAL PRIMARY KEY,
        batch_id UUID NOT NULL,
        strategy_name TEXT,
        symbol TEXT,
        timeframe TEXT,
        total_folds INT,
        train_window_years INT,
        test_window_months INT,
        avg_is_sharpe NUMERIC(8,4),
        avg_oos_sharpe NUMERIC(8,4),
        sharpe_degradation_pct NUMERIC(8,4),
        avg_is_return_pct NUMERIC(12,4),
        avg_oos_return_pct NUMERIC(12,4),
        oos_profitable_pct NUMERIC(8,4),
        oos_consistency_score NUMERIC(8,4),
        avg_oos_profit_factor NUMERIC(8,4),
        holdout_return_pct NUMERIC(12,4),
        holdout_sharpe NUMERIC(8,4),
        holdout_trades INT,
        holdout_run_id UUID,
        deflated_sharpe NUMERIC(8,4),
        overfit_flag BOOLEAN,
        verdict TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_cpcv_summary_batch ON trading.cpcv_summary(batch_id);
    """

    cmd = ["podman", "exec", "-i", "postgres", "psql", "-U", "postgres", "-d", "enterprise"]
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"WARNING: Table creation returned code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"  {result.stderr.strip()}", file=sys.stderr)
    else:
        print("CPCV tables ensured in PostgreSQL.")


def store_fold_pg(batch_id, fold_result, purge_days):
    """Store a single fold result in trading.cpcv_folds."""
    is_d = fold_result.get("is_data") or {}
    oos_d = fold_result.get("oos_data") or {}

    sql = f"""
    INSERT INTO trading.cpcv_folds (
        batch_id, fold_number, train_start, train_end, test_start, test_end, purge_days,
        is_return_pct, is_sharpe, is_sortino, is_max_dd_pct, is_win_rate, is_profit_factor, is_trades, is_run_id,
        oos_return_pct, oos_sharpe, oos_sortino, oos_max_dd_pct, oos_win_rate, oos_profit_factor, oos_trades, oos_run_id
    ) VALUES (
        '{batch_id}', {fold_result['fold']},
        '{fold_result['train_start']}', '{fold_result['train_end']}',
        '{fold_result['test_start']}', '{fold_result['test_end']}',
        {purge_days},
        {_sql_num(is_d.get('total_return_pct'))},
        {_sql_num(is_d.get('sharpe_ratio'))},
        {_sql_num(is_d.get('sortino_ratio'))},
        {_sql_num(is_d.get('max_drawdown_pct'))},
        {_sql_num(is_d.get('win_rate'))},
        {_sql_num(is_d.get('profit_factor'))},
        {_sql_int(is_d.get('total_trades'))},
        {_sql_uuid(is_d.get('run_id'))},
        {_sql_num(oos_d.get('total_return_pct'))},
        {_sql_num(oos_d.get('sharpe_ratio'))},
        {_sql_num(oos_d.get('sortino_ratio'))},
        {_sql_num(oos_d.get('max_drawdown_pct'))},
        {_sql_num(oos_d.get('win_rate'))},
        {_sql_num(oos_d.get('profit_factor'))},
        {_sql_int(oos_d.get('total_trades'))},
        {_sql_uuid(oos_d.get('run_id'))}
    );
    """
    _exec_sql(sql)


def store_summary_pg(summary):
    """Store CPCV summary in PostgreSQL."""
    sql = f"""
    INSERT INTO trading.cpcv_summary (
        batch_id, strategy_name, symbol, timeframe, total_folds,
        train_window_years, test_window_months,
        avg_is_sharpe, avg_oos_sharpe, sharpe_degradation_pct,
        avg_is_return_pct, avg_oos_return_pct,
        oos_profitable_pct, oos_consistency_score, avg_oos_profit_factor,
        holdout_return_pct, holdout_sharpe, holdout_trades, holdout_run_id,
        deflated_sharpe, overfit_flag, verdict
    ) VALUES (
        '{summary['batch_id']}',
        '{summary['strategy_name']}',
        '{summary['symbol']}',
        '{summary['timeframe']}',
        {summary['total_folds']},
        {summary['train_window_years']},
        {summary['test_window_months']},
        {_sql_num(summary.get('avg_is_sharpe'))},
        {_sql_num(summary.get('avg_oos_sharpe'))},
        {_sql_num(summary.get('sharpe_degradation_pct'))},
        {_sql_num(summary.get('avg_is_return_pct'))},
        {_sql_num(summary.get('avg_oos_return_pct'))},
        {_sql_num(summary.get('oos_profitable_pct'))},
        {_sql_num(summary.get('oos_consistency_score'))},
        {_sql_num(summary.get('avg_oos_profit_factor'))},
        {_sql_num(summary.get('holdout_return_pct'))},
        {_sql_num(summary.get('holdout_sharpe'))},
        {_sql_int(summary.get('holdout_trades'))},
        {_sql_uuid(summary.get('holdout_run_id'))},
        {_sql_num(summary.get('deflated_sharpe'))},
        {'TRUE' if summary.get('overfit_flag') else 'FALSE'},
        '{summary.get('verdict', '').replace(chr(39), chr(39)+chr(39))}'
    );
    """
    _exec_sql(sql)


def _exec_sql(sql):
    """Execute SQL via podman exec into postgres container."""
    cmd = ["podman", "exec", "-i", "postgres", "psql", "-U", "postgres", "-d", "enterprise"]
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and result.stderr:
        # Ignore NOTICE messages (e.g., table already exists)
        errors = [l for l in result.stderr.strip().split("\n") if "ERROR" in l]
        if errors:
            print(f"  SQL error: {errors[0]}", file=sys.stderr)


def _sql_num(val):
    if val is None:
        return "NULL"
    return str(val)


def _sql_int(val):
    if val is None:
        return "NULL"
    return str(int(val))


def _sql_uuid(val):
    if val is None:
        return "NULL"
    return f"'{val}'"


# ---------------------------------------------------------------------------
# Metrics extraction helpers
# ---------------------------------------------------------------------------

def safe_metric(data, key, default=0.0):
    """Safely extract a numeric metric from backtest results."""
    if data is None:
        return default
    val = data.get(key, default)
    if val is None:
        return default
    return float(val)


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------

def compute_summary(batch_id, folds_results, holdout_data, strategy_name,
                    symbol, timeframe, train_years, test_months):
    """Compute aggregated CPCV summary metrics."""

    # Separate successful folds
    valid_folds = [f for f in folds_results if f.get("is_data") and f.get("oos_data")]
    total_folds = len(folds_results)
    successful_folds = len(valid_folds)

    if successful_folds == 0:
        return {
            "batch_id": batch_id,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "total_folds": total_folds,
            "train_window_years": train_years,
            "test_window_months": test_months,
            "verdict": "FAILED - no successful folds",
            "overfit_flag": True,
        }

    # In-sample metrics
    is_sharpes = [safe_metric(f["is_data"], "sharpe_ratio") for f in valid_folds]
    is_returns = [safe_metric(f["is_data"], "total_return_pct") for f in valid_folds]

    # Out-of-sample metrics
    oos_sharpes = [safe_metric(f["oos_data"], "sharpe_ratio") for f in valid_folds]
    oos_returns = [safe_metric(f["oos_data"], "total_return_pct") for f in valid_folds]
    oos_pfs = [safe_metric(f["oos_data"], "profit_factor") for f in valid_folds]

    avg_is_sharpe = sum(is_sharpes) / len(is_sharpes)
    avg_oos_sharpe = sum(oos_sharpes) / len(oos_sharpes)
    avg_is_return = sum(is_returns) / len(is_returns)
    avg_oos_return = sum(oos_returns) / len(oos_returns)
    avg_oos_pf = sum(oos_pfs) / len(oos_pfs)

    # Sharpe degradation
    if abs(avg_is_sharpe) > 0.0001:
        sharpe_degradation = (avg_is_sharpe - avg_oos_sharpe) / abs(avg_is_sharpe) * 100
    else:
        sharpe_degradation = 0.0

    # OOS consistency: % of folds with positive OOS return
    oos_profitable = sum(1 for r in oos_returns if r > 0)
    oos_profitable_pct = oos_profitable / successful_folds * 100

    # Consistency score: % of folds where OOS Sharpe > 0
    oos_positive_sharpe = sum(1 for s in oos_sharpes if s > 0)
    oos_consistency = oos_positive_sharpe / successful_folds * 100

    # Deflated Sharpe Ratio
    if len(oos_sharpes) >= 2:
        var_sharpe = sum((s - avg_oos_sharpe) ** 2 for s in oos_sharpes) / (len(oos_sharpes) - 1)

        # Collect all OOS daily returns for skew/kurtosis estimate
        all_oos_returns = []
        for f in valid_folds:
            ec = f["oos_data"].get("equity_curve", [])
            for i in range(1, len(ec)):
                prev = ec[i - 1].get("value", 0)
                curr = ec[i].get("value", 0)
                if prev > 0:
                    all_oos_returns.append((curr - prev) / prev)

        if len(all_oos_returns) > 3:
            mean_r = sum(all_oos_returns) / len(all_oos_returns)
            std_r = math.sqrt(sum((r - mean_r) ** 2 for r in all_oos_returns) / (len(all_oos_returns) - 1))
            if std_r > 0:
                skew_r = sum(((r - mean_r) / std_r) ** 3 for r in all_oos_returns) / len(all_oos_returns)
                kurt_r = sum(((r - mean_r) / std_r) ** 4 for r in all_oos_returns) / len(all_oos_returns)
            else:
                skew_r, kurt_r = 0.0, 3.0
            backtest_len = len(all_oos_returns)
        else:
            skew_r, kurt_r, backtest_len = 0.0, 3.0, 100

        dsr = deflated_sharpe_ratio(
            observed_sharpe=avg_oos_sharpe,
            num_trials=successful_folds,
            avg_sharpe=sum(is_sharpes) / len(is_sharpes),
            var_sharpe=var_sharpe,
            skew_returns=skew_r,
            kurt_returns=kurt_r,
            backtest_length=backtest_len,
        )
    else:
        dsr = 0.0

    # Holdout metrics
    holdout_return = safe_metric(holdout_data, "total_return_pct")
    holdout_sharpe = safe_metric(holdout_data, "sharpe_ratio")
    holdout_trades = int(safe_metric(holdout_data, "total_trades", 0))
    holdout_run_id = holdout_data.get("run_id") if holdout_data else None

    # Overfit determination
    overfit_flag = False
    reasons = []

    if sharpe_degradation > 50:
        overfit_flag = True
        reasons.append(f"Sharpe degrades {sharpe_degradation:.0f}% IS->OOS")
    if oos_profitable_pct < 50:
        overfit_flag = True
        reasons.append(f"Only {oos_profitable_pct:.0f}% OOS folds profitable")
    if dsr < 0.05:
        overfit_flag = True
        reasons.append(f"Deflated Sharpe {dsr:.3f} < 0.05")
    if avg_oos_sharpe < 0:
        overfit_flag = True
        reasons.append(f"Avg OOS Sharpe negative ({avg_oos_sharpe:.2f})")

    if overfit_flag:
        verdict = "OVERFIT - " + "; ".join(reasons)
    elif oos_profitable_pct >= 70 and avg_oos_sharpe > 0.5 and dsr > 0.10:
        verdict = "ROBUST - strategy shows genuine edge"
    elif oos_profitable_pct >= 60 and avg_oos_sharpe > 0:
        verdict = "MARGINAL - some edge but needs monitoring"
    else:
        verdict = "INCONCLUSIVE - insufficient evidence of robustness"

    return {
        "batch_id": batch_id,
        "strategy_name": strategy_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "total_folds": total_folds,
        "successful_folds": successful_folds,
        "train_window_years": train_years,
        "test_window_months": test_months,
        "avg_is_sharpe": round(avg_is_sharpe, 4),
        "avg_oos_sharpe": round(avg_oos_sharpe, 4),
        "sharpe_degradation_pct": round(sharpe_degradation, 4),
        "avg_is_return_pct": round(avg_is_return, 4),
        "avg_oos_return_pct": round(avg_oos_return, 4),
        "oos_profitable_pct": round(oos_profitable_pct, 4),
        "oos_consistency_score": round(oos_consistency, 4),
        "avg_oos_profit_factor": round(avg_oos_pf, 4),
        "deflated_sharpe": round(dsr, 4),
        "holdout_return_pct": round(holdout_return, 4),
        "holdout_sharpe": round(holdout_sharpe, 4),
        "holdout_trades": holdout_trades,
        "holdout_run_id": holdout_run_id,
        "overfit_flag": overfit_flag,
        "verdict": verdict,
        "folds_detail": [
            {
                "fold": f["fold"],
                "train": f"{f['train_start']} -> {f['train_end']}",
                "test": f"{f['test_start']} -> {f['test_end']}",
                "is_sharpe": safe_metric(f.get("is_data"), "sharpe_ratio"),
                "oos_sharpe": safe_metric(f.get("oos_data"), "sharpe_ratio"),
                "is_return": safe_metric(f.get("is_data"), "total_return_pct"),
                "oos_return": safe_metric(f.get("oos_data"), "total_return_pct"),
                "is_trades": int(safe_metric(f.get("is_data"), "total_trades", 0)),
                "oos_trades": int(safe_metric(f.get("oos_data"), "total_trades", 0)),
                "status": "OK" if f.get("is_data") and f.get("oos_data") else "FAILED",
            }
            for f in folds_results
        ],
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_summary(summary):
    """Print a formatted summary table to stdout."""
    W = 72

    print()
    print("=" * W)
    print("  CPCV WALK-FORWARD VALIDATION RESULTS")
    print("=" * W)
    print(f"  Batch ID:      {summary['batch_id']}")
    print(f"  Strategy:      {summary.get('strategy_name', 'N/A')}")
    print(f"  Symbol:        {summary.get('symbol', 'N/A')}  |  Timeframe: {summary.get('timeframe', 'N/A')}")
    print(f"  Train Window:  {summary.get('train_window_years', 0)} years")
    print(f"  Test Window:   {summary.get('test_window_months', 0)} months")
    print(f"  Folds:         {summary.get('successful_folds', 0)} / {summary.get('total_folds', 0)} successful")
    print("-" * W)

    # Fold detail table
    folds = summary.get("folds_detail", [])
    if folds:
        print(f"  {'Fold':>4}  {'IS Sharpe':>10}  {'OOS Sharpe':>11}  {'IS Ret%':>8}  {'OOS Ret%':>9}  {'IS Trd':>6}  {'OOS Trd':>7}  {'Status':>6}")
        print(f"  {'----':>4}  {'----------':>10}  {'-----------':>11}  {'-------':>8}  {'--------':>9}  {'------':>6}  {'-------':>7}  {'------':>6}")
        for f in folds:
            print(
                f"  {f['fold']:4d}"
                f"  {f['is_sharpe']:10.2f}"
                f"  {f['oos_sharpe']:11.2f}"
                f"  {f['is_return']:8.1f}"
                f"  {f['oos_return']:9.1f}"
                f"  {f['is_trades']:6d}"
                f"  {f['oos_trades']:7d}"
                f"  {f['status']:>6}"
            )
    print("-" * W)

    # Aggregated metrics
    print("  AGGREGATED METRICS")
    print(f"    Avg IS Sharpe:           {summary.get('avg_is_sharpe', 0):8.4f}")
    print(f"    Avg OOS Sharpe:          {summary.get('avg_oos_sharpe', 0):8.4f}")
    print(f"    Sharpe Degradation:      {summary.get('sharpe_degradation_pct', 0):8.1f}%")
    print(f"    Avg IS Return:           {summary.get('avg_is_return_pct', 0):8.2f}%")
    print(f"    Avg OOS Return:          {summary.get('avg_oos_return_pct', 0):8.2f}%")
    print(f"    OOS Profitable Folds:    {summary.get('oos_profitable_pct', 0):8.1f}%")
    print(f"    OOS Consistency Score:   {summary.get('oos_consistency_score', 0):8.1f}%")
    print(f"    Avg OOS Profit Factor:   {summary.get('avg_oos_profit_factor', 0):8.4f}")
    print(f"    Deflated Sharpe Ratio:   {summary.get('deflated_sharpe', 0):8.4f}")
    print("-" * W)

    # Holdout
    print("  HOLDOUT (2024-2026) — UNTOUCHED DATA")
    print(f"    Return:      {summary.get('holdout_return_pct', 0):8.2f}%")
    print(f"    Sharpe:      {summary.get('holdout_sharpe', 0):8.4f}")
    print(f"    Trades:      {summary.get('holdout_trades', 0)}")
    print("-" * W)

    # Verdict
    overfit = summary.get("overfit_flag", False)
    verdict = summary.get("verdict", "N/A")
    flag = "OVERFIT" if overfit else "PASS"
    print(f"  VERDICT: [{flag}]")
    print(f"    {verdict}")
    print("=" * W)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CPCV Walk-Forward Validation for ATLAS Trading System"
    )
    parser.add_argument("--strategy", default=STRATEGY_FILE,
                        help="Path to strategy file on VPS host")
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--timeframe", default=TIMEFRAME)
    parser.add_argument("--cash", type=float, default=INITIAL_CASH)
    parser.add_argument("--commission", type=float, default=COMMISSION)
    parser.add_argument("--train-years", type=int, default=4,
                        help="Training window in years (default: 4)")
    parser.add_argument("--test-months", type=int, default=6,
                        help="Test window in months (default: 6)")
    parser.add_argument("--step-months", type=int, default=6,
                        help="Step size in months (default: 6)")
    parser.add_argument("--purge-days", type=int, default=5,
                        help="Purge gap in trading days (default: 5)")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Number of parallel fold executions (default: 1)")
    parser.add_argument("--holdout-start", default=HOLDOUT_START.isoformat(),
                        help="Holdout period start (default: 2024-01-01)")
    parser.add_argument("--holdout-end", default=HOLDOUT_END.isoformat(),
                        help="Holdout period end (default: 2026-03-06)")
    parser.add_argument("--data-start", default=DATA_START.isoformat(),
                        help="Data start date (default: 2008-01-01)")
    parser.add_argument("--skip-holdout", action="store_true",
                        help="Skip holdout test (useful for debugging)")
    parser.add_argument("--skip-db", action="store_true",
                        help="Skip PostgreSQL storage")
    parser.add_argument("--output", default=os.path.join(RESULTS_DIR, "cpcv_summary.json"),
                        help="Output JSON summary path")
    args = parser.parse_args()

    batch_id = str(uuid.uuid4())
    data_start = date.fromisoformat(args.data_start)
    holdout_start = date.fromisoformat(args.holdout_start)
    holdout_end = date.fromisoformat(args.holdout_end)

    print("=" * 72)
    print("  ATLAS CPCV Walk-Forward Validation")
    print("=" * 72)
    print(f"  Batch ID:      {batch_id}")
    print(f"  Strategy:      {args.strategy}")
    print(f"  Symbol:        {args.symbol}  |  Timeframe: {args.timeframe}")
    print(f"  Data range:    {data_start} to {holdout_start} (training/test)")
    print(f"  Holdout:       {holdout_start} to {holdout_end}")
    print(f"  Train window:  {args.train_years} years")
    print(f"  Test window:   {args.test_months} months")
    print(f"  Step:          {args.step_months} months")
    print(f"  Purge gap:     {args.purge_days} trading days")
    print(f"  Parallelism:   {args.parallel}")
    print(f"  Cash:          ${args.cash:,.2f}  |  Commission: ${args.commission}")
    print()

    # Validate strategy file exists
    if not os.path.exists(args.strategy):
        print(f"ERROR: Strategy file not found: {args.strategy}", file=sys.stderr)
        sys.exit(1)

    # Ensure results directory exists
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Create PostgreSQL tables
    if not args.skip_db:
        print("--- Creating CPCV tables in PostgreSQL ---")
        create_cpcv_tables()
        print()

    # Generate folds
    folds = generate_folds(
        data_start=data_start,
        holdout_start=holdout_start,
        train_years=args.train_years,
        test_months=args.test_months,
        step_months=args.step_months,
        purge_days=args.purge_days,
    )

    if not folds:
        print("ERROR: No folds generated. Check date ranges and window sizes.", file=sys.stderr)
        sys.exit(1)

    print(f"--- Generated {len(folds)} folds ---")
    for f in folds:
        print(f"  Fold {f['fold']:2d}: TRAIN {f['train_start']} -> {f['train_end']}  |  TEST {f['test_start']} -> {f['test_end']}")
    print()

    # Execute folds
    print(f"--- Running {len(folds)} folds (parallel={args.parallel}) ---")
    start_time = datetime.now()
    folds_results = []

    if args.parallel <= 1:
        # Sequential execution
        for fold in folds:
            result = run_fold(
                fold, batch_id, args.strategy, args.symbol, args.timeframe,
                args.cash, args.commission,
            )
            folds_results.append(result)

            # Store fold in DB
            if not args.skip_db:
                store_fold_pg(batch_id, result, args.purge_days)

            # Progress
            done = len(folds_results)
            elapsed = (datetime.now() - start_time).total_seconds()
            eta = elapsed / done * (len(folds) - done) if done > 0 else 0
            is_ok = "OK" if result.get("is_data") else "FAIL"
            oos_ok = "OK" if result.get("oos_data") else "FAIL"
            print(f"    -> Fold {result['fold']}: IS={is_ok} OOS={oos_ok}  "
                  f"[{done}/{len(folds)}  ETA: {eta:.0f}s]")
    else:
        # Parallel execution
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            futures = {}
            for fold in folds:
                future = executor.submit(
                    run_fold, fold, batch_id, args.strategy, args.symbol,
                    args.timeframe, args.cash, args.commission,
                )
                futures[future] = fold["fold"]

            for future in as_completed(futures):
                fold_num = futures[future]
                try:
                    result = future.result()
                    folds_results.append(result)

                    if not args.skip_db:
                        store_fold_pg(batch_id, result, args.purge_days)

                    done = len(folds_results)
                    is_ok = "OK" if result.get("is_data") else "FAIL"
                    oos_ok = "OK" if result.get("oos_data") else "FAIL"
                    print(f"    -> Fold {fold_num}: IS={is_ok} OOS={oos_ok}  "
                          f"[{done}/{len(folds)}]")
                except Exception as e:
                    print(f"    -> Fold {fold_num}: EXCEPTION {e}", file=sys.stderr)
                    folds_results.append({
                        "fold": fold_num,
                        "train_start": "", "train_end": "",
                        "test_start": "", "test_end": "",
                        "is_data": None, "oos_data": None,
                    })

    # Sort results by fold number
    folds_results.sort(key=lambda x: x["fold"])

    elapsed_total = (datetime.now() - start_time).total_seconds()
    print(f"\n  Folds completed in {elapsed_total:.0f}s")
    print()

    # Run holdout test
    holdout_data = None
    if not args.skip_holdout:
        print(f"--- Running HOLDOUT test: {holdout_start} -> {holdout_end} ---")
        holdout_output = os.path.join(RESULTS_DIR, f"cpcv_{batch_id}_holdout.json")
        _, holdout_data = run_backtest(
            "HOLDOUT",
            args.strategy, args.symbol, args.timeframe,
            holdout_start.isoformat(), holdout_end.isoformat(),
            args.cash, args.commission, holdout_output,
        )
        if holdout_data:
            print(f"    Holdout return: {holdout_data.get('total_return_pct', 0):.2f}%  "
                  f"Sharpe: {holdout_data.get('sharpe_ratio', 0):.2f}  "
                  f"Trades: {holdout_data.get('total_trades', 0)}")
        else:
            print("    HOLDOUT FAILED")
        print()

    # Compute summary
    strategy_name = os.path.splitext(os.path.basename(args.strategy))[0]
    summary = compute_summary(
        batch_id=batch_id,
        folds_results=folds_results,
        holdout_data=holdout_data,
        strategy_name=strategy_name,
        symbol=args.symbol,
        timeframe=args.timeframe,
        train_years=args.train_years,
        test_months=args.test_months,
    )

    # Store summary in DB
    if not args.skip_db:
        print("--- Storing summary in PostgreSQL ---")
        store_summary_pg(summary)
        print()

    # Write JSON output
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  Summary written to: {output_path}")

    # Print formatted summary
    print_summary(summary)

    # Exit code based on verdict
    if summary.get("overfit_flag"):
        sys.exit(2)  # Non-zero but distinct from error (1)
    sys.exit(0)


if __name__ == "__main__":
    main()
