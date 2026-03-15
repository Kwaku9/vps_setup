#!/usr/bin/env python3
"""Simulate DCA on stopped trades using actual OHLC data after stop.

Regime filter: skip DCA when price is below SMA(50) at stop time (bear regime).
"""
import json
from datetime import datetime, timezone
from bisect import bisect_left

SMA_PERIOD = 200  # Regime filter — SMA(200) true trend filter for bear markets

with open('/opt/compose/backtrader-results/spy_4h_2021.json') as f:
    bars = json.load(f)

with open('/opt/compose/backtrader-results/v2b_rr2_0_4h.json') as f:
    d = json.load(f)

ts_list = [b['time'] for b in bars]
bar_data = {b['time']: b for b in bars}
close_list = [b['close'] for b in bars]

trades = d['trades']
stops = [t for t in trades if t['entry_date'] >= '2021' and t['bars_held'] < 60 and t['pnl'] < 0]
winners = [t for t in trades if t['entry_date'] >= '2021' and t['pnl'] > 0]

print(f"Strategy: V2B-Long-60 R:R=2.0, 2021-2026")
print(f"Total trades: {len([t for t in trades if t['entry_date'] >= '2021'])}")
print(f"Winners: {len(winners)}, Stops: {len(stops)}")
print(f"Current stop PnL: {sum(t['pnl'] for t in stops):+.2f}")
print()


def sma_at(idx):
    """Compute SMA(50) of close prices ending at bar index idx."""
    if idx < SMA_PERIOD - 1:
        return None
    return sum(close_list[idx - SMA_PERIOD + 1:idx + 1]) / SMA_PERIOD


# Simulate DCA: when stopped, buy same size again at stop price
# Then exit at breakeven (avg cost) + small buffer
# Hard stop at 3x original risk below entry (bail-out)
# REGIME FILTER: skip DCA if price < SMA(50) at stop bar (bear regime)

dca_results = []
skipped_bear = []
for t in stops:
    dt = datetime.strptime(t['exit_date'][:19], '%Y-%m-%dT%H:%M:%S')
    exit_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
    idx = bisect_left(ts_list, exit_ts)
    if idx >= len(ts_list) - 60:
        continue

    # Regime filter: check SMA(50) at stop bar
    sma_val = sma_at(idx)
    stop_price = close_list[idx] if idx < len(close_list) else t['exit_price']
    if sma_val is not None and stop_price < sma_val:
        skipped_bear.append({
            'date': t['entry_date'][:10],
            'orig_pnl': t['pnl'],
            'price': round(stop_price, 2),
            'sma50': round(sma_val, 2),
        })
        continue

    entry1 = t['entry_price']
    stop1 = t['exit_price']
    size = t.get('size', 1)
    risk = entry1 - stop1
    if risk <= 0:
        risk = entry1 * 0.02  # estimate for BE stops

    # DCA entry: buy again at the stop price
    entry2 = stop1 if stop1 < entry1 else entry1 - risk
    avg_cost = (entry1 + entry2) / 2

    # Breakeven target: avg cost + small buffer (cover commission)
    be_target = avg_cost + (entry1 * 0.001)  # 0.1% above avg cost

    # Hard bail-out stop: 2x original risk below original entry
    hard_stop = entry1 - (risk * 2.5)

    # Walk forward through bars
    outcome = 'timeout'
    exit_price = 0
    bars_after = 0

    for j in range(idx + 1, min(idx + 61, len(ts_list))):
        bar = bar_data[ts_list[j]]
        bars_after += 1

        # Check hard stop first
        if bar['low'] <= hard_stop:
            outcome = 'hard_stop'
            exit_price = hard_stop
            break

        # Check breakeven target
        if bar['high'] >= be_target:
            outcome = 'breakeven'
            exit_price = be_target
            break

    if outcome == 'timeout':
        # Exit at last bar's close
        exit_price = bar_data[ts_list[min(idx + 60, len(ts_list) - 1)]]['close']

    # PnL calculation for the DCA'd position (2 lots)
    # Lot 1: entry1, Lot 2: entry2, both exit at exit_price
    pnl_lot1 = (exit_price - entry1) * size
    pnl_lot2 = (exit_price - entry2) * size
    total_pnl = pnl_lot1 + pnl_lot2
    commission = size * 0.65 * 2  # extra round trip for DCA lot
    net_pnl = total_pnl - commission

    # Original loss
    orig_pnl = t['pnl']

    dca_results.append({
        'date': t['entry_date'][:10],
        'orig_pnl': orig_pnl,
        'dca_pnl': net_pnl,
        'improvement': net_pnl - orig_pnl,
        'outcome': outcome,
        'bars_after': bars_after,
        'entry1': entry1,
        'entry2': round(entry2, 2),
        'avg_cost': round(avg_cost, 2),
        'exit_price': round(exit_price, 2),
    })

