#!/usr/bin/env python3
"""Generate DCA backtest chart HTML with embedded data.

Runs the regime-filtered DCA simulation and produces a self-contained
Lightweight Charts HTML page for portal.REDACTED_DOMAIN/dca-backtest.html
"""
import json
import math
from datetime import datetime, timezone
from bisect import bisect_left

SMA_PERIOD = 200  # Regime filter — SMA(200) true trend filter

# ── Load data ────────────────────────────────────────────────────────
with open('/opt/compose/backtrader-results/spy_4h_2021.json') as f:
    bars = json.load(f)

with open('/opt/compose/backtrader-results/v2b_rr2_0_4h.json') as f:
    d = json.load(f)

ts_list = [b['time'] for b in bars]
bar_data = {b['time']: b for b in bars}
close_list = [b['close'] for b in bars]

trades = d['trades']
equity_curve = d.get('equity_curve', [])
initial_cash = d.get('initial_cash', 27717.56)
all_trades_2021 = [t for t in trades if t['entry_date'] >= '2021']
stops = [t for t in all_trades_2021 if t['bars_held'] < 60 and t['pnl'] < 0]
winners = [t for t in all_trades_2021 if t['pnl'] > 0]


def sma_at(idx):
    if idx < SMA_PERIOD - 1:
        return None
    return sum(close_list[idx - SMA_PERIOD + 1:idx + 1]) / SMA_PERIOD


def parse_ts(datestr):
    dt = datetime.strptime(datestr[:19], '%Y-%m-%dT%H:%M:%S')
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


# ── Compute SMA(200) line for chart ──────────────────────────────────
sma_line = []
for i, b in enumerate(bars):
    val = sma_at(i)
    if val is not None:
        sma_line.append({'time': b['time'], 'value': round(val, 2)})

# ── Run DCA simulation ───────────────────────────────────────────────
dca_results = []
skipped_bear = []

for t in stops:
    dt = datetime.strptime(t['exit_date'][:19], '%Y-%m-%dT%H:%M:%S')
    exit_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
    idx = bisect_left(ts_list, exit_ts)
    if idx >= len(ts_list) - 60:
        continue

    sma_val = sma_at(idx)
    stop_price = close_list[idx] if idx < len(close_list) else t['exit_price']

    entry1 = t['entry_price']
    stop1 = t['exit_price']
    size = t.get('size', 1)
    risk = entry1 - stop1
    if risk <= 0:
        risk = entry1 * 0.02

    if sma_val is not None and stop_price < sma_val:
        skipped_bear.append({
            'date': t['entry_date'][:10],
            'entry_date': t['entry_date'],
            'exit_date': t['exit_date'],
            'orig_pnl': t['pnl'],
            'entry_price': entry1,
            'exit_price': stop1,
            'sma200': round(sma_val, 2),
            'regime': 'bear',
        })
        continue

    entry2 = stop1 if stop1 < entry1 else entry1 - risk
    avg_cost = (entry1 + entry2) / 2
    be_target = avg_cost + (entry1 * 0.001)
    hard_stop = entry1 - (risk * 2.5)

    outcome = 'timeout'
    exit_price = 0
    bars_after = 0
    dca_exit_ts = exit_ts

    for j in range(idx + 1, min(idx + 61, len(ts_list))):
        bar = bar_data[ts_list[j]]
        bars_after += 1
        if bar['low'] <= hard_stop:
            outcome = 'hard_stop'
            exit_price = hard_stop
            dca_exit_ts = ts_list[j]
            break
        if bar['high'] >= be_target:
            outcome = 'breakeven'
            exit_price = be_target
            dca_exit_ts = ts_list[j]
            break

    if outcome == 'timeout':
        last_idx = min(idx + 60, len(ts_list) - 1)
        exit_price = bar_data[ts_list[last_idx]]['close']
        dca_exit_ts = ts_list[last_idx]

    pnl_lot1 = (exit_price - entry1) * size
    pnl_lot2 = (exit_price - entry2) * size
    total_pnl = pnl_lot1 + pnl_lot2
    commission = size * 0.65 * 2
    net_pnl = total_pnl - commission

    dca_results.append({
        'orig_entry_date': t['entry_date'],
        'orig_exit_date': t['exit_date'],
        'dca_entry_ts': exit_ts,
        'dca_exit_ts': dca_exit_ts,
        'entry1': entry1,
        'entry2': round(entry2, 2),
        'avg_cost': round(avg_cost, 2),
        'exit_price': round(exit_price, 2),
        'be_target': round(be_target, 2),
        'hard_stop': round(hard_stop, 2),
        'orig_pnl': t['pnl'],
        'dca_pnl': round(net_pnl, 2),
        'improvement': round(net_pnl - t['pnl'], 2),
        'outcome': outcome,
        'bars_after': bars_after,
        'regime': 'bull',
    })

