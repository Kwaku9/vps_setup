/**
 * ATLAS Charts — TradingView Lightweight Charts frontend
 * Fetches OHLC data from VictoriaMetrics and renders interactive charts.
 */

const VM_PROXY = '/api/vm';

const STEP_MAP = {
    '1m': 60, '5m': 300, '15m': 900, '1h': 3600,
    '4h': 14400, '1d': 86400, '1w': 604800
};

const LOOKBACK_MAP = {
    '1m': 24 * 3600,
    '5m': 5 * 24 * 3600,
    '15m': 10 * 24 * 3600,
    '1h': 30 * 24 * 3600,
    '4h': 90 * 24 * 3600,
    '1d': 365 * 24 * 3600,
    '1w': 3 * 365 * 24 * 3600,
};

const COLORS = {
    up: '#22c55e',
    down: '#ef4444',
    wick: '#6b7280',
    bg: '#0a0e17',
    grid: '#1f293733',
    text: '#6b7280',
    crosshair: '#374151',
    sma20: '#f59e0b',
    sma50: '#8b5cf6',
    ema9: '#06b6d4',
    ema21: '#ec4899',
    bbUpper: '#6b728066',
    bbLower: '#6b728066',
    volume: '#374151',
};

let chart, candleSeries, volumeSeries;
let overlays = {};
let currentSymbol = 'SPY';
let currentTimeframe = '1d';
let activeIndicators = new Set();
let ohlcData = [];

function initChart() {
    const container = document.getElementById('chartContainer');
    chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        layout: {
            background: { type: 'solid', color: COLORS.bg },
            textColor: COLORS.text,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
        },
        grid: {
            vertLines: { color: COLORS.grid },
            horzLines: { color: COLORS.grid },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: COLORS.crosshair, labelBackgroundColor: '#1f2937' },
            horzLine: { color: COLORS.crosshair, labelBackgroundColor: '#1f2937' },
        },
        rightPriceScale: {
            borderColor: '#1f2937',
            scaleMargins: { top: 0.05, bottom: 0.2 },
        },
        timeScale: {
            borderColor: '#1f2937',
            timeVisible: currentTimeframe !== '1d' && currentTimeframe !== '1w',
            secondsVisible: false,
        },
    });

    candleSeries = chart.addCandlestickSeries({
        upColor: COLORS.up,
        downColor: COLORS.down,
        borderUpColor: COLORS.up,
        borderDownColor: COLORS.down,
        wickUpColor: COLORS.up,
        wickDownColor: COLORS.down,
    });

    volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
    });

    // Crosshair move handler for stats
    chart.subscribeCrosshairMove((param) => {
        if (!param.time || !param.seriesData) return;
        const candle = param.seriesData.get(candleSeries);
        if (candle) updateStats(candle);
    });

    window.addEventListener('resize', () => {
        chart.resize(container.clientWidth, container.clientHeight);
    });
}

function updateStats(candle) {
    const fmt = (v) => v != null ? v.toFixed(2) : '-';
    document.getElementById('statOpen').textContent = fmt(candle.open);
    document.getElementById('statHigh').textContent = fmt(candle.high);
    document.getElementById('statLow').textContent = fmt(candle.low);
    document.getElementById('statClose').textContent = fmt(candle.close);

    const chg = candle.close - candle.open;
    const chgPct = candle.open > 0 ? (chg / candle.open * 100) : 0;
    const chgEl = document.getElementById('statChg');
    chgEl.textContent = `${chg >= 0 ? '+' : ''}${chg.toFixed(2)} (${chgPct.toFixed(2)}%)`;
    chgEl.className = `stat-value ${chg >= 0 ? 'positive' : 'negative'}`;
}

async function queryVM(metric, symbol, timeframe, start, end) {
    const step = STEP_MAP[timeframe] || 86400;
    const query = `ohlc_${metric}{symbol="${symbol}",timeframe="${timeframe}"}`;
    const url = `${VM_PROXY}/api/v1/query_range?query=${encodeURIComponent(query)}&start=${start}&end=${end}&step=${step}`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`VM query failed: ${resp.status}`);
    const data = await resp.json();
    if (!data.data?.result?.[0]?.values) return [];
    return data.data.result[0].values.map(([ts, val]) => [Number(ts), Number(val)]);
}

