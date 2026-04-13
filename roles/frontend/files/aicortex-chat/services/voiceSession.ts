/**
 * WebSocket protocol handler for Gemini Live via LiteLLM passthrough.
 *
 * Manages the connection to wss://litellm.aicortex.cloud/vertex-ai/live
 * and implements the Vertex AI Multimodal Live wire protocol.
 */

import { VoiceSessionState, DEFAULT_VOICE_CONFIG } from '@/constants/types';
import { tracer, SpanStatusCode } from '@/services/tracing';
import type { Span } from '@opentelemetry/api';

// ── Event system ────────────────────────────────────────────

type Listener<T extends unknown[]> = (...args: T) => void;

interface VoiceSessionEventMap {
  stateChange: [VoiceSessionState];
  audioOutput: [string]; // base64 PCM at 24kHz
  turnComplete: [];
  interrupt: []; // user spoke during Gemini response — clear playback
  error: [Error];
}

// ── VoiceSession ────────────────────────────────────────────

const KEEPALIVE_INTERVAL_MS = 30_000; // 30s to beat Cloudflare's 100s idle timeout

export interface VoiceSessionConfig {
  wsUrl: string;
  token: string;
  voiceName?: string;
}

export class VoiceSession {
  private ws: WebSocket | null = null;
  private state: VoiceSessionState = 'idle';
  private keepaliveTimer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Map<string, Set<Listener<any>>>();
  private config: Required<VoiceSessionConfig>;
  // OTEL: parent span for the entire WebSocket session — opens at connect(),
  // closes at disconnect()/error/close. Per-chunk audio is recorded as span
  // events on this parent (not child spans) to avoid one span per 100ms.
  private sessionSpan: Span | null = null;
  private sessionStartMs = 0;

  constructor(config: VoiceSessionConfig) {
    this.config = {
      wsUrl: config.wsUrl,
      token: config.token,
      voiceName: config.voiceName ?? DEFAULT_VOICE_CONFIG.voiceName,
    };
  }

  getState(): VoiceSessionState {
    return this.state;
  }

  // ── Connection lifecycle ──────────────────────────────────

  connect(): void {
    if (this.ws) {
      this.disconnect();
    }

    this.setState('connecting');

    // Open the parent span for the entire session lifetime.
    this.sessionSpan = tracer.startSpan('voice.session.lifetime', {
      attributes: {
        'voice.model': DEFAULT_VOICE_CONFIG.model,
        'voice.name': this.config.voiceName,
        'voice.endpoint': this.config.wsUrl,
      },
    });
    this.sessionStartMs = Date.now();

    try {
      // Pass scoped voice key as api-key header via RN WebSocket's 3rd arg.
      // RN's WebSocket accepts headers in the options object (non-standard but supported).
      const url = this.config.wsUrl;
      // @ts-ignore — React Native WebSocket supports headers option
      this.ws = new WebSocket(url, undefined, {
        headers: { 'api-key': this.config.token },
      }) as WebSocket;

      // Force ArrayBuffer for binary frames so we can decode synchronously
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = this.handleOpen;
      this.ws.onmessage = this.handleMessage;
      this.ws.onerror = this.handleError;
      this.ws.onclose = this.handleClose;
    } catch (err) {
      this.recordSessionError(err);
      this.endSessionSpan('connect_failed');
      this.setState('error');
      this.emit('error', err instanceof Error ? err : new Error(String(err)));
    }
  }

  disconnect(): void {
    this.stopKeepalive();
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.endSessionSpan('user_disconnect');
    this.setState('closed');
  }

  // ── OTEL helpers ──────────────────────────────────────────

  private endSessionSpan(reason: string): void {
    if (!this.sessionSpan) return;
    const durationMs = Date.now() - this.sessionStartMs;
    this.sessionSpan.setAttributes({
      'voice.session.close_reason': reason,
      'voice.session.duration_ms': durationMs,
      'voice.audio.chunks_sent': this.audioChunksSent,
      'voice.audio.chunks_skipped': this.audioChunksSkipped,
      'voice.audio.chunks_fixed': this.audioChunksFixed,
      'voice.messages_received': this.messagesReceived,
    });
    this.sessionSpan.end();
    this.sessionSpan = null;
  }

  private recordSessionError(err: unknown): void {
    if (!this.sessionSpan) return;
    const error = err instanceof Error ? err : new Error(String(err));
    this.sessionSpan.recordException(error);
    this.sessionSpan.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
  }

