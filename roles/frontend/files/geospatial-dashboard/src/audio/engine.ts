/**
 * WorldView audio — spy-ops soundscape.
 * All SFX are WebAudio-synthesized (zero assets); the ambient bed streams
 * /audio/ambient-spy.ogg when present. Browsers demand a user gesture before
 * audio, so installAutoArm() arms the context on the first pointerdown.
 */

type VoiceKind = 'click' | 'toggle' | 'flyto' | 'launch' | 'impact' | 'alert';

const store = {
  get<T>(k: string, fallback: T): T {
    try {
      const v = localStorage.getItem(k);
      return v === null ? fallback : (JSON.parse(v) as T);
    } catch { return fallback; }
  },
  set(k: string, v: unknown): void {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ }
  },
};

const MAX_VOICES_PER_SEC = 8;

class WorldAudio {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private noiseBuf: AudioBuffer | null = null;
  private ambient: { bus: GainNode; stop: () => void } | null = null;
  private voiceWindow: number[] = [];
  public armed = false;
  public muted = store.get('wv_mute', false);
  public volume = store.get('wv_vol', 0.18);
  public ambientOn = store.get('wv_ambient', true);

  /** Arm on the first user gesture (autoplay policy). Idempotent. */
  installAutoArm(): void {
    const arm = () => { this.arm(); };
    window.addEventListener('pointerdown', arm, { once: true });
    window.addEventListener('keydown', arm, { once: true });
  }

