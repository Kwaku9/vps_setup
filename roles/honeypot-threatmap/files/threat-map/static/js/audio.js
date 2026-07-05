// WebAudio SFX engine — everything is synthesized (zero asset weight) except
// the optional ambient bed, which streams /static/audio/ambient-ops.ogg when
// that file exists. Browsers require a user gesture before audio: the ARM
// button calls arm().
import { store, clamp } from './util.js';

// ============================================================================
// SOUND DESIGN MAP — the tweakable block.
// Each attack_type maps to a voice recipe. Fields:
//   kind : 'blip' (osc ping) | 'zap' (freq sweep) | 'tick' (filtered noise)
//        | 'thud' (sub drop + noise body)
//   f0/f1: start/end frequency (Hz)   dur: seconds   vol: 0..1 relative
//   wave : oscillator shape for blip/zap
// ============================================================================
const SOUND_MAP = {
  wordpress_probe:  { kind: 'blip', wave: 'sine',     f0: 740, dur: 0.07, vol: 0.45 },
  cms_probe:        { kind: 'blip', wave: 'sine',     f0: 700, dur: 0.07, vol: 0.45 },
  generic_probe:    { kind: 'blip', wave: 'sine',     f0: 880, dur: 0.05, vol: 0.35 },
  api_probe:        { kind: 'blip', wave: 'triangle', f0: 980, dur: 0.05, vol: 0.35 },
  admin_probe:      { kind: 'blip', wave: 'triangle', f0: 660, dur: 0.08, vol: 0.5  },
  env_probe:        { kind: 'blip', wave: 'triangle', f0: 620, dur: 0.09, vol: 0.5, double: true },
  git_probe:        { kind: 'blip', wave: 'triangle', f0: 580, dur: 0.09, vol: 0.5, double: true },
  db_probe:         { kind: 'blip', wave: 'triangle', f0: 540, dur: 0.09, vol: 0.5, double: true },
  backup_probe:     { kind: 'blip', wave: 'triangle', f0: 500, dur: 0.09, vol: 0.5, double: true },
  credential_probe: { kind: 'zap',  wave: 'square',   f0: 300, f1: 150, dur: 0.11, vol: 0.5 },
  shell_probe:      { kind: 'zap',  wave: 'square',   f0: 240, f1: 90,  dur: 0.13, vol: 0.6 },
  path_traversal:   { kind: 'zap',  wave: 'sawtooth', f0: 260, f1: 110, dur: 0.12, vol: 0.55 },
  recon:            { kind: 'tick', f0: 3200, dur: 0.03, vol: 0.3 },
  auth_failure:     { kind: 'tick', f0: 1600, dur: 0.05, vol: 0.45 },
  access_denied:    { kind: 'tick', f0: 1200, dur: 0.05, vol: 0.45 },
  rate_limited:     { kind: 'tick', f0: 800,  dur: 0.04, vol: 0.35 },
  banned:           { kind: 'thud', f0: 120,  f1: 38, dur: 0.4, vol: 1.0 },
  _swarm:           { kind: 'sweep', f0: 400, f1: 2400, dur: 0.5, vol: 0.5 },
  _ui:              { kind: 'tick', f0: 2400, dur: 0.02, vol: 0.25 },
};

const MAX_VOICES_PER_SEC = 6;   // beyond this, events coalesce into one swarm