async function loadOHLC(symbol, timeframe, overrideStart, overrideEnd) {
    const loading = document.getElementById('loading');
    loading.style.display = 'block';

    const now = Math.floor(Date.now() / 1000);
    const lookback = LOOKBACK_MAP[timeframe] || 365 * 86400;
    const start = overrideStart || (now - lookback);
    const end = overrideEnd || now;

    try {
        const [opens, highs, lows, closes, volumes] = await Promise.all([
            queryVM('open', symbol, timeframe, start, end),
            queryVM('high', symbol, timeframe, start, end),
            queryVM('low', symbol, timeframe, start, end),
            queryVM('close', symbol, timeframe, start, end),
            queryVM('volume', symbol, timeframe, start, end),
        ]);

        if (!closes.length) {
            showToast(`No data for ${symbol} ${timeframe}`, true);
            loading.style.display = 'none';
            return;
        }

        // Build OHLCV by timestamp
        const tsMap = {};
        closes.forEach(([ts, v]) => { tsMap[ts] = { time: ts, close: v }; });
        opens.forEach(([ts, v]) => { if (tsMap[ts]) tsMap[ts].open = v; });
        highs.forEach(([ts, v]) => { if (tsMap[ts]) tsMap[ts].high = v; });
        lows.forEach(([ts, v]) => { if (tsMap[ts]) tsMap[ts].low = v; });
        volumes.forEach(([ts, v]) => { if (tsMap[ts]) tsMap[ts].volume = v; });

        ohlcData = Object.values(tsMap)
            .filter(d => d.open && d.high && d.low && d.close)
            .sort((a, b) => a.time - b.time);

        // Set candle data
        candleSeries.setData(ohlcData);

        // Volume bars
        const volData = ohlcData.map(d => ({
            time: d.time,
            value: d.volume || 0,
            color: d.close >= d.open ? COLORS.up + '44' : COLORS.down + '44',
        }));
        volumeSeries.setData(volData);

        // Recompute indicators
        activeIndicators.forEach(ind => addIndicator(ind));

        chart.timeScale().fitContent();
        loading.style.display = 'none';

        // Update stats with last bar
        if (ohlcData.length) updateStats(ohlcData[ohlcData.length - 1]);
        document.getElementById('statVol').textContent = formatVolume(ohlcData[ohlcData.length - 1]?.volume || 0);

    } catch (err) {
        console.error('Load failed:', err);
        showToast(`Error: ${err.message}`, true);
        loading.style.display = 'none';
    }
}

function formatVolume(v) {
    if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return v.toFixed(0);
}

// --- Indicators ---

function computeSMA(data, period) {
    const result = [];
    for (let i = period - 1; i < data.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += data[j].close;
        result.push({ time: data[i].time, value: sum / period });
    }
    return result;
}

function computeEMA(data, period) {
    const result = [];
    const k = 2 / (period + 1);
    let ema = data.slice(0, period).reduce((s, d) => s + d.close, 0) / period;
    result.push({ time: data[period - 1].time, value: ema });
    for (let i = period; i < data.length; i++) {
        ema = data[i].close * k + ema * (1 - k);
        result.push({ time: data[i].time, value: ema });
    }
    return result;
}

function computeBB(data, period, mult) {
    const upper = [], lower = [];
    for (let i = period - 1; i < data.length; i++) {
        let sum = 0, sumSq = 0;
        for (let j = i - period + 1; j <= i; j++) {
            sum += data[j].close;
            sumSq += data[j].close * data[j].close;
        }
        const mean = sum / period;
        const std = Math.sqrt(sumSq / period - mean * mean);
        upper.push({ time: data[i].time, value: mean + mult * std });
        lower.push({ time: data[i].time, value: mean - mult * std });
    }
    return { upper, lower };
}

