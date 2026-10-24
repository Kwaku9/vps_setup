/// <reference lib="webworker" />
// Models load only after a voice action. Inference and audio stay on this device.
let acknowledge: (() => void) | undefined;
const emit = (message: Record<string, unknown>, transfer: Transferable[] = []) =>
  self.postMessage(message, { transfer });
const progress = (value: { status: string; progress?: number; file?: string }) => {
  if (value.status === 'progress') emit({ type: 'progress', percent: Math.round(value.progress ?? 0) });
};

self.onmessage = async ({ data }) => {
  if (data.type === 'played') { acknowledge?.(); return; }
  try {
    const { env, pipeline } = await import('@huggingface/transformers');
    env.allowLocalModels = false;
    env.useBrowserCache = true;
    // Single-thread WASM works in mobile browsers without SharedArrayBuffer or
    // cross-origin isolation headers that could break OPS sign-in/resources.
    env.backends.onnx.wasm!.numThreads = 1;
    env.backends.onnx.wasm!.proxy = false;
    if (data.type === 'speak') {
      const { KokoroTTS } = await import('kokoro-js');
      const tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
        dtype: 'q8', device: 'wasm', progress_callback: progress,
      });
      // Bound audio memory for long responses; play each chunk before the next.
      const chunks = data.text.match(/[^.!?\n]+[.!?\n]*|[.!?\n]+/g) ?? [data.text];
      for (const sentence of chunks) {
        const words = sentence.trim().split(/\s+/);
        for (let i = 0; i < words.length; i += 65) {
          const text = words.slice(i, i + 65).join(' ');
          if (!text) continue;
          emit({ type: 'status', message: 'Preparing speech on this device…' });
          const audio = await tts.generate(text, { voice: 'af_heart' });
          const channel = Array.isArray(audio.audio) ? audio.audio[0] : audio.audio;
          const samples = Float32Array.from(channel);
          const played = new Promise<void>((resolve) => { acknowledge = resolve; });
          emit({ type: 'audio', samples, sampleRate: audio.sampling_rate }, [samples.buffer]);
          await played;
        }
      }
      await tts.model.dispose();
    } else if (data.type === 'transcribe') {
      const recognize = await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
        dtype: 'q8', device: 'wasm', progress_callback: progress,
      });
      emit({ type: 'status', message: 'Transcribing on this device…' });
      const result = await recognize(data.samples as Float32Array, { task: 'transcribe', chunk_length_s: 30 });
      const text = Array.isArray(result) ? result.map((r) => r.text).join(' ') : result.text;
      emit({ type: 'text', text });
      await recognize.dispose();
    }
    emit({ type: 'done' });
  } catch {
    emit({ type: 'error', message: 'Local voice processing failed. Check model-download access and available device memory, then try again.' });
  }
};

export {};