# ── Build equity curves ──────────────────────────────────────────────
# Sort all events chronologically to build cumulative equity
all_events_orig = []
all_events_dca = []

for t in all_trades_2021:
    ts = parse_ts(t['exit_date'])
    all_events_orig.append((ts, t['pnl']))
    # For DCA curve: same as original for winners
    if t['pnl'] > 0 or t['bars_held'] >= 60:
        all_events_dca.append((ts, t['pnl']))

# Add DCA results for stopped trades (replace original stop loss)
for r in dca_results:
    all_events_dca.append((r['dca_exit_ts'], r['dca_pnl']))

# Add bear-skipped stops unchanged
for s in skipped_bear:
    ts = parse_ts(s['exit_date'])
    all_events_dca.append((ts, s['orig_pnl']))

all_events_orig.sort(key=lambda x: x[0])
all_events_dca.sort(key=lambda x: x[0])

equity_orig = []
equity_dca = []
cum_orig = initial_cash
cum_dca = initial_cash

for ts, pnl in all_events_orig:
    cum_orig += pnl
    equity_orig.append({'time': ts, 'value': round(cum_orig, 2)})

for ts, pnl in all_events_dca:
    cum_dca += pnl
    equity_dca.append({'time': ts, 'value': round(cum_dca, 2)})

