// The signal strip: stacked density histogram (honeypot/probes/bans) with
// drag-to-select replay range, hover crosshair + tooltip, and playhead.
// Data tones are the validated chart palette; identity is also carried by the
// legend chips above the strip (never color alone).
import { el, clamp, fmtClock } from './util.js';

const TONES = { honeypot: '#00a95e', probes: '#2789cc', bans: '#e8304b' };
const ORDER = ['honeypot', 'probes', 'bans'];   // fixed stack order, bottom→top
const SELECT = '#ffb347';

export class Timeline {
  constructor(canvas, tooltipEl, { onSelect, onSeek } = {}) {
    this.canvas = canvas;
    this.tooltip = tooltipEl;
    this.onSelect = onSelect || (() => {});
    this.onSeek = onSeek || (() => {});
    this.scope = null;          // {start, end}
    this.buckets = [];
    this.stepMs = 0;
    this.selection = null;      // {a, b} ms
    this.playhead = null;       // ms
    this.enabled = { honeypot: true, probes: true, bans: true };
    this.seekMode = false;      // during replay a click seeks instead of selecting
    this._drag = null;
    this._hoverX = null;
    this._bind();
  }

  _bind() {
    const c = this.canvas;
    c.addEventListener('pointerdown', (e) => {
      if (!this.scope) return;
      c.setPointerCapture(e.pointerId);
      const t = this._xToTime(e.offsetX);
      if (this.seekMode) { this.onSeek(t); return; }
      this._drag = { a: t, b: t, moved: false };
    });
    c.addEventListener('pointermove', (e) => {
      this._hoverX = e.offsetX;
      if (this._drag) {
        this._drag.b = this._xToTime(e.offsetX);
        this._drag.moved = true;
        this.selection = this._normDrag();
      }
      this.render();
      this._renderTooltip(e);
    });
    c.addEventListener('pointerup', () => {
      if (this._drag) {
        if (this._drag.moved && this.selection
            && this.selection.b - this.selection.a > 10_000) {
          this.onSelect(this.selection);
        } else {
          this.selection = null;
          this.onSelect(null);
        }
        this._drag = null;
        this.render();
      }
    });
    c.addEventListener('pointerleave', () => {
      this._hoverX = null;
      this.tooltip.style.display = 'none';
      this.render();
    });
    c.addEventListener('dblclick', () => {
      this.selection = null;
      this.onSelect(null);
      this.render();
    });
    new ResizeObserver(() => this.render()).observe(c.parentElement);
  }

  _normDrag() {
    const { a, b } = this._drag;
    return { a: Math.min(a, b), b: Math.max(a, b) };
  }

  setData(scope, histogram) {
    this.scope = scope;
    this.buckets = histogram?.buckets || [];
    this.stepMs = histogram?.step_ms || 0;
    this.render();
  }

  setEnabled(enabled) { this.enabled = { ...enabled }; this.render(); }
  setPlayhead(ms) { this.playhead = ms; this.render(); }
  setSelection(sel) { this.selection = sel; this.render(); }

  _xToTime(x) {
    const w = this.canvas.clientWidth;
    return clamp(this.scope.start + (x / w) * (this.scope.end - this.scope.start),
      this.scope.start, this.scope.end);
  }

  _timeToX(t) {
    const w = this.canvas.clientWidth;
    return ((t - this.scope.start) / (this.scope.end - this.scope.start)) * w;
  }

  _bucketAt(x) {
    if (!this.buckets.length || !this.scope) return null;
    const t = this._xToTime(x);
    return this.buckets.find((b) => t >= b.t && t < b.t + this.stepMs) || null;
  }

  render() {
    const c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = c.parentElement.clientWidth;
    const h = c.parentElement.clientHeight;
    if (!w || !h) return;
    if (c.width !== w * dpr || c.height !== h * dpr) {
      c.width = w * dpr; c.height = h * dpr;
      c.style.width = `${w}px`; c.style.height = `${h}px`;
    }
    const ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!this.scope) return;

    const axisH = 14;
    const plotH = h - axisH;

    // Recessive hour/day gridlines.
    ctx.strokeStyle = 'rgba(85,112,127,0.18)';
    ctx.lineWidth = 1;
    const ticks = this._ticks();
    ctx.fillStyle = 'rgba(85,112,127,0.9)';
    ctx.font = '9px ui-monospace, monospace';
    ctx.textAlign = 'center';
    for (const t of ticks) {
      const x = Math.round(this._timeToX(t.ms)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, plotH); ctx.stroke();
      ctx.fillText(t.label, clamp(x, 18, w - 18), h - 3);
    }