  // ── Audio input ───────────────────────────────────────────

  private audioChunksSent = 0;
  private audioChunksSkipped = 0;
  private audioChunksFixed = 0;
  private sourceRate = 16000; // actual recording sample rate (may differ from requested)
  private activityActive = false; // whether we've sent activityStart
  private quietChunks = 0; // consecutive quiet chunks for silence detection
  private muted = false; // when true, audio is not sent and interrupts are suppressed

  // Silence detection: ~1s of quiet at 100ms chunks = 10 chunks
  private static readonly SILENCE_THRESHOLD = 80; // RMS threshold (speech ~200-400, silence ~30)
  private static readonly QUIET_CHUNKS_TO_END = 10;
  // Interruption requires higher energy to avoid false triggers from speaker bleed.
  // In playAndRecord mode, speaker bleed into mic reaches rms 250-430.
  // User's direct voice typically hits 500+.
  private static readonly INTERRUPT_THRESHOLD = 500;
  private static readonly INTERRUPT_CHUNKS_REQUIRED = 3; // ~300ms sustained to confirm
  private interruptChunks = 0; // consecutive chunks above interrupt threshold

  /** Mute/unmute — blocks audio sending and interrupt detection. */
  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  /** Set the actual recording sample rate (from startRecording result). */
  setSourceRate(rate: number): void {
    if (rate !== this.sourceRate) {
      console.log(`[VoiceSession] Source rate: ${rate}Hz → 16000Hz (ratio ${(rate / 16000).toFixed(3)})`);
    }
    this.sourceRate = rate;
  }

  sendAudio(base64Pcm: string): void {
    if (!this.ws || (this.state !== 'ready' && this.state !== 'listening' && this.state !== 'responding')) {
      return;
    }

    // Muted — don't send audio or detect interrupts
    if (this.muted) {
      return;
    }

    // Validate and fix the base64 audio chunk
    let cleaned = this.validateAndFixChunk(base64Pcm);
    if (!cleaned) {
      return; // chunk was invalid and unfixable
    }

    // Downsample to 16kHz if recording at a higher rate
    if (this.sourceRate !== 16000) {
      cleaned = downsamplePcm16(cleaned, this.sourceRate, 16000);
    }

    // Compute audio energy for silence detection + AGC
    const rms = computeRms(cleaned);
    const isQuiet = rms < VoiceSession.SILENCE_THRESHOLD;

    // Automatic gain control — Gemini needs rms ~6000+ to recognize speech.
    // Phone mic produces rms ~300. Apply gain to reach target level.
    if (!isQuiet && rms > 0) {
      const gain = Math.min(30, 6000 / rms); // cap at 30x to prevent extreme amplification
      if (gain > 1.5) {
        cleaned = applyGain(cleaned, gain);
      }
    }

    if (isQuiet) {
      this.quietChunks++;
    } else {
      this.quietChunks = 0;
    }

    // Interruption: user speaking while Gemini is responding — clear playback and pivot.
    // Requires sustained loud audio (above INTERRUPT_THRESHOLD for INTERRUPT_CHUNKS_REQUIRED
    // consecutive chunks) to avoid false triggers from speaker bleed into the mic.
    if (this.state === 'responding') {
      if (rms > VoiceSession.INTERRUPT_THRESHOLD) {
        this.interruptChunks++;
        if (this.interruptChunks >= VoiceSession.INTERRUPT_CHUNKS_REQUIRED) {
          console.log(`[VoiceSession] Interruption confirmed (rms=${rms.toFixed(0)}, ${this.interruptChunks} chunks)`);
          this.interruptChunks = 0;
          // End the current activity (if any), then start a new one for the interruption
          if (this.activityActive) {
            this.sendActivityEnd();
          }
          this.sendActivityStart();
          this.emit('interrupt');
          this.setState('listening');
          // Reset quiet counter so we don't immediately end the new turn
          this.quietChunks = 0;
        }
      } else {
        this.interruptChunks = 0;
      }
    }

    // Auto-manage activity signals based on silence detection.
    // Only send activity signals when NOT in responding state — sending them during
    // Gemini's response causes fragmented replies (Gemini treats each signal as a new turn).
    if (this.state !== 'responding') {
      if (!this.activityActive && !isQuiet) {
        // Speech started — signal activity
        this.sendActivityStart();
        if (this.state === 'ready') {
          this.setState('listening');
        }
      } else if (this.activityActive && this.quietChunks >= VoiceSession.QUIET_CHUNKS_TO_END) {
        // Prolonged silence — end activity to trigger Gemini response
        this.sendActivityEnd();
        return; // don't send this quiet chunk
      }
    }

    if (!this.activityActive) {
      return; // don't send audio when not in an active turn
    }

    this.audioChunksSent++;

    if (this.audioChunksSent <= 3 || this.audioChunksSent % 50 === 0) {
      console.log(
        `[VoiceSession] Chunk #${this.audioChunksSent} sent=${cleaned.length} rms=${rms.toFixed(0)} ` +
        `skipped=${this.audioChunksSkipped} fixed=${this.audioChunksFixed}`,
      );
    }

    this.ws.send(
      JSON.stringify({
        realtimeInput: {
          mediaChunks: [{
            data: cleaned,
            mimeType: 'audio/pcm;rate=16000',
          }],
        },
      }),
    );
  }

