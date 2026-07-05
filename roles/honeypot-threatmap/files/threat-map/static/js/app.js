// Orchestrator: LIVE mode (WS + paced dispatch) and REPLAY mode (virtual
// clock over /api/history), transport + timeline wiring, audio controls.
import { GlobeView } from './globe-view.js';
import { Timeline } from './timeline.js';
import { Feed, StatsPanels } from './feed.js';
import { Intel } from './intel.js';
import { audio } from './audio.js';
import { sourceMeta, fmtSpan, store, clamp } from './util.js';

const PRESETS = [
  { label: '1H', ms: 3_600_000 },
  { label: '6H', ms: 6 * 3_600_000 },
  { label: '24H', ms: 24 * 3_600_000 },
  { label: '7D', ms: 7 * 86_400_000 },
  { label: '14D', ms: 14 * 86_400_000 },
  { label: '60D', ms: 60 * 86_400_000, note: 'bans only beyond 14d' },
];
const SPEEDS = [1, 10, 60, 300];

const $ = (id) => document.getElementById(id);

class App {
  constructor() {
    this.cfg = null;
    this.mode = 'live';                 // 'live' | 'replay'
    this.enabled = store.get('tm_sources', { honeypot: true, probes: true, bans: true });
    this.scopeMs = store.get('tm_scope', 24 * 3_600_000);
    this.globe = new GlobeView($('globe-container'));
    this.feed = new Feed();
    this.stats = new StatsPanels();
    this.timeline = null;
    this.intel = null;
    this.ws = null;
    this.reconnectDelay = 2000;
    this.liveQueue = [];
    this.replay = null;                 // {events, idx, vt, speed, playing, sel, raf, lastReal}
    this.speed = 10;
  }

  async boot() {
    try {
      this.cfg = await (await fetch('/api/config')).json();
    } catch {
      this.cfg = { target: { lat: 40.7128, lon: -74.006 }, reports_enabled: false };
    }
    this.globe.init(this.cfg.target);

    this.timeline = new Timeline($('timeline-canvas'), $('timeline-tooltip'), {
      onSelect: (sel) => this._onSelect(sel),
      onSeek: (t) => this._onSeek(t),
    });
    this.timeline.setEnabled(this.enabled);

    this.intel = new Intel(() => this._intelRange());
    if (!this.cfg.reports_enabled) $('btn-intel').style.display = 'none';

    this._wireTransport();
    this._wireAudio();
    this._wireLegend();

    await this._loadRecent();
    this._pollStats();
    await this._refreshHistogram();
    setInterval(() => { if (this.mode === 'live') this._refreshHistogram(); }, 60_000);
    setInterval(() => this._drainLive(), 220);
    this._connectWS();
  }