# ── Compute stats ────────────────────────────────────────────────────
def compute_stats(label, trade_pnls, initial):
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p <= 0]
    total_pnl = sum(trade_pnls)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses)) / len(losses) if losses else 0

    # Max drawdown from equity
    peak = initial
    max_dd = 0
    eq = initial
    for p in trade_pnls:
        eq += p
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd = max(max_dd, dd)

    return {
        'label': label,
        'trades': len(trade_pnls),
        'winners': len(wins),
        'losers': len(losses),
        'win_rate': round(len(wins) / len(trade_pnls) * 100, 1) if trade_pnls else 0,
        'total_pnl': round(total_pnl, 2),
        'return_pct': round(total_pnl / initial * 100, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(gross_win / gross_loss, 2) if gross_loss > 0 else 999,
        'max_drawdown': round(max_dd, 2),
        'rr_ratio': round(avg_win / avg_loss, 2) if avg_loss > 0 else 999,
    }

orig_pnls = sorted([(parse_ts(t['exit_date']), t['pnl']) for t in all_trades_2021], key=lambda x: x[0])
orig_stats = compute_stats('Original V2B-Long-60', [p for _, p in orig_pnls], initial_cash)

# DCA strategy PnLs: winners unchanged, stopped trades replaced
dca_pnl_list = []
for t in all_trades_2021:
    if t['pnl'] > 0 or t['bars_held'] >= 60:
        dca_pnl_list.append(t['pnl'])
for r in dca_results:
    dca_pnl_list.append(r['dca_pnl'])
for s in skipped_bear:
    dca_pnl_list.append(s['orig_pnl'])

dca_stats = compute_stats('DCA + SMA(200) Filter', dca_pnl_list, initial_cash)

# ── Build chart trade markers ────────────────────────────────────────
# Original trades markers
orig_markers = []
for t in all_trades_2021:
    entry_ts = parse_ts(t['entry_date'])
    exit_ts = parse_ts(t['exit_date'])
    is_stop = t['pnl'] < 0 and t['bars_held'] < 60
    is_win = t['pnl'] > 0

    orig_markers.append({
        'time': entry_ts,
        'position': 'belowBar',
        'color': '#3b82f6',
        'shape': 'arrowUp',
        'text': '',
    })

    if is_stop:
        exit_color = '#ef4444'
    elif is_win:
        exit_color = '#22c55e'
    else:
        exit_color = '#f59e0b'

    orig_markers.append({
        'time': exit_ts,
        'position': 'aboveBar',
        'color': exit_color,
        'shape': 'arrowDown',
        'text': 'S' if is_stop else ('T' if t['bars_held'] >= 60 else ''),
    })

orig_markers.sort(key=lambda x: x['time'])

# DCA trade markers (only the DCA'd trades)
dca_markers = []
for r in dca_results:
    # DCA entry (at stop level)
    dca_markers.append({
        'time': r['dca_entry_ts'],
        'position': 'belowBar',
        'color': '#a855f7',  # purple — DCA entry
        'shape': 'arrowUp',
        'text': 'DCA',
    })
    # DCA exit
    if r['outcome'] == 'breakeven':
        exit_color = '#22d3ee'  # cyan — breakeven recovery
        text = 'BE'
    elif r['outcome'] == 'hard_stop':
        exit_color = '#f97316'  # orange — hard stop
        text = 'HS'
    else:
        exit_color = '#f59e0b'  # yellow — timeout
        text = 'TO'

    dca_markers.append({
        'time': r['dca_exit_ts'],
        'position': 'aboveBar',
        'color': exit_color,
        'shape': 'arrowDown',
        'text': text,
    })

# Bear-skipped markers
for s in skipped_bear:
    exit_ts = parse_ts(s['exit_date'])
    dca_markers.append({
        'time': exit_ts,
        'position': 'belowBar',
        'color': '#64748b',  # gray — skipped
        'shape': 'circle',
        'text': '',
    })

dca_markers.sort(key=lambda x: x['time'])

# ── Prepare OHLC for chart ──────────────────────────────────────────
ohlc_data = [{'time': b['time'], 'open': b['open'], 'high': b['high'],
              'low': b['low'], 'close': b['close'], 'volume': b.get('volume', 0)}
             for b in bars]

# ── DCA detail data for tooltip ──────────────────────────────────────
dca_detail = []
for r in dca_results:
    dca_detail.append({
        'entry_ts': r['dca_entry_ts'],
        'exit_ts': r['dca_exit_ts'],
        'entry1': r['entry1'],
        'entry2': r['entry2'],
        'avg_cost': r['avg_cost'],
        'be_target': r['be_target'],
        'hard_stop': r['hard_stop'],
        'exit_price': r['exit_price'],
        'orig_pnl': r['orig_pnl'],
        'dca_pnl': r['dca_pnl'],
        'improvement': r['improvement'],
        'outcome': r['outcome'],
        'bars': r['bars_after'],
    })

# ── Generate HTML ────────────────────────────────────────────────────
html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ATLAS DCA Backtest — V2B-Long-60 + SMA(200) Regime Filter</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0e17; color: #c8ccd4; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 12px; }}

  .header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 20px; background: #111827; border-bottom: 1px solid #1e293b;
  }}
  .header h1 {{ font-size: 14px; font-weight: 600; color: #e2e8f0; }}
  .header .sub {{ font-size: 11px; color: #64748b; margin-left: 12px; }}

  .controls {{
    display: flex; gap: 6px; align-items: center;
  }}
  .btn {{
    padding: 4px 12px; border-radius: 4px; border: 1px solid #1e293b;
    background: #0f172a; color: #94a3b8; cursor: pointer; font-size: 11px;
    font-family: inherit; transition: all 0.15s;
  }}
  .btn:hover {{ border-color: #334155; color: #e2e8f0; }}
  .btn.active {{ border-color: #3b82f6; background: #1e3a5f; color: #e2e8f0; }}
  .btn-dca.active {{ border-color: #a855f7; background: #3b1f5e; }}

  #price-chart {{ width: 100%; height: calc(50vh - 50px); }}
  #equity-chart {{ width: 100%; height: calc(50vh - 90px); }}

  .section-label {{
    padding: 4px 20px; background: #0f172a; border-top: 1px solid #1e293b;
    border-bottom: 1px solid #1e293b; font-size: 11px; color: #64748b;
    display: flex; align-items: center; justify-content: space-between;
  }}

  .stats-bar {{
    display: flex; gap: 16px; padding: 8px 20px;
    background: #111827; border-top: 1px solid #1e293b; font-size: 11px;
    flex-wrap: wrap;
  }}
  .stat {{ display: flex; gap: 4px; }}
  .stat-label {{ color: #64748b; }}
  .stat-value {{ color: #e2e8f0; font-weight: 600; }}
  .stat-win {{ color: #22c55e; }}
  .stat-loss {{ color: #ef4444; }}
  .stat-improve {{ color: #a855f7; }}

  .compare-panel {{
    display: flex; gap: 0; padding: 0 20px 0 20px;
    background: #111827; font-size: 11px;
  }}
  .compare-col {{
    flex: 1; padding: 8px 12px;
    border-right: 1px solid #1e293b;
  }}
  .compare-col:last-child {{ border-right: none; }}
  .compare-col h3 {{
    font-size: 11px; margin-bottom: 6px; padding-bottom: 4px;
    border-bottom: 1px solid #1e293b;
  }}
  .compare-col .row {{
    display: flex; justify-content: space-between; padding: 1px 0;
  }}
  .compare-col .row .lbl {{ color: #64748b; }}
  .delta-col {{ background: #0f172a; }}
  .delta-col h3 {{ color: #a855f7; }}

  .legend {{
    display: flex; gap: 14px; align-items: center; font-size: 10px;
  }}
  .legend-item {{
    display: flex; align-items: center; gap: 4px;
  }}
  .legend-dot {{
    width: 8px; height: 8px; border-radius: 50%;
  }}

  .trade-info {{
    position: fixed; top: 80px; right: 20px; width: 280px;
    background: #111827ee; border: 1px solid #1e293b; border-radius: 8px;
    padding: 12px; display: none; z-index: 10; font-size: 11px;
  }}
  .trade-info h3 {{ font-size: 12px; margin-bottom: 8px; color: #e2e8f0; }}
  .trade-info .row {{ display: flex; justify-content: space-between; padding: 2px 0; }}
  .trade-info .row .label {{ color: #64748b; }}
</style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:baseline;">
    <h1>ATLAS DCA BACKTEST</h1>
    <span class="sub">V2B-Long-60 &bull; SPY 4H &bull; SMA(200) Regime Filter &bull; 2021-2026</span>
  </div>
  <div class="controls">
    <span style="color:#64748b;margin-right:4px;">View:</span>
    <button class="btn active" data-view="original">Original</button>
    <button class="btn btn-dca" data-view="dca">DCA Trades</button>
    <button class="btn" data-view="both">Both</button>
  </div>
</div>

<div id="price-chart"></div>

<div class="section-label">
  <span>EQUITY CURVE COMPARISON</span>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#3b82f6;"></div> Original</div>
    <div class="legend-item"><div class="legend-dot" style="background:#a855f7;"></div> With DCA</div>
    <div class="legend-item"><div class="legend-dot" style="background:#22d3ee;"></div> DCA Breakeven</div>
    <div class="legend-item"><div class="legend-dot" style="background:#f97316;"></div> DCA Hard Stop</div>
    <div class="legend-item"><div class="legend-dot" style="background:#64748b;"></div> Bear Skipped</div>
  </div>
</div>

<div id="equity-chart"></div>

<div class="compare-panel">
  <div class="compare-col">
    <h3 style="color:#3b82f6;">ORIGINAL</h3>
    <div class="row"><span class="lbl">Trades</span> <span>{orig_stats['trades']}</span></div>
    <div class="row"><span class="lbl">Win Rate</span> <span>{orig_stats['win_rate']}%</span></div>
    <div class="row"><span class="lbl">PnL</span> <span class="{'stat-win' if orig_stats['total_pnl']>0 else 'stat-loss'}">${orig_stats['total_pnl']:+,.0f}</span></div>
    <div class="row"><span class="lbl">Return</span> <span>{orig_stats['return_pct']:+.1f}%</span></div>
    <div class="row"><span class="lbl">Profit Factor</span> <span>{orig_stats['profit_factor']}</span></div>
    <div class="row"><span class="lbl">Max DD</span> <span class="stat-loss">{orig_stats['max_drawdown']:.1f}%</span></div>
    <div class="row"><span class="lbl">Avg Win</span> <span class="stat-win">${orig_stats['avg_win']:,.0f}</span></div>
    <div class="row"><span class="lbl">Avg Loss</span> <span class="stat-loss">${orig_stats['avg_loss']:,.0f}</span></div>
    <div class="row"><span class="lbl">R:R</span> <span>{orig_stats['rr_ratio']}:1</span></div>
  </div>
  <div class="compare-col">
    <h3 style="color:#a855f7;">WITH DCA</h3>
    <div class="row"><span class="lbl">Trades</span> <span>{dca_stats['trades']}</span></div>
    <div class="row"><span class="lbl">Win Rate</span> <span>{dca_stats['win_rate']}%</span></div>
    <div class="row"><span class="lbl">PnL</span> <span class="{'stat-win' if dca_stats['total_pnl']>0 else 'stat-loss'}">${dca_stats['total_pnl']:+,.0f}</span></div>
    <div class="row"><span class="lbl">Return</span> <span>{dca_stats['return_pct']:+.1f}%</span></div>
    <div class="row"><span class="lbl">Profit Factor</span> <span>{dca_stats['profit_factor']}</span></div>
    <div class="row"><span class="lbl">Max DD</span> <span class="stat-loss">{dca_stats['max_drawdown']:.1f}%</span></div>
    <div class="row"><span class="lbl">Avg Win</span> <span class="stat-win">${dca_stats['avg_win']:,.0f}</span></div>
    <div class="row"><span class="lbl">Avg Loss</span> <span class="stat-loss">${dca_stats['avg_loss']:,.0f}</span></div>
    <div class="row"><span class="lbl">R:R</span> <span>{dca_stats['rr_ratio']}:1</span></div>
  </div>
  <div class="compare-col delta-col">
    <h3>DELTA</h3>
    <div class="row"><span class="lbl">DCA Trades</span> <span>{len(dca_results)}</span></div>
    <div class="row"><span class="lbl">Breakeven</span> <span class="stat-win">{len([r for r in dca_results if r['outcome']=='breakeven'])}/{len(dca_results)} ({len([r for r in dca_results if r['outcome']=='breakeven'])/len(dca_results)*100:.0f}%)</span></div>
    <div class="row"><span class="lbl">Hard Stop</span> <span class="stat-loss">{len([r for r in dca_results if r['outcome']=='hard_stop'])}/{len(dca_results)}</span></div>
    <div class="row"><span class="lbl">Bear Skipped</span> <span>{len(skipped_bear)}</span></div>
    <div class="row"><span class="lbl">PnL Delta</span> <span class="stat-improve">${dca_stats['total_pnl'] - orig_stats['total_pnl']:+,.0f}</span></div>
    <div class="row"><span class="lbl">Return Delta</span> <span class="stat-improve">{dca_stats['return_pct'] - orig_stats['return_pct']:+.1f}%</span></div>
    <div class="row"><span class="lbl">Avg Recovery</span> <span>{sum(r['bars_after'] for r in dca_results if r['outcome']=='breakeven') / max(1, len([r for r in dca_results if r['outcome']=='breakeven'])):.1f} bars</span></div>
    <div class="row"><span class="lbl">Improvement</span> <span class="stat-improve">${sum(r['improvement'] for r in dca_results):+,.0f}</span></div>
    <div class="row"><span class="lbl">Bear Avoided</span> <span class="stat-win">${abs(sum(s['orig_pnl'] for s in skipped_bear) - sum(r['orig_pnl'] for r in dca_results)):+,.0f}</span></div>
  </div>
</div>

<div class="trade-info" id="trade-info">
  <h3 id="ti-title">DCA Trade Detail</h3>
  <div class="row"><span class="label">Entry 1:</span> <span id="ti-e1"></span></div>
  <div class="row"><span class="label">Entry 2 (DCA):</span> <span id="ti-e2"></span></div>
  <div class="row"><span class="label">Avg Cost:</span> <span id="ti-avg"></span></div>
  <div class="row"><span class="label">BE Target:</span> <span id="ti-be"></span></div>
  <div class="row"><span class="label">Hard Stop:</span> <span id="ti-hs"></span></div>
  <div class="row"><span class="label">Exit:</span> <span id="ti-exit"></span></div>
  <div class="row"><span class="label">Orig PnL:</span> <span id="ti-orig"></span></div>
  <div class="row"><span class="label">DCA PnL:</span> <span id="ti-dca"></span></div>
  <div class="row"><span class="label">Improvement:</span> <span id="ti-imp"></span></div>
  <div class="row"><span class="label">Outcome:</span> <span id="ti-out"></span></div>
  <div class="row"><span class="label">Bars:</span> <span id="ti-bars"></span></div>
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
const OHLC = {json.dumps(ohlc_data)};
const SMA200 = {json.dumps(sma_line)};
const ORIG_MARKERS = {json.dumps(orig_markers)};
const DCA_MARKERS = {json.dumps(dca_markers)};
const EQ_ORIG = {json.dumps(equity_orig)};
const EQ_DCA = {json.dumps(equity_dca)};
const DCA_DETAIL = {json.dumps(dca_detail)};

const chartOpts = {{
  layout: {{ background: {{ type: 'solid', color: '#0a0e17' }}, textColor: '#64748b', fontSize: 11 }},
  grid: {{ vertLines: {{ color: '#111827' }}, horzLines: {{ color: '#111827' }} }},
  crosshair: {{
    mode: LightweightCharts.CrosshairMode.Normal,
    vertLine: {{ color: '#334155', labelBackgroundColor: '#1e293b' }},
    horzLine: {{ color: '#334155', labelBackgroundColor: '#1e293b' }},
  }},
  timeScale: {{ borderColor: '#1e293b', timeVisible: true, secondsVisible: false }},
  rightPriceScale: {{ borderColor: '#1e293b' }},
}};

// ── Price Chart ──────────────────────────────────────────────────
const priceContainer = document.getElementById('price-chart');
const priceChart = LightweightCharts.createChart(priceContainer, chartOpts);

const candleSeries = priceChart.addCandlestickSeries({{
  upColor: '#22c55e', downColor: '#ef4444',
  borderUpColor: '#22c55e', borderDownColor: '#ef4444',
  wickUpColor: '#22c55e80', wickDownColor: '#ef444480',
}});
candleSeries.setData(OHLC);

const smaLine = priceChart.addLineSeries({{
  color: '#f59e0b80', lineWidth: 1, lineStyle: 2,
  priceLineVisible: false, lastValueVisible: false,
  title: 'SMA(200)',
}});
smaLine.setData(SMA200);

const volumeSeries = priceChart.addHistogramSeries({{
  priceFormat: {{ type: 'volume' }}, priceScaleId: 'volume',
}});
priceChart.priceScale('volume').applyOptions({{ scaleMargins: {{ top: 0.85, bottom: 0 }} }});
volumeSeries.setData(OHLC.map(b => ({{
  time: b.time, value: b.volume,
  color: b.close >= b.open ? '#22c55e20' : '#ef444420',
}})));

// ── Equity Chart ─────────────────────────────────────────────────
const eqContainer = document.getElementById('equity-chart');
const eqChart = LightweightCharts.createChart(eqContainer, {{
  ...chartOpts,
  rightPriceScale: {{ borderColor: '#1e293b', scaleMargins: {{ top: 0.1, bottom: 0.1 }} }},
}});

const eqOrigLine = eqChart.addLineSeries({{
  color: '#3b82f6', lineWidth: 2, title: 'Original',
  priceLineVisible: false, lastValueVisible: true,
}});
eqOrigLine.setData(EQ_ORIG);

const eqDcaLine = eqChart.addLineSeries({{
  color: '#a855f7', lineWidth: 2, title: 'With DCA',
  priceLineVisible: false, lastValueVisible: true,
}});
eqDcaLine.setData(EQ_DCA);

// Baseline at initial cash
const baseLine = eqChart.addLineSeries({{
  color: '#334155', lineWidth: 1, lineStyle: 2,
  priceLineVisible: false, lastValueVisible: false,
}});
if (EQ_ORIG.length > 0) {{
  baseLine.setData([
    {{ time: EQ_ORIG[0].time, value: {initial_cash} }},
    {{ time: EQ_ORIG[EQ_ORIG.length-1].time, value: {initial_cash} }},
  ]);
}}

// ── Sync crosshairs ──────────────────────────────────────────────
priceChart.timeScale().subscribeVisibleTimeRangeChange(() => {{
  const range = priceChart.timeScale().getVisibleRange();
  if (range) eqChart.timeScale().setVisibleRange(range);
}});
eqChart.timeScale().subscribeVisibleTimeRangeChange(() => {{
  const range = eqChart.timeScale().getVisibleRange();
  if (range) priceChart.timeScale().setVisibleRange(range);
}});

// ── View toggle ──────────────────────────────────────────────────
let currentView = 'original';

function updateView() {{
  if (currentView === 'original') {{
    candleSeries.setMarkers(ORIG_MARKERS);
  }} else if (currentView === 'dca') {{
    candleSeries.setMarkers(DCA_MARKERS);
  }} else {{
    const all = [...ORIG_MARKERS, ...DCA_MARKERS].sort((a, b) => a.time - b.time);
    candleSeries.setMarkers(all);
  }}
}}

document.querySelectorAll('.btn[data-view]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.btn[data-view]').forEach(b => {{
      b.classList.remove('active');
    }});
    btn.classList.add('active');
    currentView = btn.dataset.view;
    updateView();
  }});
}});

updateView();
priceChart.timeScale().fitContent();
eqChart.timeScale().fitContent();

// ── Resize ───────────────────────────────────────────────────────
new ResizeObserver(() => {{
  priceChart.applyOptions({{ width: priceContainer.clientWidth, height: priceContainer.clientHeight }});
  eqChart.applyOptions({{ width: eqContainer.clientWidth, height: eqContainer.clientHeight }});
}}).observe(document.body);
</script>
</body>
</html>'''

# ── Write output ─────────────────────────────────────────────────
output_path = '/opt/compose/backtrader-results/dca-backtest.html'
with open(output_path, 'w') as f:
    f.write(html)

print(f"Generated: {output_path}")
print(f"Size: {len(html) / 1024:.0f} KB")
print()
print("=== ORIGINAL vs DCA COMPARISON ===")
print(f"{'':>20} {'Original':>12} {'With DCA':>12} {'Delta':>12}")
print(f"{'Trades':>20} {orig_stats['trades']:>12} {dca_stats['trades']:>12} {'':>12}")
print(f"{'Win Rate':>20} {orig_stats['win_rate']:>11}% {dca_stats['win_rate']:>11}% {dca_stats['win_rate']-orig_stats['win_rate']:>+11.1f}%")
print(f"{'Total PnL':>20} ${orig_stats['total_pnl']:>+10,.0f} ${dca_stats['total_pnl']:>+10,.0f} ${dca_stats['total_pnl']-orig_stats['total_pnl']:>+10,.0f}")
print(f"{'Return':>20} {orig_stats['return_pct']:>+11.1f}% {dca_stats['return_pct']:>+11.1f}% {dca_stats['return_pct']-orig_stats['return_pct']:>+11.1f}%")
print(f"{'Profit Factor':>20} {orig_stats['profit_factor']:>12} {dca_stats['profit_factor']:>12}")
print(f"{'Max Drawdown':>20} {orig_stats['max_drawdown']:>11.1f}% {dca_stats['max_drawdown']:>11.1f}%")
print(f"{'R:R':>20} {orig_stats['rr_ratio']:>11}:1 {dca_stats['rr_ratio']:>11}:1")
print()
print(f"DCA Trades: {len(dca_results)} | Breakeven: {len([r for r in dca_results if r['outcome']=='breakeven'])} ({len([r for r in dca_results if r['outcome']=='breakeven'])/len(dca_results)*100:.0f}%) | Hard Stop: {len([r for r in dca_results if r['outcome']=='hard_stop'])} | Bear Skipped: {len(skipped_bear)}")