  // ── Activity signals (manual VAD) ────────────────────────

  private sendActivityStart(): void {
    if (!this.ws || this.activityActive) return;
    this.activityActive = true;
    this.quietChunks = 0;
    console.log('[VoiceSession] → activityStart');
    this.ws.send(JSON.stringify({ realtimeInput: { activityStart: {} } }));
  }

  private sendActivityEnd(): void {
    if (!this.ws || !this.activityActive) return;
    this.activityActive = false;
    console.log('[VoiceSession] → activityEnd');
    this.ws.send(JSON.stringify({ realtimeInput: { activityEnd: {} } }));
  }

  /**
   * Validates a base64 PCM chunk and fixes common issues:
   * - Strips whitespace/newlines that iOS base64 may include
   * - Ensures base64 length is divisible by 4 (re-pads if needed)
   * - Skips runt chunks (< 128 bytes decoded, ~4ms at 16kHz)
   * - Fixes odd decoded byte count (invalid for 16-bit PCM) by trimming
   *
   * Returns cleaned base64 string, or null if chunk should be skipped.
   */
  private validateAndFixChunk(raw: string): string | null {
    // Strip any whitespace/newlines (iOS base64EncodedString can include them)
    let b64 = raw.replace(/[\r\n\s]/g, '');

    // Ensure valid base64 padding (length must be divisible by 4)
    const remainder = b64.length % 4;
    if (remainder === 1) {
      // Invalid base64 — single trailing char is never valid, strip it
      b64 = b64.slice(0, -1);
    } else if (remainder === 2) {
      b64 += '==';
    } else if (remainder === 3) {
      b64 += '=';
    }

    if (b64.length === 0) {
      return null;
    }

    // Calculate decoded byte count
    let padChars = 0;
    if (b64.endsWith('==')) padChars = 2;
    else if (b64.endsWith('=')) padChars = 1;
    const decodedSize = (b64.length * 3) / 4 - padChars;

    // Skip runt chunks (< 128 bytes ≈ 4ms at 16kHz 16-bit mono)
    if (decodedSize < 128) {
      this.audioChunksSkipped++;
      if (this.audioChunksSkipped <= 5) {
        console.log(`[VoiceSession] Skipping runt chunk: ${decodedSize} bytes`);
      }
      return null;
    }

    // Fix odd byte count — invalid for 16-bit PCM (each sample = 2 bytes).
    // Trim last byte by decoding, slicing, re-encoding.
    if (decodedSize % 2 !== 0) {
      try {
        const decoded = atob(b64);
        const trimmed = decoded.slice(0, -1); // drop last byte for even count
        b64 = btoa(trimmed);
        this.audioChunksFixed++;
        if (this.audioChunksFixed <= 5) {
          console.log(`[VoiceSession] Fixed odd chunk: ${decodedSize} → ${decodedSize - 1} bytes`);
        }
      } catch {
        // If atob/btoa fails, skip this chunk
        this.audioChunksSkipped++;
        return null;
      }
    }

    return b64;
  }

  // ── WebSocket handlers ────────────────────────────────────

  private handleOpen = (): void => {
    this.sessionSpan?.addEvent('voice.ws.open', {
      'time_to_open_ms': Date.now() - this.sessionStartMs,
    });
    this.setState('setup');
    this.sendSetup();
    this.startKeepalive();
  };

  private messagesReceived = 0;