class AudioEngine {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.armed = false;
    this.muted = store.get('tm_mute', false);
    this.volume = store.get('tm_vol', 0.22);
    this.ambientOn = store.get('tm_ambient', false);
    this.ambientEl = null;
    this.ambientAvailable = null;   // null = unprobed
    this._voiceWindow = [];
    this._lastSwarm = 0;
    this._noiseBuf = null;
  }

  // Must be called from a click handler (browser autoplay policy).
  arm() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      this.ctx = new AC();
      const comp = this.ctx.createDynamicsCompressor();
      comp.threshold.value = -18;
      comp.ratio.value = 6;
      comp.connect(this.ctx.destination);
      this.master = this.ctx.createGain();
      this.master.connect(comp);
      this._applyGain();
    }
    this.ctx.resume();
    this.armed = true;
    if (this.ambientOn) this._startAmbient();
    this.play('_ui');
    return true;
  }

  setVolume(v) {
    this.volume = clamp(v, 0, 1);
    store.set('tm_vol', this.volume);
    this._applyGain();
    if (this.ambientEl) this.ambientEl.volume = this._ambientVol();
  }

  setMuted(m) {
    this.muted = !!m;
    store.set('tm_mute', this.muted);
    this._applyGain();
    if (this.ambientEl) this.ambientEl.muted = this.muted;
  }

  toggleAmbient() {
    this.ambientOn = !this.ambientOn;
    store.set('tm_ambient', this.ambientOn);
    if (this.ambientOn && this.armed) this._startAmbient();
    if (!this.ambientOn && this.ambientEl) this.ambientEl.pause();
    return this.ambientOn;
  }

  _ambientVol() { return clamp(this.volume * 0.55, 0, 0.4); }

  _startAmbient() {
    if (this.ambientAvailable === false) return;
    if (!this.ambientEl) {
      this.ambientEl = new Audio('/static/audio/ambient-ops.ogg');
      this.ambientEl.loop = true;
      this.ambientEl.addEventListener('error', () => {
        this.ambientAvailable = false;
        document.dispatchEvent(new CustomEvent('ambient-unavailable'));
      });
    }
    this.ambientEl.volume = this._ambientVol();
    this.ambientEl.muted = this.muted;
    this.ambientEl.play().then(() => { this.ambientAvailable = true; })
      .catch(() => { /* not armed yet or missing file */ });
  }

  _applyGain() {
    if (this.master) {
      this.master.gain.value = this.muted ? 0 : this.volume;
    }
  }

  // Rate-limited event sound. Bans always voice; floods become one swarm/sec.
  event(attackType) {
    if (!this._ready()) return;
    const now = performance.now();
    this._voiceWindow = this._voiceWindow.filter((t) => now - t < 1000);
    if (attackType !== 'banned' && this._voiceWindow.length >= MAX_VOICES_PER_SEC) {
      if (now - this._lastSwarm > 1000) {
        this._lastSwarm = now;
        this.play('_swarm');
      }
      return;
    }
    this._voiceWindow.push(now);
    this.play(attackType);
  }

  ui() { this.play('_ui'); }

  _ready() {
    return this.armed && !this.muted && this.ctx && this.ctx.state === 'running'
      && !document.hidden;
  }

  play(type) {
    if (!this._ready()) return;
    const spec = SOUND_MAP[type] || SOUND_MAP.generic_probe;
    const t0 = this.ctx.currentTime;
    try {
      if (spec.kind === 'blip' || spec.kind === 'zap') {
        this._osc(spec, t0);
        if (spec.double) this._osc({ ...spec, f0: spec.f0 * 1.335 }, t0 + spec.dur + 0.03);
      } else if (spec.kind === 'tick') {
        this._noise(spec, t0, 'highpass');
      } else if (spec.kind === 'sweep') {
        this._sweepNoise(spec, t0);
      } else if (spec.kind === 'thud') {
        this._osc({ ...spec, wave: 'sine', kind: 'zap' }, t0);           // sub drop
        this._noise({ ...spec, f0: 200, dur: 0.12, vol: spec.vol * 0.4 }, t0, 'lowpass');
      }
    } catch { /* never let audio break the app */ }
  }

  _env(gainNode, t0, dur, vol) {
    const g = gainNode.gain;
    g.setValueAtTime(0.0001, t0);
    g.exponentialRampToValueAtTime(Math.max(vol, 0.001), t0 + 0.008);
    g.exponentialRampToValueAtTime(0.0001, t0 + dur);
  }

  _osc(spec, t0) {
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.type = spec.wave || 'sine';
    osc.frequency.setValueAtTime(spec.f0, t0);
    if (spec.f1) osc.frequency.exponentialRampToValueAtTime(spec.f1, t0 + spec.dur);
    this._env(g, t0, spec.dur, spec.vol * 0.6);
    osc.connect(g).connect(this.master);
    osc.start(t0);
    osc.stop(t0 + spec.dur + 0.05);
  }

  _noiseBuffer() {
    if (!this._noiseBuf) {
      const len = this.ctx.sampleRate * 0.5;
      this._noiseBuf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const d = this._noiseBuf.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    }
    return this._noiseBuf;
  }

  _noise(spec, t0, filterType) {
    const src = this.ctx.createBufferSource();
    src.buffer = this._noiseBuffer();
    const f = this.ctx.createBiquadFilter();
    f.type = filterType;
    f.frequency.value = spec.f0;
    const g = this.ctx.createGain();
    this._env(g, t0, spec.dur, spec.vol * 0.5);
    src.connect(f).connect(g).connect(this.master);
    src.start(t0);
    src.stop(t0 + spec.dur + 0.05);
  }

  _sweepNoise(spec, t0) {
    const src = this.ctx.createBufferSource();
    src.buffer = this._noiseBuffer();
    src.loop = true;
    const f = this.ctx.createBiquadFilter();
    f.type = 'bandpass';
    f.Q.value = 8;
    f.frequency.setValueAtTime(spec.f0, t0);
    f.frequency.exponentialRampToValueAtTime(spec.f1, t0 + spec.dur);
    const g = this.ctx.createGain();
    this._env(g, t0, spec.dur, spec.vol * 0.4);
    src.connect(f).connect(g).connect(this.master);
    src.start(t0);
    src.stop(t0 + spec.dur + 0.1);
  }
}

export const audio = new AudioEngine();
