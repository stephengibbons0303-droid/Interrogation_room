import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn
import logging
import httpx

import agent as agent_module
import auth
import sessions
from db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Build the LLM and vector store up front so the first learner does not pay
    # the cost, and so a misconfiguration is visible at boot rather than mid-interview.
    agent_module.init_resources()
    yield


app = FastAPI(lifespan=lifespan)


app.include_router(auth.router)
app.include_router(sessions.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local speech sidecars (pair C). Both are OpenAI-compatible, so swapping back to a
# hosted provider is a URL change. See backend/speech/ for the servers themselves.
# Character -> Kokoro voice mapping lives in the TTS server, not here.
STT_URL = os.getenv("STT_URL", "http://127.0.0.1:7677/v1/audio/transcriptions")
TTS_URL = os.getenv("TTS_URL", "http://127.0.0.1:7678/v1/audio/speech")

class TTSSegment(BaseModel):
    text: str
    voice: str = "Reynolds"


class TTSRequest(BaseModel):
    # A normal turn is one line. An aside is two speakers, sent as segments and
    # returned as a single wav so the client plays it exactly as it plays a
    # single line - no sequencing in the browser, no gap mid-exchange.
    text: Optional[str] = None
    voice: str = "Reynolds"
    segments: Optional[List[TTSSegment]] = None

@app.get("/")
async def root():
    return {"status": "ok", "service": "Interrogation Learning System Backend"}

# NOTE: the old unauthenticated POST /chat is gone. It ignored its session_id and
# routed every learner through one shared agent. Chat is now
# POST /interviews/{id}/chat - authenticated, and scoped to one interview.

@app.post("/tts")
async def tts_endpoint(request: TTSRequest):
    """Synthesise a detective's line via the local Kokoro sidecar.

    Kokoro returns a complete WAV rather than a stream, so unlike the previous
    hosted-MP3 path there is no chunked playback - the whole utterance is
    synthesised before audio starts. Roughly 3.5-4.5x faster than realtime, so a
    typical 20-word line costs ~1.7s of silence up front.
    """
    if request.segments:
        payload = {"segments": [s.model_dump() for s in request.segments]}
    elif request.text:
        payload = {"input": request.text, "voice": request.voice}
    else:
        raise HTTPException(status_code=400, detail="Provide 'text' or 'segments'")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(TTS_URL, json=payload, timeout=60.0)
    except httpx.TimeoutException:
        logger.error("TTS request timed out")
        raise HTTPException(status_code=504, detail="TTS request timed out")
    except Exception as e:
        logger.error(f"TTS unreachable at {TTS_URL}: {e}")
        raise HTTPException(status_code=502, detail="TTS service unreachable")

    if response.status_code != 200:
        logger.error(f"TTS error: {response.status_code} {response.text[:200]}")
        raise HTTPException(status_code=502, detail="TTS provider error")

    return Response(
        content=response.content,
        media_type="audio/wav",
        headers={"Content-Disposition": "inline"},
    )

@app.post("/stt")
async def stt_endpoint(audio: UploadFile = File(...)):
    """Transcribe learner speech via the local faster-whisper sidecar.

    Runs large-v3, not small.en: the learners are non-native speakers, and heavily
    accented L2 English is precisely where the small English-only model degrades.
    """
    try:
        content = await audio.read()
        content_type = audio.content_type or "audio/wav"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                STT_URL,
                files={"file": (audio.filename or "audio.wav", content, content_type)},
                timeout=60.0,
            )
    except httpx.TimeoutException:
        logger.error("STT request timed out")
        raise HTTPException(status_code=504, detail="STT request timed out")
    except Exception as e:
        logger.error(f"STT unreachable at {STT_URL}: {e}")
        raise HTTPException(status_code=502, detail="STT service unreachable")

    if response.status_code != 200:
        logger.error(f"STT error: {response.status_code} {response.text[:200]}")
        raise HTTPException(status_code=502, detail="STT provider error")

    return {"text": response.json().get("text", "")}

if __name__ == "__main__":
    # 8013 is this repo's registered backend port (CLAUDE.md / ~/.claude/PORTS.md);
    # 8000 is SAIF's. Binds loopback by default - /tts and /stt are unauthenticated
    # relays to the local speech models, and there is no reason to expose them (or
    # the auth API) to the LAN unless explicitly asked via HOST.
    port = int(os.environ.get("PORT", 8013))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port)
