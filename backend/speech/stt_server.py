r"""
stt_server.py - OpenAI-compatible Speech-To-Text endpoint wrapping faster-whisper.

Dedicated to the interrogation app (speech pair C) so it stays independent of the
SAIF voice services on 7657/7658 - those run small.en, which is the wrong model for
the non-native accented English our learners speak.

  POST /v1/audio/transcriptions   (port 7677)
    multipart form: file=<audio blob: webm/opus/wav/mp3/...>, model=..., language=...
    -> JSON {"text":"<transcript>"}.  `model` is ignored; faster-whisper decodes the
       blob as-is via av/ffmpeg, so webm/opus from a browser works directly.

Launch:  "%USERPROFILE%\.claude\voice\.venv\Scripts\python.exe" backend\speech\stt_server.py
         (that venv already has faster-whisper, ctranslate2 and the NVIDIA CUDA wheels;
          there is nothing to install)
"""
import json, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 7677
MODEL_NAME = "large-v3"


def _register_cuda_dlls():
    """Put the pip-installed NVIDIA runtime DLLs on the loader search path.

    The nvidia-cublas-cu12 / nvidia-cudnn-cu12 wheels keep their DLLs in
    site-packages/nvidia/<pkg>/bin, which Windows does not search. Without this,
    CTranslate2 raises "Library cublas64_12.dll is not found" and we silently
    drop to CPU int8 - roughly an order of magnitude slower, with no error.
    """
    try:
        import nvidia
    except ImportError:
        return 0
    found = 0
    for root in nvidia.__path__:
        for sub in os.listdir(root):
            p = os.path.join(root, sub, "bin")
            if os.path.isdir(p):
                os.add_dll_directory(p)
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                found += 1
    return found


print(f"Registered {_register_cuda_dlls()} NVIDIA DLL directories", flush=True)
print(f"Loading Whisper {MODEL_NAME}...", flush=True)
import numpy as np
from faster_whisper import WhisperModel


def _load():
    # Try GPU, but force one inference so a broken CUDA surfaces here rather than
    # on the first real request.
    try:
        m = WhisperModel(MODEL_NAME, device="cuda", compute_type="float16")
        list(m.transcribe(np.zeros(16000, dtype=np.float32), language="en", vad_filter=False)[0])
        print(f"STT on CUDA (GPU): {MODEL_NAME}", flush=True)
        return m
    except Exception as e:
        # Loud on purpose. A silent CPU fallback here is the difference between
        # a snappy interview and one that stalls for seconds on every answer.
        print("=" * 72, flush=True)
        print(f"WARNING: GPU unavailable ({e})", flush=True)
        print(f"WARNING: falling back to CPU int8 - {MODEL_NAME} will be SLOW.", flush=True)
        print("=" * 72, flush=True)
        return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")


MODEL = _load()
_lock = threading.Lock()
print("Whisper ready", flush=True)


def _extract_file(body, boundary):
    """Pull the 'file' field's raw bytes out of a multipart/form-data body."""
    delim = b"--" + boundary.encode()
    for part in body.split(delim):
        if b"\r\n\r\n" not in part:
            continue
        head, content = part.split(b"\r\n\r\n", 1)
        if b'name="file"' in head:
            return content[:-2] if content.endswith(b"\r\n") else content
    return None


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") in ("", "/health"):
            return self._send(200, {"status": "ok", "model": MODEL_NAME})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/v1/audio/transcriptions":
            return self._send(404, {"error": "not found"})
        try:
            ctype = self.headers.get("Content-Type", "")
            if "boundary=" not in ctype:
                return self._send(400, {"error": "expected multipart/form-data"})
            boundary = ctype.split("boundary=", 1)[1].strip().strip('"')
            n = int(self.headers.get("Content-Length", 0) or 0)
            audio = _extract_file(self.rfile.read(n), boundary)
            if not audio:
                return self._send(400, {"error": "missing file field"})
            tf = tempfile.NamedTemporaryFile(delete=False)
            tf.write(audio); tf.close()
            try:
                with _lock:
                    # language pinned to en: large-v3 is multilingual and can
                    # misdetect heavily accented English as another language.
                    segs, _ = MODEL.transcribe(tf.name, language="en", vad_filter=True)
                    text = "".join(s.text for s in segs).strip()
            finally:
                try: os.remove(tf.name)
                except Exception: pass
            self._send(200, {"text": text})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"STT  http://{HOST}:{PORT}/v1/audio/transcriptions", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