  private handleMessage = (event: MessageEvent): void => {
    try {
      // React Native WebSocket delivers text frames as strings and binary as ArrayBuffer
      let jsonStr: string;
      if (typeof event.data === 'string') {
        jsonStr = event.data;
      } else if (event.data instanceof ArrayBuffer) {
        jsonStr = new TextDecoder().decode(event.data);
      } else {
        // Blob or other — try toString, or read text from Blob-like object
        jsonStr = typeof event.data?.text === 'function'
          ? 'BLOB' // can't decode synchronously
          : String(event.data);
        if (jsonStr === 'BLOB') {
          // Use FileReader for Blob (async fallback)
          const reader = new FileReader();
          reader.onload = () => {
            if (typeof reader.result === 'string') {
              // Re-dispatch as a synthetic event with the decoded string
              this.handleMessage({ data: reader.result } as MessageEvent);
            }
          };
          reader.readAsText(event.data as Blob);
          return;
        }
      }

      const data = JSON.parse(jsonStr);
      this.messagesReceived++;

      if (this.messagesReceived <= 5 || this.messagesReceived % 20 === 0) {
        console.log(`[VoiceSession] Message #${this.messagesReceived}, keys=${Object.keys(data).join(',')}`);
      }

      // Setup complete confirmation
      if (data.setupComplete) {
        console.log('[VoiceSession] Setup complete, sessionId:', data.setupComplete.sessionId);
        this.sessionSpan?.addEvent('voice.setup.complete', {
          'session_id': data.setupComplete.sessionId ?? 'unknown',
          'time_to_ready_ms': Date.now() - this.sessionStartMs,
        });
        if (data.setupComplete.sessionId) {
          this.sessionSpan?.setAttribute('voice.session.gemini_id', data.setupComplete.sessionId);
        }
        this.setState('ready');
        return;
      }

      // Server audio response
      if (data.serverContent?.modelTurn?.parts) {
        if (this.state !== 'responding') {
          this.setState('responding');
        }

        for (const part of data.serverContent.modelTurn.parts) {
          if (part.inlineData?.data) {
            this.emit('audioOutput', part.inlineData.data);
          }
        }
      }

      // Turn complete — reset activity state so user can speak again
      if (data.serverContent?.turnComplete) {
        console.log('[VoiceSession] Turn complete received');
        this.sessionSpan?.addEvent('voice.turn.complete', {
          'audio_chunks_sent_total': this.audioChunksSent,
          'messages_received_total': this.messagesReceived,
        });
        this.activityActive = false;
        this.quietChunks = 0;
        this.emit('turnComplete');
        this.setState('ready');
      }
    } catch (err) {
      console.log(`[VoiceSession] Message parse error: ${err}, dataType=${typeof event.data}, len=${typeof event.data === 'string' ? event.data.length : '?'}`);
    }
  };

  private handleError = (): void => {
    const err = new Error('WebSocket connection error');
    this.recordSessionError(err);
    this.endSessionSpan('ws_error');
    this.setState('error');
    this.emit('error', err);
  };

  private handleClose = (): void => {
    this.stopKeepalive();
    if (this.state !== 'closed') {
      // Closed unexpectedly (server-side or network) — distinguish from user disconnect.
      this.endSessionSpan('ws_close');
      this.setState('closed');
    }
  };

  // ── Protocol messages ─────────────────────────────────────

  private sendSetup(): void {
    if (!this.ws) return;

    this.ws.send(
      JSON.stringify({
        setup: {
          model: DEFAULT_VOICE_CONFIG.model,
          generationConfig: {
            responseModalities: ['AUDIO'],
            speechConfig: {
              voiceConfig: {
                prebuiltVoiceConfig: {
                  voiceName: this.config.voiceName,
                },
              },
            },
          },
          realtimeInputConfig: {
            automaticActivityDetection: {
              disabled: true,
            },
          },
        },
      }),
    );
  }

  // ── Keepalive ─────────────────────────────────────────────

  private startKeepalive(): void {
    this.stopKeepalive();
    this.keepaliveTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        // Send empty realtimeInput as keepalive
        this.ws.send(
          JSON.stringify({
            realtimeInput: {},
          }),
        );
      }
    }, KEEPALIVE_INTERVAL_MS);
  }

  private stopKeepalive(): void {
    if (this.keepaliveTimer) {
      clearInterval(this.keepaliveTimer);
      this.keepaliveTimer = null;
    }
  }

  // ── State management ──────────────────────────────────────

  private setState(state: VoiceSessionState): void {
    if (this.state === state) return;
    this.state = state;
    this.emit('stateChange', state);
  }

  // ── Event emitter ─────────────────────────────────────────

  on<K extends keyof VoiceSessionEventMap>(
    event: K,
    cb: Listener<VoiceSessionEventMap[K]>,
  ): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(cb);
  }

  off<K extends keyof VoiceSessionEventMap>(
    event: K,
    cb: Listener<VoiceSessionEventMap[K]>,
  ): void {
    this.listeners.get(event)?.delete(cb);
  }

  private emit<K extends keyof VoiceSessionEventMap>(
    event: K,
    ...args: VoiceSessionEventMap[K]
  ): void {
    this.listeners.get(event)?.forEach((cb) => cb(...args));
  }
}

