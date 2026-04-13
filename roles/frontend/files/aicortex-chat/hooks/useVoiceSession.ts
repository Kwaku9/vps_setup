/**
 * React hook for real-time voice conversations via Gemini Live.
 *
 * Bridges the VoiceSession WebSocket handler with expo-audio-stream
 * for simultaneous mic capture (16kHz) and playback (24kHz).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ExpoPlayAudioStream,
  EncodingTypes,
  type AudioDataEvent,
} from '@mykin-ai/expo-audio-stream';
import { VoiceSession } from '@/services/voiceSession';
import { getVoiceWebSocketUrl, getVoiceKey } from '@/services/api';
import type { VoiceSessionState } from '@/constants/types';

const VOICE_TURN_ID = 'gemini-live';
const DIAG_CHUNK_COUNT = 20; // Set to 0 to disable per-chunk diagnostics

// When true, omit sampleRate from recording config so iOS uses hardware native rate
// (typically 48kHz). VoiceSession will downsample to 16kHz in JS.
// This avoids a bug in expo-audio-stream's iOS resampling where the AVAudioEngine
// tap format is set to the desired rate while hardware delivers at the native rate.
const USE_NATIVE_RATE = true;

export interface UseVoiceSessionReturn {
  sessionState: VoiceSessionState;
  isActive: boolean;
  isMuted: boolean;
  error: string | null;
  startSession: () => Promise<void>;
  endSession: () => void;
  toggleMute: () => void;
}

export function useVoiceSession(): UseVoiceSessionReturn {
  const [sessionState, setSessionState] = useState<VoiceSessionState>('idle');
  const [isMuted, setIsMuted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<VoiceSession | null>(null);
  const recordingRef = useRef(false);
  const subscriptionRef = useRef<{ remove: () => void } | null>(null);

  const isActive =
    sessionState === 'ready' ||
    sessionState === 'listening' ||
    sessionState === 'responding';

  // Clean up on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cleanup = useCallback(() => {
    // Stop recording
    if (recordingRef.current) {
      ExpoPlayAudioStream.stopRecording().catch(() => {});
      recordingRef.current = false;
    }

    // Remove audio subscription
    if (subscriptionRef.current) {
      subscriptionRef.current.remove();
      subscriptionRef.current = null;
    }

    // Stop playback
    ExpoPlayAudioStream.clearPlaybackQueueByTurnId(VOICE_TURN_ID).catch(() => {});

    // Disconnect WebSocket
    if (sessionRef.current) {
      sessionRef.current.disconnect();
      sessionRef.current = null;
    }
  }, []);

  const startSession = useCallback(async () => {
    setError(null);

    // Use the scoped voice key for LiteLLM WebSocket auth
    const token = getVoiceKey();
    if (!token) {
      setError('Voice key not configured — set up in Profile settings');
      return;
    }

    // Request mic permission
    const { granted } = await ExpoPlayAudioStream.requestPermissionsAsync();
    if (!granted) {
      setError('Microphone permission denied');
      return;
    }

    // Create voice session — token sent as first message, proxy handles LiteLLM auth
    const session = new VoiceSession({
      wsUrl: getVoiceWebSocketUrl(),
      token,
    });
    sessionRef.current = session;

    // Wire up events
    session.on('stateChange', (state) => {
      setSessionState(state);

      // Start recording once setup is complete — stays on for the entire session (full-duplex)
      if (state === 'ready' && !recordingRef.current) {
        startRecording(session, recordingRef, subscriptionRef);
      }
    });

    session.on('audioOutput', (base64Pcm) => {
      // Gemini outputs 24kHz PCM, upsample to 48kHz (2x) for playback
      const upsampled = upsample24to48(base64Pcm);
      // Full-duplex: play audio while mic stays on (requires native playAndRecord patch)
      ExpoPlayAudioStream.playSound(
        upsampled,
        VOICE_TURN_ID,
        EncodingTypes.PCM_S16LE,
      ).catch((err) => {
        console.log(`[Playback] Error: ${err}`);
      });
    });

    session.on('interrupt', () => {
      // User spoke during Gemini's response — stop playing old audio immediately
      ExpoPlayAudioStream.clearSoundQueueByTurnId(VOICE_TURN_ID).catch(() => {});
      console.log('[Voice] Interrupted — cleared playback queue');
    });

    session.on('turnComplete', () => {
      console.log('[Voice] Turn complete');
    });

    session.on('error', (err) => {
      setError(err.message);
    });

    // Connect
    session.connect();
  }, []);

  const endSession = useCallback(() => {
    cleanup();
    setSessionState('idle');
    setError(null);
  }, [cleanup]);

  const toggleMute = useCallback(() => {
    setIsMuted((prev) => {
      const next = !prev;
      // Block audio sending at the session level — prevents sending AND interrupt detection
      if (sessionRef.current) {
        sessionRef.current.setMuted(next);
      }
      console.log(`[Voice] Mic ${next ? 'muted' : 'unmuted'}`);
      return next;
    });
  }, []);

  return { sessionState, isActive, isMuted, error, startSession, endSession, toggleMute };
}

// ── Audio helpers ─────────────────────────────────────────────

async function startRecording(
  session: VoiceSession,
  recordingRef: React.MutableRefObject<boolean>,
  subscriptionRef: React.MutableRefObject<{ remove: () => void } | null>,
): Promise<void> {
  try {
    recordingRef.current = true;
    let chunkIndex = 0;

    const recordingConfig: Record<string, unknown> = {
      channels: 1,
      encoding: 'pcm_16bit',
      interval: 100, // iOS enforces 100ms minimum — be explicit
    };

    // Either record at 16kHz (library handles resampling) or at native rate (we resample)
    if (!USE_NATIVE_RATE) {
      recordingConfig.sampleRate = 16000;
    }

    const { recordingResult, subscription } = await ExpoPlayAudioStream.startRecording({
      ...recordingConfig,
      onAudioStream: async (event: AudioDataEvent) => {
        const idx = chunkIndex++;
        const data = typeof event.data === 'string' ? event.data : null;

        // Diagnostic logging for first N chunks — includes raw audio RMS
        if (idx < DIAG_CHUNK_COUNT && data) {
          const len = data.length;
          const padChars = data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0;
          const decodedBytes = Math.floor((len * 3) / 4) - padChars;
          // Compute RMS on RAW audio (before downsampling) to check mic capture
          let rawRms = 0;
          try {
            const raw = atob(data);
            const samp = raw.length >> 1;
            let sum = 0;
            const step = Math.max(1, samp >> 6);
            let cnt = 0;
            for (let j = 0; j < samp; j += step) {
              const lo = raw.charCodeAt(j * 2);
              const hi = raw.charCodeAt(j * 2 + 1);
              const s = (lo | (hi << 8));
              const v = s > 32767 ? s - 65536 : s;
              sum += v * v;
              cnt++;
            }
            rawRms = Math.sqrt(sum / cnt);
          } catch { /* ignore */ }
          console.log(
            `[AudioDiag] #${idx} b64len=${len} ~bytes=${decodedBytes} rawRms=${rawRms.toFixed(0)} ` +
            `pos=${event.position} b64mod4=${len % 4}`,
          );
        }

        if (data) {
          session.sendAudio(data);
        }
      },
    });

    // Configure downsampling based on actual hardware rate
    const actualRate = recordingResult.sampleRate ?? 16000;
    console.log(
      `[Recording] Started: rate=${actualRate}Hz native=${USE_NATIVE_RATE} ` +
      `channels=${recordingResult.channels} bits=${recordingResult.bitDepth}`,
    );
    session.setSourceRate(actualRate);

    if (subscription) {
      subscriptionRef.current = subscription;
    }
  } catch {
    recordingRef.current = false;
  }
}

/**
 * Upsample 24kHz PCM 16-bit LE to 48kHz by duplicating each sample.
 * Gemini outputs 24kHz, but expo-audio-stream plays at 48kHz hardware rate.
 */
function upsample24to48(b64: string): string {
  const decoded = atob(b64);
  let result = '';
  // Each 16-bit sample is 2 bytes — duplicate it for 2x upsample
  for (let i = 0; i < decoded.length - 1; i += 2) {
    const lo = decoded.charAt(i);
    const hi = decoded.charAt(i + 1);
    result += lo + hi + lo + hi; // write sample twice
  }
  return btoa(result);
}
