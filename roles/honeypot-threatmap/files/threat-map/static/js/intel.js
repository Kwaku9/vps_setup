// INTEL modal — renders Grafana panels to PNG via the backend proxy.
// Renders on this VPS take ~40s, so the UX is explicitly asynchronous:
// elapsed timer, cancel, and a client cache per (panel, minute-range).
import { el, fmtSpan } from './util.js';

const PANELS = [
  { key: 'map', label: 'THREAT MAP' },
  { key: 'countries', label: 'TOP COUNTRIES' },
  { key: 'table', label: 'EVENT TABLE' },
];

export class Intel {
  constructor(getRange) {
    this.getRange = getRange;          // () => {from_ms, to_ms, label}
    this.modal = document.getElementById('intel-modal');
    this.body = document.getElementById('intel-body');
    this.rangeEl = document.getElementById('intel-range');
    this.tabsEl = document.getElementById('intel-tabs');
    this.cache = new Map();
    this.abort = null;
    this._buildTabs();
    document.getElementById('intel-close').addEventListener('click', () => this.close());
    this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.modal.classList.contains('open')) this.close();
    });
  }

  _buildTabs() {
    for (const p of PANELS) {
      const b = el('button', 'intel-tab', p.label);
      b.addEventListener('click', () => this.load(p.key));
      this.tabsEl.appendChild(b);
    }
  }

  open() {
    this.modal.classList.add('open');
    const r = this.getRange();
    this.rangeEl.textContent = fmtSpan(r.from_ms, r.to_ms);
    this.load('map');
  }

  close() {
    this.modal.classList.remove('open');
    if (this.abort) this.abort.abort();
  }

  async load(panelKey) {
    for (const b of this.tabsEl.children) {
      b.classList.toggle('active', b.textContent ===
        PANELS.find((p) => p.key === panelKey)?.label);
    }
    const r = this.getRange();
    const key = `${panelKey}:${Math.floor(r.from_ms / 60000)}:${Math.floor(r.to_ms / 60000)}`;
    if (this.cache.has(key)) {
      this._showImage(this.cache.get(key));
      return;
    }

    if (this.abort) this.abort.abort();
    this.abort = new AbortController();
    this.body.textContent = '';
    const wait = el('div', 'intel-wait');
    wait.append(el('div', 'intel-spinner'),
      el('div', 'intel-wait-label', 'RENDERING — the VPS renderer takes ~40s'),
      el('div', 'intel-elapsed', '0s'));
    this.body.appendChild(wait);
    const started = Date.now();
    const tick = setInterval(() => {
      const s = wait.querySelector('.intel-elapsed');
      if (s) s.textContent = `${Math.round((Date.now() - started) / 1000)}s`;
    }, 1000);

    try {
      const resp = await fetch('/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ panel: panelKey, from_ms: r.from_ms, to_ms: r.to_ms }),
        signal: this.abort.signal,
      });
      clearInterval(tick);
      if (!resp.ok) {
        const detail = (await resp.json().catch(() => ({})))?.detail || resp.status;
        this._showError(`Render failed: ${detail}`);
        return;
      }
      const data = await resp.json();
      if (!data.png_base64) { this._showError('Renderer returned no image'); return; }
      this.cache.set(key, data);
      if (this.cache.size > 12) this.cache.delete(this.cache.keys().next().value);
      this._showImage(data);
    } catch (err) {
      clearInterval(tick);
      if (err.name !== 'AbortError') this._showError('Render engine unreachable');
    }
  }

  _showImage(data) {
    this.body.textContent = '';
    const img = new Image();
    img.className = 'intel-img';
    img.alt = data.label || 'Grafana panel';
    img.src = `data:image/png;base64,${data.png_base64}`;
    this.body.appendChild(img);
    const bar = el('div', 'intel-actions');
    const dl = el('a', 'intel-download', 'SAVE PNG');
    dl.href = img.src;
    dl.download = `${(data.label || 'panel').toLowerCase().replace(/\s+/g, '-')}.png`;
    bar.appendChild(dl);
    if (data.cached) bar.appendChild(el('span', 'intel-cached', 'cached'));
    this.body.appendChild(bar);
  }

  _showError(msg) {
    this.body.textContent = '';
    const box = el('div', 'intel-error');
    box.append(el('div', null, msg),
      el('div', 'intel-error-hint',
        'The Grafana image renderer may be busy or disabled — retry in a minute.'));
    this.body.appendChild(box);
  }
}
