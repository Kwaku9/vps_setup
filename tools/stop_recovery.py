#!/usr/bin/env python3
"""Analyze how often stopped-out trades would have recovered to target."""
import json
from datetime import datetime, timezone
from bisect import bisect_left

with open('/opt/compose/backtrader-results/spy_4h_2021.json') as f:
    bars = json.load(f)

with open('/opt/compose/backtrader-results/v2b_long60_4h_2017_21k.json') as f:
    trades = json.load(f)['trades']

ts_list = [b['time'] for b in bars]
high_list = [b['high'] for b in bars]

stops = [t for t in trades if t['entry_date'] >= '2021' and t['bars_held'] < 60 and t['pnl'] < 0]
print(f'Stops 2021-2026: {len(stops)}')

recovery = []
for t in stops:
    dt = datetime.strptime(t['exit_date'][:19], '%Y-%m-%dT%H:%M:%S')
    exit_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
    idx = bisect_left(ts_list, exit_ts)
    if idx >= len(ts_list):
        continue

    entry = t['entry_price']
    stop_price = t['exit_price']
    risk = entry - stop_price
    # Many stops exit at breakeven (trail to BE after 1R) — use PnL/size as risk proxy
    if risk <= 0:
        # Estimate risk from PnL: loss = risk_per_share * size, size ~ equity*0.02/risk
        # Simpler: use average stop distance from actual losers (~2% of entry from ATR stop)
        risk = entry * 0.02  # ATR stop is roughly 2% for SPY 4h
    target = entry + risk * 2.5

    def max_high(n):
        end = min(idx + n, len(high_list))
        return max(high_list[idx:end]) if idx < end else 0

    recovery.append({
        'date': t['entry_date'][:10],
        'pnl': t['pnl'],
        'entry': entry,
        'stop': stop_price,
        'target': round(target, 2),
        'max20': max_high(20),
        'max40': max_high(40),
        'max60': max_high(60),
    })

total = len(recovery)
print(f'Analyzed: {total}\n')

for label, key in [('20 bars (~5 trading days)', 'max20'),
                    ('40 bars (~10 trading days)', 'max40'),
                    ('60 bars (~15 trading days)', 'max60')]:
    hit_tgt = [r for r in recovery if r[key] >= r['target']]
    hit_be = [r for r in recovery if r[key] >= r['entry']]
    stayed = [r for r in recovery if r[key] < r['entry']]

    print(f'Within {label} AFTER being stopped out:')
    print(f'  Price returned to entry: {len(hit_be):>3}/{total} ({len(hit_be)/total*100:.0f}%)')
    print(f'  Price reached target:    {len(hit_tgt):>3}/{total} ({len(hit_tgt)/total*100:.0f}%)')
    print(f'  Price stayed below entry:{len(stayed):>3}/{total} ({len(stayed)/total*100:.0f}%)')
    if hit_tgt:
        lost = sum(r['pnl'] for r in hit_tgt)
        print(f'  PnL lost on recovered:   ${lost:+.2f}')
    print()

print('=' * 70)
print('STOPS WHERE PRICE HIT TARGET WITHIN 60 BARS')
print('=' * 70)
hit60 = sorted([r for r in recovery if r['max60'] >= r['target']], key=lambda x: x['pnl'])
for r in hit60:
    print(f"  {r['date']}  PnL: {r['pnl']:>+7.2f}  Entry: {r['entry']:>7.2f}  Stop: {r['stop']:>7.2f}  Target: {r['target']:>7.2f}  MaxAfter: {r['max60']:>7.2f}")
print(f"  --- Total lost on these {len(hit60)} trades: ${sum(r['pnl'] for r in hit60):+.2f}")

print()
print('=' * 70)
print('STOPS WHERE PRICE NEVER RETURNED TO ENTRY (correct stops)')
print('=' * 70)
never = sorted([r for r in recovery if r['max60'] < r['entry']], key=lambda x: x['pnl'])
for r in never:
    print(f"  {r['date']}  PnL: {r['pnl']:>+7.2f}  Entry: {r['entry']:>7.2f}  Stop: {r['stop']:>7.2f}  BestAfter: {r['max60']:>7.2f}")
print(f"  --- These {len(never)} stops were correct")

print()
print('=' * 70)
print('RETURNED TO ENTRY BUT NOT TARGET (partial recovery)')
print('=' * 70)
partial = sorted([r for r in recovery if r['max60'] >= r['entry'] and r['max60'] < r['target']], key=lambda x: x['pnl'])
for r in partial:
    print(f"  {r['date']}  PnL: {r['pnl']:>+7.2f}  Entry: {r['entry']:>7.2f}  Target: {r['target']:>7.2f}  MaxAfter: {r['max60']:>7.2f}")
print(f"  --- {len(partial)} trades returned to entry but not target")

# Summary
print()
print('=' * 70)
print('SUMMARY')
print('=' * 70)
correct = len([r for r in recovery if r['max60'] < r['entry']])
wrong_full = len([r for r in recovery if r['max60'] >= r['target']])
wrong_partial = len([r for r in recovery if r['max60'] >= r['entry'] and r['max60'] < r['target']])
print(f"  Correct stops (never recovered):  {correct}/{total} ({correct/total*100:.0f}%)")
print(f"  Wrong stops (hit target after):   {wrong_full}/{total} ({wrong_full/total*100:.0f}%)")
print(f"  Partial (returned to entry only): {wrong_partial}/{total} ({wrong_partial/total*100:.0f}%)")
print(f"  PnL lost on wrong stops:          ${sum(r['pnl'] for r in recovery if r['max60'] >= r['target']):+.2f}")
print(f"  PnL saved on correct stops:       ${sum(r['pnl'] for r in recovery if r['max60'] < r['entry']):+.2f}")
