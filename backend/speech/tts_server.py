r"""
tts_server.py - OpenAI-compatible Text-To-Speech endpoint wrapping Kokoro 82M.

Dedicated to the interrogation app (speech pair C), independent of the SAIF voice
services on 7657/7658.

  POST /v1/audio/speech   (port 7678)
    JSON in: {"input":"<text>", "voice":"Reynolds"|"Chen"|<any kokoro voice>}
    -> raw WAV bytes (Content-Type: audio/wav).  `model` and Authorization are ignored.

Voices: the detectives are Metropolitan Police, so both are cast from Kokoro's
British set. Passing a character name resolves via VOICE_MAP; passing a raw Kokoro
voice id (e.g. "bm_lewis") is honoured as-is, which makes recasting a one-word change.

Kokoro runs on CPU deliberately - it is an 82M model and near real-time on CPU, and
onnxruntime's CUDA provider has not supported Blackwell (sm_120). The venv ships
CPU-only onnxruntime, so GPU is not an option here regardless.

Launch:  "%USERPROFILE%\.claude\voice\.venv\Scripts\python.exe" backend\speech\tts_server.py
"""
import io, json, os, re, threading, wave
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 7678
ROOT   = os.path.join(os.environ["USERPROFILE"], ".claude", "voice")
MODEL  = os.path.join(ROOT, "kokoro-v1.0.onnx")
VOICES = os.path.join(ROOT, "voices-v1.0.bin")

# Casting. DI Reynolds is the bad cop, DS Chen the good cop.
VOICE_MAP = {
    "Reynolds": "bm_george",     # British male, measured and cold
    "Chen":     "bf_isabella",   # British female, warm
}
DEFAULT_VOICE = "bm_george"

# onnxruntime grabs every core by default and thrashes, which surfaces as audible
# stuttering in the synthesised speech. Cap it.
INTRA_OP_THREADS = 4

print("Loading Kokoro...", flush=True)
import onnxruntime as ort
from kokoro_onnx import Kokoro

_so = ort.SessionOptions()
_so.intra_op_num_threads = INTRA_OP_THREADS
_session = ort.InferenceSession(MODEL, sess_options=_so, providers=["CPUExecutionProvider"])
KOKORO = Kokoro.from_session(_session, VOICES)
_lock = threading.Lock()

try:
    AVAILABLE = set(KOKORO.get_voices())
except Exception:
    AVAILABLE = set()

print(f"Kokoro ready (CPU, intra_op_num_threads={INTRA_OP_THREADS}, "
      f"{len(AVAILABLE)} voices)", flush=True)


def _clean(t):
    t = re.sub(r"\s*[—–]\s*", ", ", t)   # em/en dash -> spoken pause
    t = re.sub(r"\s-\s", ", ", t)
    return re.sub(r"\s+", " ", t).strip()


def synth_wav(text, voice):
    requested = (voice or "").strip()
    voice = VOICE_MAP.get(requested, requested) or DEFAULT_VOICE
    if AVAILABLE and voice not in AVAILABLE:
        # Unknown character or voice id - e.g. the agent's Mock Mode speaks as
        # "System". Don't fail the whole line over casting; log and carry on.
        print(f"[tts] unknown voice {requested!r}, using {DEFAULT_VOICE}", flush=True)
        voice = DEFAULT_VOICE
    lang = "en-gb" if voice.startswith("b") else "en-us"
    with _lock:
        samples, sr = KOKORO.create(_clean(text), voice=voice, speed=1.0, lang=lang)
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") in ("", "/health"):
            return self._json(200, {"status": "ok", "voices": VOICE_MAP})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/v1/audio/speech":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            text = (req.get("input") or "").strip()
            if not text:
                return self._json(400, {"error": "missing 'input'"})
            self._send(200, synth_wav(text, req.get("voice")), "audio/wav")
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"TTS  http://{HOST}:{PORT}/v1/audio/speech", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
