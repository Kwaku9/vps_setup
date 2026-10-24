import { renderMarkdown } from './markdown';

export const voice = $state({ activeId: '', phase: 'idle', message: '', error: '' });
let worker: Worker | undefined;
let context: AudioContext | undefined;
let playing: AudioBufferSourceNode | undefined;
let recorder: MediaRecorder | undefined;
let microphone: MediaStream | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let operation = 0;

export const canDictate = () => window.isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function' && typeof window.MediaRecorder === 'function';

export function cancelVoice() {
  operation++;
  if (timer) clearTimeout(timer);
  timer = undefined;
  if (recorder) { recorder.onstop = null; if (recorder.state !== 'inactive') recorder.stop(); }
  recorder = undefined;
  microphone?.getTracks().forEach((track) => track.stop()); microphone = undefined;
  if (playing) { playing.onended = null; playing.stop(); playing = undefined; }
  worker?.terminate(); worker = undefined;
  if (context) { void context.close(); context = undefined; }
  voice.activeId = ''; voice.phase = 'idle'; voice.message = '';
}

function fail(message: string) {
  cancelVoice(); voice.error = message;
}

function makeWorker(id: number, onText?: (text: string) => void) {
  worker = new Worker(new URL('./voice.worker.ts', import.meta.url), { type: 'module' });
  worker.onerror = () => { if (id === operation) fail('Local voice could not start in this browser. You can still type a reply.'); };
  worker.onmessage = async ({ data }) => {
    if (id !== operation) return;
    if (data.type === 'progress') voice.message = `Downloading local voice model… ${data.percent}%`;
    else if (data.type === 'status') voice.message = data.message;
    else if (data.type === 'text') onText?.(data.text.trim());
    else if (data.type === 'error') fail(data.message);
    else if (data.type === 'done') cancelVoice();
    else if (data.type === 'audio' && context) {
      try {
        const audio = context.createBuffer(1, data.samples.length, data.sampleRate);
        audio.copyToChannel(data.samples, 0);
        const source = context.createBufferSource(); source.buffer = audio; source.connect(context.destination);
        source.onended = () => { if (id === operation) { playing = undefined; worker?.postMessage({ type: 'played' }); } };
        playing = source; voice.phase = 'speaking'; voice.message = 'Playing locally · Kokoro';
        source.start();
      } catch { fail('Audio playback failed. Tap Listen to try again.'); }
    }
  };
  return worker;
}

export async function listen(entryId: string, markdown: string) {
  if (voice.activeId === entryId) { cancelVoice(); return; }
  cancelVoice(); voice.error = '';
  const element = document.createElement('div'); element.innerHTML = renderMarkdown(markdown);
  element.querySelectorAll('pre, .code-label').forEach((node) => node.remove());
  const text = (element.textContent ?? '').trim();
  if (!text) { voice.error = 'This message has no spoken text.'; return; }
  const id = operation;
  voice.activeId = entryId; voice.phase = 'loading'; voice.message = 'Loading Kokoro on this device…';
  try {
    // Resume during the tap so iOS permits playback after an asynchronous model load.
    context = new AudioContext(); await context.resume();
    if (id !== operation) return;
    makeWorker(id).postMessage({ type: 'speak', text });
  } catch { fail('This browser could not start local audio playback.'); }
}

export async function startDictation(sessionId: string, onText: (text: string) => void) {
  cancelVoice(); voice.error = '';
  if (!canDictate()) { voice.error = 'Dictation needs microphone support and HTTPS in this browser.'; return; }
  const id = operation;
  voice.activeId = `dictate:${sessionId}`; voice.phase = 'starting'; voice.message = 'Opening microphone…';
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (id !== operation) { stream.getTracks().forEach((track) => track.stop()); return; }
    microphone = stream;
    const chunks: BlobPart[] = [];
    const capture = new MediaRecorder(stream); recorder = capture;
    capture.ondataavailable = ({ data }) => { if (data.size) chunks.push(data); };
    capture.onerror = () => fail('Microphone recording failed. Try dictation again.');
    capture.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop()); microphone = undefined; recorder = undefined;
      if (timer) clearTimeout(timer); timer = undefined;
      if (id !== operation) return;
      voice.phase = 'transcribing'; voice.message = 'Loading Whisper Tiny on this device…';
      try {
        const blob = new Blob(chunks, { type: capture.mimeType });
        context = new AudioContext();
        const decoded = await context.decodeAudioData(await blob.arrayBuffer());
        if (id !== operation) return;
        // Whisper requires mono 16 kHz; use the browser's audio resampler, not
        // the microphone's reported sample rate or a server upload.
        const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000);
        const source = offline.createBufferSource(); source.buffer = decoded; source.connect(offline.destination); source.start();
        const converted = await offline.startRendering();
        if (id !== operation) return;
        const samples = converted.getChannelData(0).slice();
        makeWorker(id, onText).postMessage({ type: 'transcribe', samples }, [samples.buffer]);
      } catch { if (id === operation) fail('Could not read the microphone audio in this browser. You can still type a reply.'); }
    };
    capture.start(); voice.phase = 'recording'; voice.message = 'Recording locally · tap Stop when finished';
    timer = setTimeout(stopDictation, 30000);
  } catch { if (id === operation) fail('Microphone access was not available. Check this site’s microphone permission.'); }
}

export function stopDictation() {
  if (recorder?.state === 'recording') recorder.stop();
}