    // Stacked bars (fixed order, 1px gaps between bars and segments).
    const n = this.buckets.length;
    if (n) {
      const bw = Math.max(1, w / n - 1);
      let peak = 1;
      for (const b of this.buckets) {
        peak = Math.max(peak, ORDER.reduce(
          (s, k) => s + (this.enabled[k] ? (b[k] || 0) : 0), 0));
      }
      this.buckets.forEach((b, i) => {
        const x = (i / n) * w + 0.5;
        let y = plotH;
        for (const k of ORDER) {
          if (!this.enabled[k]) continue;
          const v = b[k] || 0;
          if (!v) continue;
          const bh = Math.max(1, (v / peak) * (plotH - 6));
          y -= bh;
          ctx.fillStyle = TONES[k];
          ctx.fillRect(x, y, bw, bh);
          y -= 1; // surface gap between stacked segments
        }
      });
      // Peak annotation (right-aligned, muted ink).
      ctx.fillStyle = 'rgba(201,215,228,0.55)';
      ctx.textAlign = 'right';
      ctx.font = '9px ui-monospace, monospace';
      ctx.fillText(`peak ${peak}`, w - 4, 10);
    }

    // Selection overlay + bracket handles.
    if (this.selection) {
      const x1 = this._timeToX(this.selection.a);
      const x2 = this._timeToX(this.selection.b);
      ctx.fillStyle = 'rgba(255,179,71,0.13)';
      ctx.fillRect(x1, 0, x2 - x1, plotH);
      ctx.strokeStyle = SELECT;
      ctx.lineWidth = 1.5;
      for (const x of [x1, x2]) {
        ctx.beginPath();
        ctx.moveTo(x + (x === x1 ? 4 : -4), 2);
        ctx.lineTo(x, 2); ctx.lineTo(x, plotH - 2);
        ctx.lineTo(x + (x === x1 ? 4 : -4), plotH - 2);
        ctx.stroke();
      }
    }

    // Playhead.
    if (this.playhead !== null && this.playhead >= this.scope.start) {
      const x = Math.round(this._timeToX(this.playhead)) + 0.5;
      ctx.strokeStyle = SELECT;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, plotH); ctx.stroke();
      ctx.fillStyle = SELECT;
      ctx.beginPath();
      ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6);
      ctx.closePath(); ctx.fill();
    }

    // Hover crosshair.
    if (this._hoverX !== null && !this._drag) {
      const x = Math.round(this._hoverX) + 0.5;
      ctx.strokeStyle = 'rgba(201,215,228,0.35)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, plotH); ctx.stroke();
    }
  }

  _ticks() {
    const span = this.scope.end - this.scope.start;
    const target = Math.max(3, Math.min(7, Math.floor(this.canvas.clientWidth / 110)));
    const steps = [60, 300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600,
      86400, 2 * 86400, 7 * 86400].map((s) => s * 1000);
    const step = steps.find((s) => span / s <= target) || steps[steps.length - 1];
    const out = [];
    let t = Math.ceil(this.scope.start / step) * step;
    for (; t <= this.scope.end; t += step) {
      const d = new Date(t);
      const label = step >= 86400000
        ? d.toLocaleDateString([], { month: 'short', day: 'numeric' })
        : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      out.push({ ms: t, label });
    }
    return out;
  }

  _renderTooltip(e) {
    if (this._hoverX === null || !this.scope) return;
    const b = this._bucketAt(this._hoverX);
    const tt = this.tooltip;
    if (!b) { tt.style.display = 'none'; return; }
    tt.textContent = '';
    tt.appendChild(el('div', 'tl-tt-time',
      `${fmtClock(b.t)} – ${fmtClock(b.t + this.stepMs)}`));
    const rows = [['honeypot', 'Honeypot'], ['probes', 'Probes'], ['bans', 'Bans']];
    for (const [k, label] of rows) {
      if (!this.enabled[k]) continue;
      const row = el('div', 'tl-tt-row');
      const chip = el('span', 'tl-tt-chip');
      chip.style.background = TONES[k];
      row.append(chip, el('span', null, `${label} ${b[k] || 0}`));
      tt.appendChild(row);
    }
    tt.style.display = 'block';
    const rect = this.canvas.getBoundingClientRect();
    const x = clamp(e.clientX - rect.left + 12, 0, rect.width - 130);
    tt.style.left = `${x}px`;
  }
}
