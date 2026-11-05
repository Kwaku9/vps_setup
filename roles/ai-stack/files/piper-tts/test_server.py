"""piper-tts: OpenAI-compatible /v1/audio/speech in kokoro-tts's place (2026-11-05). Every existing client keeps its
request: OpenWebUI (model "piper"), the Telegram bot (model "kokoro", response_format "mp3"), the tts. route. So the
server accepts ANY model and maps ANY voice name to a configured Piper voice. Run: python3 -m unittest test_server"""
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import wave

import server


class FakeChunk:
    def __init__(self, pcm):
        self.audio_int16_bytes, self.sample_rate, self.sample_width, self.sample_channels = pcm, 22050, 2, 1


class FakeVoice:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, syn_config=None):
        self.calls.append(text)
        yield FakeChunk(b"\x01\x00" * 22050)   # one second of near-silence


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = FakeVoice()
        cls.httpd = server.make_server("127.0.0.1", 0, cls.voice, voice_name="en_US-amy-medium", max_chars=50)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, body):
        req = urllib.request.Request(self.base + "/v1/audio/speech", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=10)
            return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type"), e.read()

    def test_mp3_by_default_and_for_the_telegram_bot(self):
        for body in ({"model": "piper", "input": "hello there", "voice": "amy"},
                     {"model": "kokoro", "input": "hello there", "voice": "af_heart", "response_format": "mp3"}):
            with self.subTest(body["model"]):
                status, ctype, data = self.post(body)
                self.assertEqual(status, 200)
                self.assertEqual(ctype, "audio/mpeg")
                self.assertTrue(data[:3] == b"ID3" or data[0] == 0xFF, "not an mp3 stream")

    def test_wav_on_request(self):
        status, ctype, data = self.post({"model": "tts-1", "input": "hello there", "voice": "alloy", "response_format": "wav"})
        self.assertEqual((status, ctype), (200, "audio/wav"))
        with wave.open(io.BytesIO(data)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (22050, 1, 2))

    def test_any_model_and_any_voice_name_are_accepted(self):
        status, _, _ = self.post({"model": "whatever", "input": "hi there", "voice": "af_bella"})
        self.assertEqual(status, 200)

    def test_unsupported_format_is_a_clear_400(self):
        status, _, data = self.post({"input": "hi there", "response_format": "opus"})
        self.assertEqual(status, 400)
        self.assertIn(b"mp3", data)

    def test_empty_input_is_a_400(self):
        self.assertEqual(self.post({"input": "  "})[0], 400)

    def test_long_input_is_cut_to_max_chars(self):
        self.voice.calls.clear()
        self.post({"input": "x" * 500})
        self.assertLessEqual(len(self.voice.calls[-1]), 50)

    def test_health_and_models(self):
        h = json.loads(urllib.request.urlopen(self.base + "/health", timeout=5).read())
        self.assertEqual(h, {"status": "ok", "voice": "en_US-amy-medium"})
        m = json.loads(urllib.request.urlopen(self.base + "/v1/models", timeout=5).read())
        self.assertIn("piper", [x["id"] for x in m["data"]])

    def test_unknown_path_is_404(self):
        try:
            urllib.request.urlopen(self.base + "/nope", timeout=5)
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


class Signals(unittest.TestCase):
    def test_sigterm_exits_cleanly(self):
        """As PID 1 in a container, Python ignores SIGTERM unless it installs a handler: every podman stop then waited
        the full 10 s and ended in SIGKILL (seen in the 2026-11-05 rehearsal)."""
        import signal
        old = signal.getsignal(signal.SIGTERM)
        try:
            server.install_signal_handlers()
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            with self.assertRaises(SystemExit) as cm:
                handler(signal.SIGTERM, None)
            self.assertEqual(cm.exception.code, 0)
        finally:
            signal.signal(signal.SIGTERM, old)


if __name__ == "__main__":
    unittest.main()
