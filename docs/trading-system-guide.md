# Trading System Guide — Options Lifecycle from Scan to Exit

This document explains the complete automated options trading infrastructure: how opportunities are found, how positions are entered, how they're tracked, and when to exit. Every component is deployed via Ansible to the VPS and runs without manual intervention except for trade execution itself.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The Two Strategies](#2-the-two-strategies)
3. [Opportunity Scanning — ivscan-daily.py](#3-opportunity-scanning--ivscan-dailypy)
4. [Position Entry — The /spy-options-trading Skill](#4-position-entry--the-spy-options-trading-skill)
5. [Position Tracking — position-sync.py](#5-position-tracking--position-syncpy)
6. [Exit Signal Rules](#6-exit-signal-rules)
7. [Database Schema](#7-database-schema)
8. [Alerting Pipeline](#8-alerting-pipeline)
9. [Cron Schedule](#9-cron-schedule)
10. [Infrastructure Diagram](#10-infrastructure-diagram)
11. [Grafana Dashboard](#11-grafana-dashboard)
12. [Risk Management Rules](#12-risk-management-rules)
13. [Operational Runbook](#13-operational-runbook)

---

## 1. System Overview

The system implements a **scan → evaluate → enter → track → exit** lifecycle for options trading, focused on S&P 500 stocks. It is entirely **advisory** — no trades are placed automatically. The human decides when to enter and exit; the system provides data, scoring, alerts, and exit signal recommendations.

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY LIFECYCLE                          │
│                                                                 │
│  9:45 AM ET     position-sync.py    ← sync open positions      │
│                     ↓                                           │
│  Market Hours   /spy-options-trading ← human evaluates + trades │
│                     ↓                                           │
│  4:15 PM ET     position-sync.py    ← sync + exit signals      │
│  4:30 PM ET     ivscan-daily.py     ← scan S&P 500 for IV      │
│  5:00 PM ET     daily-market-notify ← Telegram summary         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Component Map

| Component | Type | Purpose |
|-----------|------|---------|
| IBeam | Container | Headless IBKR gateway (handles auth, 2FA) |
| ib-mcp-server | Container | FastAPI wrapper over IBKR Web API (79 endpoints) |
| ivscan-daily.py | Cron script | Daily S&P 500 implied volatility scanner |
| position-sync.py | Cron script | Position lifecycle tracker with exit signals |
| /spy-options-trading | Claude skill | Interactive trading advisor (human-in-the-loop) |
| daily-market-notify | Cron script | Telegram summary of scan results |
| PostgreSQL | Container | Stores scan results + position history |
| Grafana | Container | Visualizes IV trends and position data |
| Telegram Gateway | Container | Delivers alerts to phone |

---

## 2. The Two Strategies

### Strategy 1: Inflection Trading (Directional)

**Concept**: Trade price reactions at key support/resistance levels. Direction-agnostic — buy calls at support, buy puts at resistance.

**When to use**: Any IV regime, but best in NEUTRAL. Requires strong technical levels.

**Entry criteria**:
- Identify support/resistance using 5 methods: Volume Profile, Moving Averages, Fibonacci, Horizontal Structure, Round Numbers
- Score each level 1-10 using the Inflection Scoring Matrix (see below)
- Only trade levels scoring 6+ out of 10
- Wait for confirmation signals (hammer, engulfing, divergence)

**Instruments**: Calls (at support) or Puts (at resistance), delta 0.25-0.40, 21-45 DTE

**Inflection Scoring Matrix (0-10)**:

| Factor | Max Points | What to Check |
|--------|-----------|---------------|
| Level Type Confluence | 3 | How many independent methods identify the level (Volume Profile, MA, Fib, Horizontal, VWAP). 1 point per method, max 3. |
| Volume Confirmation | 2 | HVN within 0.3% of level (+1). Above-average volume on prior test (+1). |
| Multi-Timeframe Alignment | 2 | Level visible on 2 timeframes (+1). Visible on 3+ timeframes (+2). |
| Prior Reaction History | 2 | 1 prior bounce/rejection (+1). 2+ prior clean V-shape reactions (+2). |
| Round Number Proximity | 1 | Within $1 of a $5 or $10 round number (+1). |

**Score interpretation**: 8-10 = PRIME (trade with high conviction), 6-7 = STRONG (trade with confirmation), 4-5 = MODERATE (watch only), 1-3 = WEAK (ignore).

### Strategy 2: IV Cycle Trading (Volatility)

**Concept**: Exploit mean-reversion in implied volatility. When IV is abnormally high, sell premium (it will contract). When IV is abnormally low, buy premium (it will expand).

**When to use**: Depends on IV regime classification:

| Regime | VIX | IV Rank | Action | Structures |
|--------|-----|---------|--------|------------|
| HIGH IV | > 20 | > 50% | Sell premium | Iron condors, credit spreads, naked puts |
| NEUTRAL | 15-20 | 25-50% | Selective directional | Calls/puts at prime inflection levels only |
| LOW IV | < 15 | < 25% | Buy premium | Straddles, debit spreads, calendars |

**Entry criteria**:
- IV Z-Score between 1.75 and 3.0 (absolute value)
- Z-Scores > 3.0 are excluded — likely event-driven (earnings, FDA), not mean-reversion
- Confirmed by IV/HV ratio, IV rank, term structure slope, and options liquidity

**The sweet spot**: Enter at 45 DTE, exit at 21 DTE or 50% profit (whichever comes first).

---

## 3. Opportunity Scanning — ivscan-daily.py

**File**: `roles/monitoring/files/ivscan-daily.py`
**Runs**: Mon-Fri 4:30 PM ET (after market close)
**Output**: Top candidates written to `trading.iv_scan_results` in PostgreSQL

### What It Does (5-Phase Pipeline)

#### Phase 1: Conid Resolution
Resolves all ~500 S&P 500 ticker symbols to IBKR contract IDs (conids). Results are cached to disk at `/var/lib/ivscan/sp500_conids.json` for 30 days to avoid re-resolving on every run.

#### Phase 2: Batch IV Snapshots
Fetches current Implied Volatility, price, and volume for all 500 stocks in batches of 20. Uses the IBKR snapshot 2-call pattern:
1. First call subscribes to market data (returns nothing useful)
2. Wait 2.5 seconds for data to populate
3. Second call retrieves actual values

#### Phase 3: Pre-Filter
Applies coarse filters to reduce the universe:
- **High IV candidates**: IV > 20% AND daily volume > 100K shares
- **Low IV candidates**: IV < 30% AND daily volume > 100K shares
- Stocks can appear in both buckets (20% < IV < 30%)

Typically reduces ~500 stocks to 50-150 candidates.

#### Phase 3.5: Term Structure Analysis
For each pre-filtered candidate, analyzes the option term structure (30 DTE vs 90 DTE):

1. Get option chain expirations for the stock
2. Find the nearest-to-30-DTE and nearest-to-90-DTE expirations
3. Resolve ATM call option conids at each expiration
4. Snapshot IV at both expirations
5. Compute **term slope** = (IV_near - IV_far) / IV_far

**Why this matters**:
- **Backwardation** (slope > 0, near IV > far IV): Near-term fear is elevated. Confirms the sell-premium thesis — elevated IV is temporary and will mean-revert.
- **Contango** (slope < 0, near IV < far IV): Near-term IV is compressed. Confirms the buy-premium thesis — cheap options that will re-expand.

#### Phase 4: Full Metrics
For each remaining candidate, fetches 1 year of daily price bars and computes:

- **HV20**: Rolling 20-day historical volatility (annualized). Computed as: `stdev(20 log-returns) × sqrt(252)`.
- **Z-Score**: `(Current_IV - mean_HV20) / stdev_HV20`. Measures how many standard deviations IV is from normal. Since IBKR doesn't expose historical IV series via Web API, the HV20 distribution serves as a proxy (IV and HV are ~0.7 correlated).
- **IV/HV Ratio**: `Current_IV / latest_HV20`. Values > 1.5 indicate elevated premium.
- **IV Rank**: `(Current_IV - min_HV20) / (max_HV20 - min_HV20) × 100`. Percentile position within the 52-week range.

Candidates are filtered to |Z-Score| between 1.75 and 3.0, then scored.

#### Phase 4 Scoring: IV Scan Matrix (0-12)

| Factor | Max Points | Criteria |
|--------|-----------|----------|
| Z-Score Magnitude | 3 | \|z\| ≥ 1.75 (+1), ≥ 2.0 (+2), ≥ 2.5 (+3) |
| IV/HV Ratio | 2 | High IV: ratio > 1.5 (+1), > 2.0 (+2). Low IV: ratio < 0.7 (+1), < 0.5 (+2) |
| Term Structure | 2 | High IV: backwardation slope > 0.05 (+1), > 0.15 (+2). Low IV: contango slope < -0.02 (+1), < -0.10 (+2) |
| Options Liquidity | 2 | Volume > 1M (+1), > 5M (+2) |
| IV Rank Extreme | 2 | High IV: rank > 90% (+1), > 95% (+2). Low IV: rank < 10% (+1), < 5% (+2) |
| Price Range | 1 | Stock price $50-$500 (optimal for options spreads) |

#### Phase 5: Database Insert
Top 10 high-IV and top 10 low-IV candidates are batch-inserted into `trading.iv_scan_results`.

### Example Log Output
```
S&P 500 IV Z-Score Daily Scan — 2026-02-27 16:30
Pre-filter: 45 high IV (>20%), 62 low IV (<30%)
Term structure: 38/107 candidates analyzed successfully
  NVDA: price=125.30 iv=48.2% hv20=28.1% z=2.41 rank=94% term=+0.12 score=9 -> SELL PREMIUM
  META: price=612.45 iv=35.7% hv20=21.3% z=2.15 rank=91% term=+0.08 score=8 -> SELL PREMIUM
SCAN COMPLETE — 14 candidates persisted in 12.3 minutes
```

---

## 4. Position Entry — The /spy-options-trading Skill

**File**: `.claude/skills/spy-options-trading/SKILL.md`
**Invoked**: Manually via Claude Code (`/spy-options-trading <mode>`)
**Safety**: Advisory-only. ALL orders require explicit CONFIRM input.

### Available Modes

| Command | What It Does |
|---------|-------------|
| `scan` | Weekly inflection map: multi-timeframe analysis + IV environment assessment |
| `alert 585,590,595` | Set IBKR price alerts at inflection levels |
| `analyze 585.50` | Score a specific price level (1-10 inflection scorecard) |
| `trade call` | Plan and execute a trade (with human confirmation gate) |
| `monitor` | Position dashboard with exit signal checks |
| `weekly` | Full Sunday prep: scan + analyze top 5 + monitor + alert setup |
| `ivscan [high\|low\|both]` | Interactive IV scanner (uses same methodology as daily cron) |
| `chart NVDA` | Render IV Z-Score chart from Grafana |

### Trade Execution Flow (Step 5 in the Skill)

```
1. Context Check     — verify IV regime matches strategy
2. Strike Selection  — find options matching criteria (delta, DTE, liquidity)
3. Position Sizing   — calculate contracts: max_risk = NLV × 2%, contracts = floor(max_risk / max_loss)
4. Whatif Preview     — POST /iserver/account/{id}/orders/whatif → shows commission, margin impact
5. ████ STOP ████    — display full trade proposal, wait for "CONFIRM"
6. Order Execution   — POST /iserver/account/{id}/orders → place order
7. Reply Handling    — handle IBKR confirmation chains (replyId flow)
8. Fill Tracking     — monitor order status until filled
```

**Critical safety**: The skill stops at step 5 and will not proceed without explicit human confirmation. IBKR reply chains also require human confirmation. No auto-execution exists anywhere in the system.

### Strike Selection Criteria by Trade Type

| Trade Type | Delta | DTE | Key Criteria |
|-----------|-------|-----|-------------|
| Call/Put (directional) | 0.25-0.40 | 21-45d | Bid-ask < 10% of mid, OI > 1,000 |
| Iron Condor | Short strikes outside expected move | 30-45d | Credit ≥ 1/3 wing width |
| Credit Spread | Short outside expected move | 30-45d | Credit ≥ 1/3 spread width |
| Straddle | ATM | 30-45d | IV Rank < 25% |
| Debit Spread | Long ATM, short 5-10 OTM | 30-45d | Debit < 50% spread width |
| Calendar | Same strike, short 7-14d, long 45d+ | Mixed | IV Rank < 30% |

---

## 5. Position Tracking — position-sync.py

**File**: `roles/monitoring/files/position-sync.py`
**Runs**: Mon-Fri 9:45 AM ET (post-open) and 4:15 PM ET (pre-close)
**Output**: Upserts to `trading.open_positions` + Telegram alerts on exit signals

### What It Does (10-Step Pipeline)

```
Step 1:  check_session()          — verify IBeam is authenticated
Step 2:  ensure_schema()          — CREATE TABLE IF NOT EXISTS (idempotent)
Step 3:  get_account_id()         — GET /portfolio/accounts → first account
Step 4:  fetch_all_positions()    — GET /portfolio/{id}/positions/{page} (paginated)
Step 5:  filter_options()         — keep only assetClass=OPT
Step 6:  fetch_all_greeks()       — batch snapshot fields 7283,7308-7311
Step 7:  build_records()          — compute DTE, PnL%, exit signals
Step 8:  upsert_positions()       — INSERT ... ON CONFLICT DO UPDATE
Step 9:  mark_stale_positions()   — OPEN not in current sync → CLOSED/EXPIRED
Step 10: send_telegram_alerts()   — only if exit signals exist
```

### Position Lifecycle States

```
                    ┌──────────┐
       new sync →   │   OPEN   │  ← re-opened (closed_at = NULL)
                    └────┬─────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     not in sync    not in sync    manually closed
     + expiry past  + expiry future
          │              │              │
          ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ EXPIRED  │   │  CLOSED  │   │  CLOSED  │
    └──────────┘   └──────────┘   └──────────┘
```

- **OPEN**: Position exists in the IBKR portfolio. Updated on every sync.
- **CLOSED**: Position no longer in portfolio and expiry is in the future. `closed_at` timestamp set.
- **EXPIRED**: Position no longer in portfolio and expiry has passed.

### The UPSERT Pattern

Each sync does an INSERT ... ON CONFLICT (account_id, conid) DO UPDATE:

- **Preserved on update**: `opened_at` (original entry time never overwritten)
- **Cleared on re-open**: `closed_at` set to NULL if a previously-closed position reappears
- **Always updated**: `dte`, `market_price`, `unrealized_pnl`, `pnl_pct`, greeks, `exit_signal`, `last_synced`

### Safety: Zero-Position Guard

If the IBKR API returns zero positions (possible during transient failures, session drops, or maintenance), the script skips stale detection entirely. This prevents mass-closing all positions due to an API glitch.

```python
if not current_conids:
    log.warning("Zero positions from API — skipping stale detection (safety)")
    return
```

---

## 6. Exit Signal Rules

The position sync evaluates every open option position against five exit rules. The **highest-priority signal wins** — each position gets at most one signal.

### Signal Hierarchy

| Priority | Signal | Condition | Meaning |
|----------|--------|-----------|---------|
| 1 (emergency) | `GAMMA_RISK` | DTE < 14 AND \|delta\| > 0.50 | Delta is accelerating rapidly. Gamma near expiration makes the position behave like stock — small price moves cause large P&L swings. Close immediately. |
| 2 (action) | `STOP_LOSS` | PnL% ≤ -100% | Total loss has reached the max risk budget. The position has doubled in cost for debit trades, or the credit received has been entirely consumed. Close to prevent further loss. |
| 2 (action) | `DTE_EXIT` | DTE ≤ 21 | The position has entered the theta acceleration zone. Time decay increases exponentially below 21 DTE. If profit target hasn't been hit, close or roll. |
| 2 (action) | `TAKE_PROFIT` | PnL% ≥ 50% | Unrealized profit has reached 50% of the initial cost/credit. Lock in gains — the remaining 50% takes disproportionately longer to capture. |
| 3 (warning) | `APPROACHING_DTE` | 21 < DTE ≤ 28 | Warning that the 21 DTE exit threshold is approaching. Start planning the exit but no immediate action required. |

### Why These Specific Thresholds

**21 DTE exit**: Theta decay follows a curve, not a straight line. The rate of time decay roughly doubles between 30 DTE and 15 DTE. By exiting at 21 DTE, you capture the bulk of premium decay (for sellers) while avoiding the zone where gamma risk escalates and small price moves can wipe out accumulated gains.

```
Theta decay curve (conceptual):

  Theta
  ($/day)
    │
    │                                    ╱
    │                                  ╱
    │                               ╱
    │                            ╱
    │                        ╱
    │                   ╱────  ← 21 DTE exit point
    │             ╱────
    │      ╱──────
    │╱─────
    └──────────────────────────────── DTE
   90    75    60    45    30    21  14   7   0
```

**50% profit target**: Research on options selling strategies consistently shows that taking profits at 50% of max profit produces higher risk-adjusted returns than holding to expiration. The last 50% of profit takes disproportionately more time and gamma risk to capture.

**Gamma risk (DTE < 14, |delta| > 0.50)**: When delta exceeds 0.50, the option is moving nearly 1:1 with the underlying stock. Combined with high gamma near expiration, a 1% move in the stock can swing the option value by 20-30%. This is the "gamma bomb" zone — extremely dangerous for premium sellers.

**Stop loss at -100%**: For credit strategies, losing 100% of the credit means you've given back everything collected plus an equal amount. For debit strategies, it means the option is now worth double what you paid (for short positions) or has lost all its value (for long positions).

### PnL% Calculation

```python
pnl_pct = (unrealized_pnl / abs(avg_cost * quantity)) * 100
```

- For a **short put sold for $3.50**: avg_cost ≈ 3.50, unrealized_pnl = -(current_value - 3.50) × qty
- If current value dropped to $1.75: pnl_pct = +50% → TAKE_PROFIT signal
- If current value rose to $7.00: pnl_pct = -100% → STOP_LOSS signal

---

## 7. Database Schema

Both tables live in the `trading` schema in the `enterprise` PostgreSQL database.

### trading.iv_scan_results

Populated by `ivscan-daily.py` after market close. Each row is one candidate from one scan.

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | Auto-increment |
| scan_time | TIMESTAMP | When the scan ran (default NOW()) |
| ticker | VARCHAR(10) | Stock symbol |
| conid | INTEGER | IBKR contract ID |
| price | NUMERIC(10,2) | Stock price at scan time |
| iv | NUMERIC(6,4) | Current implied volatility (decimal, e.g., 0.4820 = 48.2%) |
| hv20 | NUMERIC(6,4) | Latest 20-day historical volatility |
| iv_hv_ratio | NUMERIC(6,3) | IV / HV20 ratio |
| z_score | NUMERIC(6,3) | IV Z-Score (how many SDs from mean HV20) |
| iv_rank | NUMERIC(5,2) | IV percentile rank (0-100%) |
| monthly_ranks | JSONB | Per-month IV rank breakdown |
| score | INTEGER | Composite score (0-12) |
| signal | VARCHAR(20) | "SELL PREMIUM" or "BUY PREMIUM" |
| scan_direction | VARCHAR(10) | "high" or "low" |
| iv_30d | NUMERIC(6,4) | IV at ~30 DTE expiration |
| iv_90d | NUMERIC(6,4) | IV at ~90 DTE expiration |
| term_slope | NUMERIC(6,3) | (IV_30d - IV_90d) / IV_90d |
| target_dte | INTEGER | Ideal entry DTE |

**Indexes**: ticker, scan_time

### trading.open_positions

Populated by `position-sync.py` twice daily. Each row tracks one option contract position across its lifecycle.

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | Auto-increment |
| account_id | VARCHAR(20) | IBKR account (e.g., "U21534519") |
| conid | INTEGER | IBKR contract ID for the option |
| ticker | VARCHAR(10) | Underlying stock symbol |
| underlying_conid | INTEGER | Conid of the underlying stock |
| put_call | VARCHAR(1) | "C" or "P" |
| strike | NUMERIC(10,2) | Strike price |
| expiry | DATE | Option expiration date |
| dte | INTEGER | Days to expiration (computed each sync) |
| quantity | INTEGER | Number of contracts (negative = short) |
| avg_cost | NUMERIC(12,4) | Average cost per contract |
| market_price | NUMERIC(12,4) | Current market price |
| market_value | NUMERIC(12,2) | Total market value |
| unrealized_pnl | NUMERIC(12,2) | Unrealized profit/loss |
| pnl_pct | NUMERIC(8,2) | P&L as percentage of cost |
| iv | NUMERIC(8,4) | Current implied volatility |
| delta | NUMERIC(8,4) | Option delta |
| gamma | NUMERIC(8,6) | Option gamma |
| theta | NUMERIC(8,4) | Option theta |
| vega | NUMERIC(8,4) | Option vega |
| exit_signal | VARCHAR(20) | Active exit signal (or NULL) |
| exit_priority | INTEGER | Signal priority (1=emergency, 2=action, 3=warning) |
| status | VARCHAR(10) | OPEN, CLOSED, or EXPIRED |
| opened_at | TIMESTAMP | First time position appeared (preserved across updates) |
| last_synced | TIMESTAMP | Last successful sync |
| closed_at | TIMESTAMP | When position was closed/expired (NULL if open) |

**Unique constraint**: `(account_id, conid)` — enables the UPSERT pattern
**Indexes**: status, exit_signal (partial, WHERE NOT NULL)

---

## 8. Alerting Pipeline

### How Alerts Flow

```
position-sync.py
      │
      │  exit signals detected?
      │
      ├── NO  → log "no exit signals" → done (no Telegram spam)
      │
      └── YES → format HTML message
                    │
                    ▼
           /usr/local/bin/telegram-notify "<msg>" "HTML"
                    │
                    ▼
           curl → Telegram Gateway → Telegram Bot API → Phone
```

### Alert Message Format

Signals are grouped by priority with visual urgency headers:

```
Position Alert  2026-02-27 16:15 ET

[URGENT]
  TSLA   -2 450C 11d PnL:-45.2% d:0.62 GAMMA_RISK

[ACTION]
  SPY    -5 580P 19d PnL:+52.3% d:-0.22 TAKE_PROFIT
  AAPL   -3 230C 20d PnL:+15.7% d:0.35 DTE_EXIT

[WATCH]
  AMZN   -2 210C 25d PnL:+32.1% d:0.28 APPROACHING_DTE
```

### When Alerts Are NOT Sent

- Clean syncs with no exit signals (prevents daily notification fatigue)
- When `telegram-notify` is not installed (logged as warning, script continues)
- When the Telegram Gateway is unreachable (timeout, logged as warning)
- On weekends (cron doesn't run)

### Daily Market Summary (separate from position alerts)

The `daily-market-notify` script (5:00 PM ET) queries the day's IV scan results from PostgreSQL and sends a formatted table:

```
Daily IV Scanner Report

Date: 2026-02-27
Stocks flagged: 14

Ticker  | Score | Signal     | IV     | Z-Score | IV Rank
--------|-------|------------|--------|---------|--------
NVDA    |     9 | SELL PREM  | 0.4820 |   2.41  | 94.00
META    |     8 | SELL PREM  | 0.3570 |   2.15  | 91.00
...
```

---

## 9. Cron Schedule

All cron jobs run under `CRON_TZ=America/New_York` (DST-safe). Managed by Ansible in `roles/monitoring/tasks/main.yml`.

| Time (ET) | Days | Job | Purpose |
|-----------|------|-----|---------|
| 7:00 AM | Daily | daily-services-check | Infrastructure health: pods, ports, disk, SSL, tunnel |
| 7:30 AM | Daily | daily-security-check | Security: Trivy, fail2ban, firewall, SSH, updates |
| 9:45 AM | Mon-Fri | position-sync.py | Sync positions after market open, detect overnight signals |
| 4:15 PM | Mon-Fri | position-sync.py | Sync positions before close, final exit signal check |
| 4:30 PM | Mon-Fri | ivscan-daily.py | Scan S&P 500 for IV opportunities (uses closing data) |
| 5:00 PM | Mon-Fri | daily-market-notify | Send IV scan summary to Telegram |

### Why These Times

- **9:45 AM** (not 9:30): Avoids the opening auction chaos. Prices stabilize ~15 minutes after open.
- **4:15 PM** (not 4:00): Options markets close at 4:00 but final prints arrive by 4:15. This captures accurate closing greeks and PnL.
- **4:30 PM**: IV scan needs market-close data. Running after 4:15 ensures all snapshots reflect closing prices.
- **5:00 PM**: Market notify runs 30 minutes after the IV scan to ensure results are in the database.

---

## 10. Infrastructure Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  VPS (Alpine Linux)                                                     │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │  Podman Network: enterprise_network (REDACTED_CIDR)             │     │
│  │                                                                 │     │
│  │  ┌──────────────────┐    ┌──────────────────────────────────┐  │     │
│  │  │  IBeam Container  │    │  shared-db-pod                   │  │     │
│  │  │  (voyz/ibeam)     │    │  ┌───────────┐                    │  │     │
│  │  │  :5055 → :5000    │    │  │ PostgreSQL │                   │  │     │
│  │  │  IBKR Gateway     │    │  │  :5432     │                   │  │     │
│  │  └────────┬──────────┘    │  └─────┬─────┘                    │  │     │
│  │           │                │        │                          │  │     │
│  │  ┌────────▼──────────┐    │        │  trading.iv_scan_results │  │     │
│  │  │ ib-mcp-server     │    │        │  trading.open_positions  │  │     │
│  │  │  :5002             │    │        │                          │  │     │
│  │  │  FastAPI + FastMCP │    └────────┼──────────────────────────┘  │     │
│  │  │  79 REST endpoints │             │                            │     │
│  │  └────────────────────┘             │                            │     │
│  │                                     │                            │     │
│  │  ┌──────────────────────────────────┼─────────────────────────┐  │     │
│  │  │  metrics-pod                     │                         │  │     │
│  │  │  ┌──────────┐  ┌──────────┐     │    ┌─────────────────┐  │  │     │
│  │  │  │ Grafana  │  │Prometheus│     │    │ Image Renderer  │  │  │     │
│  │  │  │  :3000   │  │  :9090   │     │    │     :8081       │  │  │     │
│  │  │  └──────────┘  └──────────┘     │    └─────────────────┘  │  │     │
│  │  └─────────────────────────────────┘                          │  │     │
│  └───────────────────────────────────────────────────────────────┘  │     │
│                                                                      │     │
│  ┌──────────────────────────────────┐                                │     │
│  │  Cron Jobs (Python/Shell)        │                                │     │
│  │                                  │                                │     │
│  │  ivscan-daily.py ──────────┬─────┼── IBKR API (via IBeam :5055)  │     │
│  │  position-sync.py ─────────┤     │                                │     │
│  │  daily-market-notify ──────┤     ├── PostgreSQL (via podman exec) │     │
│  │                            │     │                                │     │
│  │                            └─────┼── telegram-notify              │     │
│  └──────────────────────────────────┘         │                      │     │
│                                               ▼                      │     │
│  ┌──────────────────────────────────┐                                │     │
│  │  Telegram Gateway Container      │                                │     │
│  │  Bot API → Telegram → Phone      │                                │     │
│  └──────────────────────────────────┘                                │     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Grafana Dashboard

Dashboard UID: `trading-iv`

The Trading IV dashboard visualizes IV scan history. It reads from `trading.iv_scan_results` and includes:

- **Z-Score time series by ticker** — Track how IV evolves over multiple scans
- **Score distribution** — Histogram of scan scores over time
- **Top candidates table** — Current day's ranked results
- **Term structure slope** — Backwardation/contango trends

The Grafana Image Renderer can snapshot any panel for Telegram delivery:
```bash
curl -u "admin:PASSWORD" \
  "http://127.0.0.1:3000/render/d-solo/trading-iv/trading-iv-scanner?panelId=3&var-ticker=NVDA&from=now-90d&to=now&width=1200&height=600&theme=dark" \
  -o /tmp/chart.png
```

---

## 12. Risk Management Rules

### Position Sizing

| Rule | Value | Rationale |
|------|-------|-----------|
| Max risk per trade | 2% of NLV | Ensures no single trade can materially impact the account |
| Max concurrent positions | 5 (across all tickers) | Limits total portfolio exposure |
| Min inflection score | 6/10 | Only trade well-confirmed levels |
| Min IV Z-Score | 1.75 | Statistical significance threshold (~96th percentile) |
| Max IV Z-Score | 3.0 | Outliers likely event-driven, not mean-reversion |

### Position Sizing Formula

```
max_risk_dollars = NLV × 0.02

# For credit strategies (iron condor, credit spread):
max_loss_per_contract = (wing_width - credit_received) × 100
contracts = floor(max_risk_dollars / max_loss_per_contract)

# For debit strategies (call, put, debit spread):
max_loss_per_contract = debit_paid × 100
contracts = floor(max_risk_dollars / max_loss_per_contract)
```

### Expected Move Calculation

Used for strike placement in credit strategies:

```
Expected Move = Price × IV × sqrt(DTE / 365)
```

Short strikes should be placed outside the expected move boundary. Example:
- SPY at $590, IV 15%, 30 DTE
- Expected Move = 590 × 0.15 × sqrt(30/365) = $25.37
- 1 SD range: $564.63 to $615.37
- Short call: above $615, Short put: below $565

### Rolling Rules

When DTE < 21 and profit < 50%:
1. Close current position
2. Open same structure in next monthly expiry
3. Must receive a net credit on the roll (roll for credit, not debit)
4. If can't roll for credit, close outright instead

---

## 13. Operational Runbook

### Manual Position Sync

```bash
ssh root@REDACTED_IP "python3 /usr/local/bin/position-sync.py"
```

### Check Open Positions

```bash
ssh root@REDACTED_IP 'podman exec postgres psql -U postgres -d enterprise -c \
  "SELECT ticker, put_call, strike, dte, pnl_pct, exit_signal, status
   FROM trading.open_positions
   WHERE status='\''OPEN'\''
   ORDER BY exit_priority DESC NULLS LAST, dte ASC"'
```

### Check Today's IV Scan Results

```bash
ssh root@REDACTED_IP 'podman exec postgres psql -U postgres -d enterprise -c \
  "SELECT ticker, score, signal, z_score, iv_rank, term_slope
   FROM trading.iv_scan_results
   WHERE scan_time::date = CURRENT_DATE
   ORDER BY score DESC"'
```

### View Position History

```bash
# All closed positions with their P&L
podman exec postgres psql -U postgres -d enterprise -c \
  "SELECT ticker, put_call, strike, pnl_pct, status, opened_at, closed_at
   FROM trading.open_positions
   WHERE status IN ('CLOSED','EXPIRED')
   ORDER BY closed_at DESC LIMIT 20"
```

### IBeam Session Issues

```bash
# Check IBeam status
podman logs ibeam --tail 20

# Restart IBeam (triggers re-auth, needs IB Key approval on phone)
podman restart ibeam

# Verify session
curl -sk https://127.0.0.1:5055/v1/api/tickle | python3 -m json.tool
```

### Deploy Changes

```bash
# From the VPS, via ansible-deployment container:
podman exec -w /ansible ansible-deployment ansible-playbook \
  -i inventory/hosts site.yml \
  --tags "trading-schema,position-sync,cron-jobs"
```

### Clear Stale Session Data

If position sync is producing incorrect data due to a stale IBeam session:
```bash
podman restart ibeam
# Wait for IB Key approval on phone, then:
python3 /usr/local/bin/position-sync.py
```

### Check Cron Jobs

```bash
crontab -l | grep -E 'position-sync|ivscan|market-notify'
```

### View Logs

```bash
tail -50 /var/log/position-sync.log
tail -50 /var/log/ivscan.log
tail -50 /var/log/daily-market-notify.log
```