function addIndicator(name) {
    removeIndicator(name);
    if (!ohlcData.length) return;

    switch (name) {
        case 'sma20': {
            const line = chart.addLineSeries({ color: COLORS.sma20, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
            line.setData(computeSMA(ohlcData, 20));
            overlays[name] = [line];
            break;
        }
        case 'sma50': {
            const line = chart.addLineSeries({ color: COLORS.sma50, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
            line.setData(computeSMA(ohlcData, 50));
            overlays[name] = [line];
            break;
        }
        case 'ema9': {
            const line = chart.addLineSeries({ color: COLORS.ema9, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
            line.setData(computeEMA(ohlcData, 9));
            overlays[name] = [line];
            break;
        }
        case 'ema21': {
            const line = chart.addLineSeries({ color: COLORS.ema21, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
            line.setData(computeEMA(ohlcData, 21));
            overlays[name] = [line];
            break;
        }
        case 'bb': {
            const bb = computeBB(ohlcData, 20, 2);
            const upper = chart.addLineSeries({ color: COLORS.bbUpper, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
            const lower = chart.addLineSeries({ color: COLORS.bbLower, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
            upper.setData(bb.upper);
            lower.setData(bb.lower);
            overlays[name] = [upper, lower];
            break;
        }
    }
}

function removeIndicator(name) {
    if (overlays[name]) {
        overlays[name].forEach(s => chart.removeSeries(s));
        delete overlays[name];
    }
}

// --- Backtest overlay ---

async function loadBacktest() {
    const params = new URLSearchParams(window.location.search);
    const runId = params.get('backtest');
    if (!runId) return null;

    try {
        const resp = await fetch(`/api/vm/api/v1/query?query=backtest_info{run_id="${runId}"}`);
        // Backtest results loaded from JSON file (mounted volume)
        const fileResp = await fetch(`/backtest-results/${runId}.json`);
        if (fileResp.ok) return await fileResp.json();
    } catch (e) {
        console.warn('No backtest data:', e);
    }
    return null;
}

function renderBacktestPanel(bt) {
    if (!bt) return;
    const panel = document.getElementById('backtestPanel');
    panel.classList.add('visible');
    panel.innerHTML = `
        <div class="backtest-title">${bt.strategy_name} Backtest</div>
        <div class="metric-row"><span class="metric-name">Period</span><span class="metric-val">${bt.start_date} to ${bt.end_date}</span></div>
        <div class="metric-row"><span class="metric-name">Initial</span><span class="metric-val">$${Number(bt.initial_cash).toLocaleString()}</span></div>
        <div class="metric-row"><span class="metric-name">Final</span><span class="metric-val">$${Number(bt.final_value).toLocaleString()}</span></div>
        <div class="metric-row"><span class="metric-name">Return</span><span class="metric-val ${bt.total_return_pct >= 0 ? 'positive' : 'negative'}">${bt.total_return_pct.toFixed(2)}%</span></div>
        <div class="metric-row"><span class="metric-name">Sharpe</span><span class="metric-val">${bt.sharpe_ratio?.toFixed(2) || '-'}</span></div>
        <div class="metric-row"><span class="metric-name">Sortino</span><span class="metric-val">${bt.sortino_ratio?.toFixed(2) || '-'}</span></div>
        <div class="metric-row"><span class="metric-name">Max DD</span><span class="metric-val negative">${bt.max_drawdown_pct?.toFixed(2) || '-'}%</span></div>
        <div class="metric-row"><span class="metric-name">Win Rate</span><span class="metric-val">${(bt.win_rate * 100).toFixed(1)}%</span></div>
        <div class="metric-row"><span class="metric-name">Profit Factor</span><span class="metric-val">${bt.profit_factor?.toFixed(2) || '-'}</span></div>
        <div class="metric-row"><span class="metric-name">Trades</span><span class="metric-val">${bt.total_trades}</span></div>
        <div class="metric-row"><span class="metric-name">Avg Win</span><span class="metric-val positive">$${bt.avg_win?.toFixed(2) || '-'}</span></div>
        <div class="metric-row"><span class="metric-name">Avg Loss</span><span class="metric-val negative">$${bt.avg_loss?.toFixed(2) || '-'}</span></div>
    `;

    // Add trade markers to chart
    if (bt.trades && candleSeries) {
        const markers = [];
        bt.trades.forEach(t => {
            const entryTs = Math.floor(new Date(t.entry_date).getTime() / 1000);
            const exitTs = t.exit_date ? Math.floor(new Date(t.exit_date).getTime() / 1000) : null;

            markers.push({
                time: entryTs,
                position: t.direction === 'long' ? 'belowBar' : 'aboveBar',
                color: COLORS.up,
                shape: t.direction === 'long' ? 'arrowUp' : 'arrowDown',
                text: `${t.direction.toUpperCase()} @${t.entry_price}`,
            });

            if (exitTs) {
                markers.push({
                    time: exitTs,
                    position: t.pnl >= 0 ? 'aboveBar' : 'belowBar',
                    color: t.pnl >= 0 ? COLORS.up : COLORS.down,
                    shape: 'circle',
                    text: `$${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(0)}`,
                });
            }
        });
        markers.sort((a, b) => a.time - b.time);
        candleSeries.setMarkers(markers);
    }
}

// --- Toast ---

function showToast(msg, isError) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = `toast visible${isError ? ' error' : ''}`;
    setTimeout(() => { el.className = 'toast'; }, 3000);
}

// --- URL state ---

function updateURL() {
    const params = new URLSearchParams(window.location.search);
    params.set('symbol', currentSymbol);
    params.set('tf', currentTimeframe);
    history.replaceState(null, '', '?' + params.toString());
}

function loadFromURL() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('symbol')) currentSymbol = params.get('symbol').toUpperCase();
    if (params.get('tf')) currentTimeframe = params.get('tf');
}

// --- Init ---

document.addEventListener('DOMContentLoaded', async () => {
    loadFromURL();
    initChart();

    // Symbol input
    const symbolInput = document.getElementById('symbolInput');
    symbolInput.value = currentSymbol;
    symbolInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            currentSymbol = symbolInput.value.toUpperCase().trim();
            symbolInput.value = currentSymbol;
            updateURL();
            loadOHLC(currentSymbol, currentTimeframe);
        }
    });

    // Timeframe buttons
    document.querySelectorAll('.tf-btn').forEach(btn => {
        if (btn.dataset.tf === currentTimeframe) btn.classList.add('active');
        else btn.classList.remove('active');

        btn.addEventListener('click', () => {
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTimeframe = btn.dataset.tf;
            chart.applyOptions({
                timeScale: {
                    timeVisible: currentTimeframe !== '1d' && currentTimeframe !== '1w',
                },
            });
            updateURL();
            loadOHLC(currentSymbol, currentTimeframe);
        });
    });

    // Indicator toggles
    document.querySelectorAll('.indicator-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const ind = btn.dataset.ind;
            if (ind === 'backtest') {
                document.getElementById('backtestPanel').classList.toggle('visible');
                btn.classList.toggle('active');
                return;
            }
            if (ind === 'volume') {
                const visible = btn.classList.toggle('active');
                chart.priceScale('volume').applyOptions({
                    scaleMargins: { top: visible ? 0.7 : 0.99, bottom: 0 },
                });
                return;
            }
            btn.classList.toggle('active');
            if (activeIndicators.has(ind)) {
                activeIndicators.delete(ind);
                removeIndicator(ind);
            } else {
                activeIndicators.add(ind);
                addIndicator(ind);
            }
        });
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT') return;
        const tfKeys = { '1': '1m', '2': '5m', '3': '15m', '4': '1h', '5': '4h', '6': '1d', '7': '1w' };
        if (tfKeys[e.key]) {
            currentTimeframe = tfKeys[e.key];
            document.querySelectorAll('.tf-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.tf === currentTimeframe);
            });
            updateURL();
            loadOHLC(currentSymbol, currentTimeframe);
        }
        if (e.key === '/') {
            e.preventDefault();
            symbolInput.focus();
            symbolInput.select();
        }
    });

    // Check for backtest overlay first to set date range
    const bt = await loadBacktest();
    if (bt && bt.start_date && bt.end_date) {
        const btStart = Math.floor(new Date(bt.start_date).getTime() / 1000);
        const btEnd = Math.floor(new Date(bt.end_date).getTime() / 1000) + 86400;
        await loadOHLC(currentSymbol, currentTimeframe, btStart, btEnd);
    } else {
        await loadOHLC(currentSymbol, currentTimeframe);
    }

    if (bt) renderBacktestPanel(bt);
});