total = len(dca_results)
print(f"=== DCA SIMULATION ({total} stopped trades) ===")
print()

# Outcomes
be_trades = [r for r in dca_results if r['outcome'] == 'breakeven']
hs_trades = [r for r in dca_results if r['outcome'] == 'hard_stop']
to_trades = [r for r in dca_results if r['outcome'] == 'timeout']

print(f"Outcomes:")
print(f"  Hit breakeven:  {len(be_trades):>3}/{total} ({len(be_trades)/total*100:.0f}%)")
print(f"  Hard stopped:   {len(hs_trades):>3}/{total} ({len(hs_trades)/total*100:.0f}%)")
print(f"  Timed out:      {len(to_trades):>3}/{total} ({len(to_trades)/total*100:.0f}%)")
print()

# PnL comparison
orig_total = sum(r['orig_pnl'] for r in dca_results)
dca_total = sum(r['dca_pnl'] for r in dca_results)
print(f"PnL comparison (stopped trades only):")
print(f"  Original (just stop):  ${orig_total:+,.2f}")
print(f"  With DCA:              ${dca_total:+,.2f}")
print(f"  Improvement:           ${dca_total - orig_total:+,.2f}")
print()

# Breakdown by outcome
for label, group in [('Breakeven exits', be_trades), ('Hard stops', hs_trades), ('Timeouts', to_trades)]:
    if not group:
        continue
    orig = sum(r['orig_pnl'] for r in group)
    dca = sum(r['dca_pnl'] for r in group)
    avg_bars = sum(r['bars_after'] for r in group) / len(group)
    print(f"  {label} ({len(group)}):")
    print(f"    Original PnL: ${orig:+,.2f}")
    print(f"    DCA PnL:      ${dca:+,.2f}")
    print(f"    Avg bars to exit: {avg_bars:.1f}")
    print()

# Skipped bear regime trades
bear_pnl = sum(s['orig_pnl'] for s in skipped_bear)
print(f"REGIME FILTER: Skipped {len(skipped_bear)} stops in bear regime (price < SMA50)")
print(f"  Bear-regime stop PnL (untouched): ${bear_pnl:+,.2f}")
if skipped_bear:
    print(f"  {'Date':>10} {'Orig PnL':>10} {'Price':>8} {'SMA50':>8}")
    for s in skipped_bear:
        print(f"  {s['date']:>10} {s['orig_pnl']:>+10.2f} {s['price']:>8.2f} {s['sma50']:>8.2f}")
print()

# Net strategy impact
print("=" * 60)
print("FULL STRATEGY IMPACT (all trades)")
print("=" * 60)
winner_pnl = sum(t['pnl'] for t in winners)
orig_stop_total = sum(t['pnl'] for t in stops if t['entry_date'] >= '2021')
orig_strategy = winner_pnl + orig_stop_total
dca_strategy = winner_pnl + dca_total + bear_pnl  # DCA'd trades + untouched bear stops
print(f"  Winner PnL (unchanged):       ${winner_pnl:+,.2f}")
print(f"  Original all-stop PnL:        ${orig_stop_total:+,.2f}")
print(f"  DCA stop PnL (bull regime):   ${dca_total:+,.2f}")
print(f"  Bear stops (no DCA):          ${bear_pnl:+,.2f}")
print(f"  ---")
print(f"  Original total:               ${orig_strategy:+,.2f}")
print(f"  With regime-filtered DCA:     ${dca_strategy:+,.2f}")
print(f"  Net improvement:              ${dca_strategy - orig_strategy:+,.2f}")
print()

# Show DCA'd trade details
print("DCA TRADE DETAILS (bull regime only):")
print(f"  {'Date':>10} {'Orig':>8} {'DCA':>8} {'Delta':>8} {'Outcome':>10} {'Bars':>5}")
for r in sorted(dca_results, key=lambda x: x['improvement'], reverse=True):
    print(f"  {r['date']:>10} {r['orig_pnl']:>+8.2f} {r['dca_pnl']:>+8.2f} {r['improvement']:>+8.2f} {r['outcome']:>10} {r['bars_after']:>5}")