  // ---------------------------------------------------------------- live ---
  _connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws.onopen = () => {
      this.reconnectDelay = 2000;
      this._status();
    };
    this.ws.onmessage = (msg) => {
      try {
        const { event, data } = JSON.parse(msg.data);
        if (['attack', 'probe', 'ban'].includes(event)) this.liveQueue.push(data);
      } catch { /* malformed frame */ }
    };
    this.ws.onclose = () => {
      this._status('offline');
      setTimeout(() => this._connectWS(), this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 30_000);
    };
  }

  _drainLive() {
    if (this.mode !== 'live' || !this.liveQueue.length) return;
    // Smooth pacing: one event per tick; on floods, flush the backlog visually
    // capped (arc cooldowns absorb it) with a single swarm sound.
    let burst = false;
    if (this.liveQueue.length > 30) {
      burst = true;
      audio.event('_swarm');
    }
    const n = burst ? this.liveQueue.length : 1;
    for (let i = 0; i < n; i++) {
      const evt = this.liveQueue.shift();
      if (!evt) break;
      if (!this.enabled[sourceMeta(evt).key]) continue;
      this.globe.spawnEvent(evt, 1);
      this.feed.add(evt);
      if (!burst) audio.event(evt.attack_type);
    }
  }

  async _loadRecent() {
    try {
      const events = await (await fetch('/api/recent?minutes=60&limit=50')).json();
      for (const e of events) {
        if (!this.enabled[sourceMeta(e).key]) continue;
        this.feed.add(e);           // silent backfill — no sounds
      }
      for (const e of events.slice(-8)) {
        if (this.enabled[sourceMeta(e).key]) this.globe.spawnEvent(e, 1);
      }
    } catch { /* backend warming up */ }
  }

  async _pollStats() {
    try {
      const s = await (await fetch('/api/stats')).json();
      if (this.mode === 'live') this.stats.render(s);
      this._lastStats = s;
    } catch { /* retry next cycle */ }
    setTimeout(() => this._pollStats(), 30_000);
  }

  async _refreshHistogram(scope) {
    const end = Date.now();
    const sc = scope || { start: end - this.scopeMs, end };
    try {
      const r = await fetch(`/api/histogram?start=${sc.start}&end=${sc.end}&buckets=180`);
      if (r.ok) this.timeline.setData(sc, await r.json());
    } catch { /* keep last histogram */ }
  }

  // -------------------------------------------------------------- replay ---
  _onSelect(sel) {
    if (this.mode === 'replay') this._stopReplay(false);
    $('btn-play').disabled = !sel;
    $('replay-range').textContent = sel ? fmtSpan(sel.a, sel.b) : '';
  }

  async _startReplay() {
    const sel = this.timeline.selection
      || { a: this.timeline.scope.start, b: this.timeline.scope.end };
    const sources = Object.entries(this.enabled)
      .filter(([, v]) => v).map(([k]) => k).join(',');
    this._status('loading');
    let events = [];
    try {
      const r = await fetch(`/api/history?start=${sel.a}&end=${sel.b}`
        + `&limit=3000&sources=${encodeURIComponent(sources)}`);
      if (!r.ok) throw new Error();
      const data = await r.json();
      events = data.events || [];
      $('replay-range').textContent =
        `${fmtSpan(sel.a, sel.b)} · ${events.length} events`
        + (data.meta?.truncated ? ' (sampled)' : '')
        + (data.meta?.loki_clipped ? ' · honeypot/probes >14d not retained' : '');
    } catch {
      this._status();
      $('replay-range').textContent = 'history fetch failed';
      return;
    }
    this.mode = 'replay';
    this.feed.setReplayMode(true);
    this.globe.clear();
    this.timeline.seekMode = true;
    this.timeline.setSelection(sel);
    this.stats.renderReplay(events, sel.b - sel.a);
    this.replay = {
      events, sel, idx: 0, vt: sel.a, speed: this.speed,
      playing: true, lastReal: performance.now(), raf: null,
    };
    this._status();
    this._tickReplay();
  }

  _tickReplay() {
    if (!this.replay) return;
    const r = this.replay;
    if (r.playing) {
      const now = performance.now();
      r.vt = Math.min(r.vt + (now - r.lastReal) * r.speed, r.sel.b);
      r.lastReal = now;
      while (r.idx < r.events.length && r.events[r.idx].ts_ms <= r.vt) {
        const evt = r.events[r.idx++];
        if (this.enabled[sourceMeta(evt).key]) {
          this.globe.spawnEvent(evt, r.speed);
          this.feed.add(evt);
          audio.event(evt.attack_type);
        }
      }
      this.timeline.setPlayhead(r.vt);
      $('replay-clock').textContent = new Date(r.vt).toLocaleString([], { hour12: false });
      if (r.vt >= r.sel.b) {
        r.playing = false;
        this._status('ended');
        this._playBtn();
      }
    }
    r.raf = requestAnimationFrame(() => this._tickReplay());
  }

  _onSeek(t) {
    const r = this.replay;
    if (!r) return;
    r.vt = clamp(t, r.sel.a, r.sel.b);
    r.idx = r.events.findIndex((e) => e.ts_ms > r.vt);
    if (r.idx < 0) r.idx = r.events.length;
    r.lastReal = performance.now();
    this.globe.clear();
    this.feed.clear();
    this.timeline.setPlayhead(r.vt);
    if (!r.playing) { r.playing = true; this._status(); this._playBtn(); }
  }

  _togglePause() {
    const r = this.replay;
    if (!r) { this._startReplay(); return; }
    if (r.vt >= r.sel.b) {           // replay ended → restart
      r.vt = r.sel.a; r.idx = 0;
      this.globe.clear(); this.feed.clear();
    }
    r.playing = !r.playing;
    r.lastReal = performance.now();
    this._status(r.playing ? undefined : 'paused');
    this._playBtn();
  }

  _stopReplay(clearSel = true) {
    if (this.replay?.raf) cancelAnimationFrame(this.replay.raf);
    this.replay = null;
    this.mode = 'live';
    this.timeline.seekMode = false;
    this.timeline.setPlayhead(null);
    if (clearSel) {
      this.timeline.setSelection(null);
      $('replay-range').textContent = '';
      $('btn-play').disabled = true;
    }
    this.feed.setReplayMode(false);
    this.globe.clear();
    $('replay-clock').textContent = '';
    if (this._lastStats) this.stats.render(this._lastStats);
    this._loadRecent();
    this._refreshHistogram();
    this._status();
    this._playBtn();
  }

  // ------------------------------------------------------------- wiring ---
  _wireTransport() {
    const presetsEl = $('range-presets');
    for (const p of PRESETS) {
      const b = document.createElement('button');
      b.className = 'chip' + (p.ms === this.scopeMs ? ' active' : '');
      b.textContent = p.label;
      if (p.note) b.title = p.note;
      b.addEventListener('click', () => {
        this.scopeMs = p.ms;
        store.set('tm_scope', p.ms);
        for (const c of presetsEl.children) c.classList.toggle('active', c === b);
        this._refreshHistogram();
        audio.ui();
      });
      presetsEl.appendChild(b);
    }

    const speedsEl = $('speed-buttons');
    for (const s of SPEEDS) {
      const b = document.createElement('button');
      b.className = 'chip' + (s === this.speed ? ' active' : '');
      b.textContent = `${s}×`;
      b.addEventListener('click', () => {
        this.speed = s;
        if (this.replay) { this.replay.speed = s; this.replay.lastReal = performance.now(); }
        for (const c of speedsEl.children) c.classList.toggle('active', c === b);
        audio.ui();
      });
      speedsEl.appendChild(b);
    }

    $('btn-play').addEventListener('click', () => { audio.ui(); this._togglePause(); });
    $('btn-live').addEventListener('click', () => { audio.ui(); this._stopReplay(); });
    $('btn-intel').addEventListener('click', () => { audio.ui(); this.intel.open(); });
    $('btn-play').disabled = true;
  }

  _wireLegend() {
    for (const key of ['honeypot', 'probes', 'bans']) {
      const b = $(`legend-${key}`);
      b.classList.toggle('off', !this.enabled[key]);
      b.addEventListener('click', () => {
        this.enabled[key] = !this.enabled[key];
        store.set('tm_sources', this.enabled);
        b.classList.toggle('off', !this.enabled[key]);
        this.timeline.setEnabled(this.enabled);
        audio.ui();
      });
    }
  }

  _wireAudio() {
    const armBtn = $('btn-audio-arm');
    const panel = $('audio-panel');
    const vol = $('audio-vol');
    const muteBtn = $('btn-audio-mute');
    const ambBtn = $('btn-ambient');

    vol.value = String(audio.volume);
    muteBtn.classList.toggle('active', !audio.muted);
    ambBtn.classList.toggle('active', audio.ambientOn);

    armBtn.addEventListener('click', () => {
      if (audio.arm()) {
        armBtn.style.display = 'none';
        panel.style.display = 'flex';
      }
    });
    vol.addEventListener('input', () => audio.setVolume(parseFloat(vol.value)));
    muteBtn.addEventListener('click', () => {
      audio.setMuted(!audio.muted);
      muteBtn.classList.toggle('active', !audio.muted);
      muteBtn.textContent = audio.muted ? 'MUTED' : 'SFX';
    });
    ambBtn.addEventListener('click', () => {
      ambBtn.classList.toggle('active', audio.toggleAmbient());
    });
    document.addEventListener('ambient-unavailable', () => {
      ambBtn.style.display = 'none';
    });
  }

  _playBtn() {
    const r = this.replay;
    $('btn-play').textContent = r && r.playing ? '⏸ PAUSE' : '▶ PLAY';
  }

  _status(state) {
    const dot = $('status-dot');
    const txt = $('status-text');
    dot.className = 'dot';
    if (state === 'offline') { dot.classList.add('red'); txt.textContent = 'Reconnecting…'; return; }
    if (state === 'loading') { dot.classList.add('amber'); txt.textContent = 'Loading history…'; return; }
    if (this.mode === 'replay') {
      dot.classList.add('amber');
      txt.textContent = state === 'ended' ? `REPLAY ended`
        : state === 'paused' ? `REPLAY paused`
          : `REPLAY ${this.replay?.speed ?? this.speed}×`;
      return;
    }
    txt.textContent = 'LIVE';
  }
}

const app = new App();
app.boot();