  arm(): boolean {
    if (!this.ctx) {
      const AC = window.AudioContext
        || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) return false;
      this.ctx = new AC();
      const comp = this.ctx.createDynamicsCompressor();
      comp.threshold.value = -20;
      comp.ratio.value = 6;
      comp.connect(this.ctx.destination);
      this.master = this.ctx.createGain();
      this.master.connect(comp);
      this.applyGain();
    }
    void this.ctx.resume();
    this.armed = true;
    if (this.ambientOn) this.startAmbient();
    return true;
  }

  setVolume(v: number): void {
    this.volume = Math.min(0.6, Math.max(0, v));
    store.set('wv_vol', this.volume);
    this.applyGain();
    if (this.ambient) this.ambient.bus.gain.value = this.ambientVol();
  }

  setMuted(m: boolean): void {
    this.muted = m;
    store.set('wv_mute', m);
    this.applyGain();
  }

  toggleAmbient(): boolean {
    this.ambientOn = !this.ambientOn;
    store.set('wv_ambient', this.ambientOn);
    if (this.ambientOn && this.armed) this.startAmbient();
    else this.stopAmbient();
    return this.ambientOn;
  }

  // ── SFX entry points ──────────────────────────────────────────────────
  ui(): void { this.play('click'); }
  layerToggle(): void { this.play('toggle'); }
  flyTo(): void { this.play('flyto'); }
  threatLaunch(): void { this.playLimited('launch'); }
  threatImpact(): void { this.playLimited('impact'); }
  alert(): void { this.play('alert'); }

  // ── internals ─────────────────────────────────────────────────────────
  private ambientVol(): number { return Math.min(0.3, this.volume * 0.55); }

  // Procedural cinematic spy bed: a low minor-triad drone (A1/C2/E2) with a
  // slow detune shimmer, an airy filtered-noise layer, and a distant sonar
  // ping every ~14s. Synthesized — no asset, no CSP media dependency.
  private startAmbient(): void {
    if (!this.ctx || !this.master || this.ambient) return;
    const ctx = this.ctx;
    const bus = ctx.createGain();
    bus.gain.value = this.ambientVol();
    bus.connect(this.master);

    const oscs: OscillatorNode[] = [];
    const noises: AudioBufferSourceNode[] = [];
    const drone = (freq: number, level: number, detuneLfo = false) => {
      const o = ctx.createOscillator();
      o.type = 'sawtooth';
      o.frequency.value = freq;
      const lp = ctx.createBiquadFilter();
      lp.type = 'lowpass';
      lp.frequency.value = 240;
      const g = ctx.createGain();
      g.gain.value = level;
      o.connect(lp).connect(g).connect(bus);
      o.start();
      oscs.push(o);
      if (detuneLfo) {
        const lfo = ctx.createOscillator();
        const lg = ctx.createGain();
        lfo.frequency.value = 0.04;
        lg.gain.value = 2;
        lfo.connect(lg).connect(o.frequency);
        lfo.start();
        oscs.push(lfo);
      }
    };
    drone(55, 0.14);          // A1
    drone(65.4, 0.09, true);  // C2
    drone(82.4, 0.08, true);  // E2

    const noise = ctx.createBufferSource();
    noise.buffer = this.noiseBuffer();
    noise.loop = true;
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 600;
    bp.Q.value = 0.6;
    const ng = ctx.createGain();
    ng.gain.value = 0.03;
    const swell = ctx.createOscillator();
    const sg = ctx.createGain();
    swell.frequency.value = 0.025;
    sg.gain.value = 0.025;
    swell.connect(sg).connect(ng.gain);
    noise.connect(bp).connect(ng).connect(bus);
    noise.start();
    swell.start();
    oscs.push(swell);
    noises.push(noise);

    const ping = window.setInterval(() => {
      if (!this.ctx || document.hidden) return;
      const t = ctx.currentTime;
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = 990;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.04, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 1.8);
      o.connect(g).connect(bus);
      o.start(t);
      o.stop(t + 1.9);
    }, 14000);

    this.ambient = {
      bus,
      stop: () => {
        clearInterval(ping);
        try { oscs.forEach((o) => o.stop()); noises.forEach((n) => n.stop()); }
        catch { /* already stopped */ }
        bus.disconnect();
      },
    };
  }

  private stopAmbient(): void {
    if (this.ambient) { this.ambient.stop(); this.ambient = null; }
  }

  private applyGain(): void {
    if (this.master) this.master.gain.value = this.muted ? 0 : this.volume;
  }

  private ready(): boolean {
    return this.armed && !this.muted && !!this.ctx
      && this.ctx.state === 'running' && !document.hidden;
  }

  private playLimited(kind: VoiceKind): void {
    const now = performance.now();
    this.voiceWindow = this.voiceWindow.filter((t) => now - t < 1000);
    if (this.voiceWindow.length >= MAX_VOICES_PER_SEC) return;
    this.voiceWindow.push(now);
    this.play(kind);
  }

  private play(kind: VoiceKind): void {
    if (!this.ready() || !this.ctx || !this.master) return;
    const t0 = this.ctx.currentTime;
    try {
      switch (kind) {
        case 'click':
          this.noise(t0, 2600, 0.02, 0.18, 'highpass'); break;
        case 'toggle':
          this.osc(t0, 'triangle', 840, 0, 0.05, 0.25); break;
        case 'flyto':
          this.sweepNoise(t0, 300, 1800, 0.5, 0.28); break;
        case 'launch':   // soft sonar ping with a fifth echo
          this.osc(t0, 'sine', 620, 0, 0.09, 0.3);
          this.osc(t0 + 0.16, 'sine', 930, 0, 0.06, 0.12);
          break;
        case 'impact':
          this.osc(t0, 'sine', 95, 42, 0.3, 0.5);
          this.noise(t0, 180, 0.1, 0.2, 'lowpass');
          break;
        case 'alert':
          this.osc(t0, 'square', 660, 0, 0.07, 0.22);
          this.osc(t0 + 0.1, 'square', 550, 0, 0.07, 0.22);
          break;
      }
    } catch { /* audio must never break the globe */ }
  }

  private env(g: GainNode, t0: number, dur: number, vol: number): void {
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(Math.max(vol, 0.001), t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  }

  private osc(t0: number, wave: OscillatorType, f0: number, f1: number,
    dur: number, vol: number): void {
    if (!this.ctx || !this.master) return;
    const o = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    o.type = wave;
    o.frequency.setValueAtTime(f0, t0);
    if (f1 > 0) o.frequency.exponentialRampToValueAtTime(f1, t0 + dur);
    this.env(g, t0, dur, vol);
    o.connect(g).connect(this.master);
    o.start(t0);
    o.stop(t0 + dur + 0.05);
  }

  private noiseBuffer(): AudioBuffer {
    if (!this.noiseBuf && this.ctx) {
      const len = this.ctx.sampleRate * 0.5;
      this.noiseBuf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const d = this.noiseBuf.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    }
    return this.noiseBuf as AudioBuffer;
  }

  private noise(t0: number, freq: number, dur: number, vol: number,
    filter: BiquadFilterType): void {
    if (!this.ctx || !this.master) return;
    const src = this.ctx.createBufferSource();
    src.buffer = this.noiseBuffer();
    const f = this.ctx.createBiquadFilter();
    f.type = filter;
    f.frequency.value = freq;
    const g = this.ctx.createGain();
    this.env(g, t0, dur, vol);
    src.connect(f).connect(g).connect(this.master);
    src.start(t0);
    src.stop(t0 + dur + 0.05);
  }

  private sweepNoise(t0: number, f0: number, f1: number, dur: number, vol: number): void {
    if (!this.ctx || !this.master) return;
    const src = this.ctx.createBufferSource();
    src.buffer = this.noiseBuffer();
    src.loop = true;
    const f = this.ctx.createBiquadFilter();
    f.type = 'bandpass';
    f.Q.value = 7;
    f.frequency.setValueAtTime(f0, t0);
    f.frequency.exponentialRampToValueAtTime(f1, t0 + dur);
    const g = this.ctx.createGain();
    this.env(g, t0, dur, vol);
    src.connect(f).connect(g).connect(this.master);
    src.start(t0);
    src.stop(t0 + dur + 0.1);
  }
}

export const worldAudio = new WorldAudio();