// ── Audio utilities ──────────────────────────────────────────

/**
 * Compute RMS (root mean square) energy of base64-encoded PCM 16-bit LE audio.
 * Returns a value 0–32767. Used for silence detection.
 */
function computeRms(b64: string): number {
  const decoded = atob(b64);
  const samples = decoded.length >> 1;
  if (samples === 0) return 0;

  let sumSq = 0;
  // Sample every 8th value for speed (still accurate enough for silence detection)
  const step = Math.max(1, Math.min(8, samples >> 4));
  let count = 0;
  for (let i = 0; i < samples; i += step) {
    const lo = decoded.charCodeAt(i * 2);
    const hi = decoded.charCodeAt(i * 2 + 1);
    const s = (lo | (hi << 8));
    const signed = s > 32767 ? s - 65536 : s;
    sumSq += signed * signed;
    count++;
  }

  return Math.sqrt(sumSq / count);
}

/**
 * Apply gain to base64-encoded PCM 16-bit LE audio.
 * Multiplies each sample by gainFactor, clamping to 16-bit range.
 */
function applyGain(b64: string, gainFactor: number): string {
  const decoded = atob(b64);
  let result = '';
  for (let i = 0; i < decoded.length - 1; i += 2) {
    const lo = decoded.charCodeAt(i);
    const hi = decoded.charCodeAt(i + 1);
    const s = (lo | (hi << 8));
    const signed = s > 32767 ? s - 65536 : s;
    let amplified = Math.round(signed * gainFactor);
    amplified = Math.max(-32768, Math.min(32767, amplified));
    const u = amplified < 0 ? amplified + 65536 : amplified;
    result += String.fromCharCode(u & 0xff, (u >> 8) & 0xff);
  }
  return btoa(result);
}

// ── Audio resampling ─────────────────────────────────────────

/**
 * Downsample base64-encoded PCM 16-bit LE audio from one sample rate to another.
 * Uses linear interpolation for non-integer ratios (e.g., 44100 → 16000).
 * For integer ratios (e.g., 48000 → 16000 = 3:1), this is equivalent to decimation.
 */
function downsamplePcm16(b64: string, fromRate: number, toRate: number): string {
  if (fromRate === toRate) return b64;

  const decoded = atob(b64);
  const srcSamples = decoded.length >> 1; // 2 bytes per 16-bit sample
  const ratio = fromRate / toRate;
  const dstSamples = Math.floor(srcSamples / ratio);

  if (dstSamples === 0) return b64;

  let result = '';
  for (let i = 0; i < dstSamples; i++) {
    const srcPos = i * ratio;
    const srcIdx = Math.floor(srcPos);
    const frac = srcPos - srcIdx;

    // Read 16-bit LE sample at srcIdx
    const lo0 = decoded.charCodeAt(srcIdx * 2);
    const hi0 = decoded.charCodeAt(srcIdx * 2 + 1);
    const s0 = (lo0 | (hi0 << 8));
    const s0s = s0 > 32767 ? s0 - 65536 : s0; // sign-extend

    let sample: number;
    if (frac > 0 && srcIdx + 1 < srcSamples) {
      // Linearly interpolate with next sample
      const lo1 = decoded.charCodeAt((srcIdx + 1) * 2);
      const hi1 = decoded.charCodeAt((srcIdx + 1) * 2 + 1);
      const s1 = (lo1 | (hi1 << 8));
      const s1s = s1 > 32767 ? s1 - 65536 : s1;
      sample = Math.round(s0s + frac * (s1s - s0s));
    } else {
      sample = s0s;
    }

    // Clamp to 16-bit range and write as LE
    sample = Math.max(-32768, Math.min(32767, sample));
    const u = sample < 0 ? sample + 65536 : sample;
    result += String.fromCharCode(u & 0xff, (u >> 8) & 0xff);
  }

  return btoa(result);
}
