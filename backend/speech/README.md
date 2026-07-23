# Local speech sidecars (speech pair C)

Fully local STT and TTS for the interrogation app. No API keys, no network calls.
Both expose **OpenAI-compatible** endpoints, so swapping back to a hosted provider is a
URL change in `backend/main.py` (`STT_URL` / `TTS_URL`).

| Service | Port | Endpoint | Engine |
|---|---|---|---|
| STT | 7677 | `POST /v1/audio/transcriptions` (multipart `file=`) → `{"text": ...}` | faster-whisper **large-v3**, CUDA |
| TTS | 7678 | `POST /v1/audio/speech` (`{"input","voice"}`) → WAV | Kokoro 82M, CPU |

Both also answer `GET /health`.

## Running them

There is **nothing to install.** These run on the shared voice venv, which already has
faster-whisper, ctranslate2, kokoro-onnx and the NVIDIA CUDA wheels — and both models are
already in the local cache (`large-v3` 2.9 GB, Kokoro 325 MB).

```bash
"$USERPROFILE/.claude/voice/.venv/Scripts/python.exe" backend/speech/stt_server.py
"$USERPROFILE/.claude/voice/.venv/Scripts/python.exe" backend/speech/tts_server.py
```

Confirm STT came up on the GPU — the startup line must read:

```
STT on CUDA (GPU): large-v3
```

## Why pair C and not the existing pair A (7657/7658)

Pair A serves SAIF and runs **`small.en`**. Our learners are non-native speakers, and
accented L2 English is exactly where a small English-only model degrades — which would
present as the app failing rather than the model struggling. Pair C also isolates us, so
a SAIF restart doesn't take the interrogation down. Ports are registered in
`~/.claude/PORTS.md`.

## Two traps worth knowing

**1. CUDA DLLs are not on any search path.** The `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`
wheels keep their DLLs in `site-packages/nvidia/<pkg>/bin`, which Windows does not search.
Without `_register_cuda_dlls()`, CTranslate2 raises `Library cublas64_12.dll is not found`
and faster-whisper **silently** falls back to CPU int8 — roughly an order of magnitude
slower, with no error surfaced. That is why the fallback in `stt_server.py` is deliberately
loud.

**2. Kokoro on CPU must cap its threads.** onnxruntime grabs every core by default and
thrashes, which surfaces as audible stuttering. `tts_server.py` builds its own
`InferenceSession` with `intra_op_num_threads=4` via `Kokoro.from_session()`.

Kokoro runs on CPU deliberately: it is an 82M model (3.5–4.5× faster than realtime), and
onnxruntime's CUDA provider has not supported Blackwell (sm_120). The venv ships CPU-only
onnxruntime, so GPU is not an option here regardless.

## Casting

Both detectives are Metropolitan Police, so both are cast from Kokoro's British voices.
The mapping lives in `tts_server.py`, not in the backend:

| Character | Voice |
|---|---|
| DI Reynolds (bad cop) | `bm_george` |
| DS Chen (good cop) | `bf_isabella` |

Passing a raw Kokoro voice id instead of a character name is honoured as-is, so recasting
is a one-word change. Other British options: `bm_daniel`, `bm_fable`, `bm_lewis`,
`bf_alice`, `bf_emma`, `bf_lily`.

## Known limitation

Kokoro returns a **complete WAV**, not a stream. Where the old hosted path streamed MP3
chunks and started playback almost immediately, the whole utterance is now synthesised
first — about **1.7 s of silence before a 20-word line**. If that hurts the interrogation
pacing, the fix is sentence-level chunking: synthesise the first sentence, start playback,
and synthesise the rest behind it.
