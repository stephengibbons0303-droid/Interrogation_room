import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
import logging
import httpx
from openai import OpenAI
from agent import agent_instance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI client for TTS
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI()

# Deepgram API key for STT
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

VOICE_MAP = {
    "Reynolds": "onyx",
    "Chen": "nova",
}

class ChatRequest(BaseModel):
    message: str
    session_id: str

class TTSRequest(BaseModel):
    text: str
    voice: str = "onyx"

@app.get("/")
async def root():
    return {"status": "ok", "service": "Interrogation Learning System Backend"}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info(f"Received message: {request.message} from session: {request.session_id}")
    response = agent_instance.process_message(request.message)
    return response

@app.post("/tts")
async def tts_endpoint(request: TTSRequest):
    if not openai_client:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    voice = VOICE_MAP.get(request.voice, request.voice)

    def stream_audio():
        try:
            with openai_client.audio.speech.with_streaming_response.create(
                model="tts-1",
                voice=voice,
                input=request.text,
                response_format="mp3",
            ) as response:
                yield from response.iter_bytes(chunk_size=4096)
        except Exception as e:
            logger.error(f"TTS streaming error: {e}")

    return StreamingResponse(
        stream_audio(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline"},
    )

@app.post("/stt")
async def stt_endpoint(audio: UploadFile = File(...)):
    if not DEEPGRAM_API_KEY:
        raise HTTPException(status_code=503, detail="Deepgram API key not configured")

    try:
        content = await audio.read()
        content_type = audio.content_type or "audio/wav"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                params={
                    "model": "nova-2",
                    "language": "en",
                    "smart_format": "true",
                },
                headers={
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": content_type,
                },
                content=content,
                timeout=10.0,
            )

        if response.status_code != 200:
            logger.error(f"Deepgram error: {response.status_code} {response.text}")
            raise HTTPException(status_code=502, detail="STT provider error")

        data = response.json()
        transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]

        return {"text": transcript}

    except httpx.TimeoutException:
        logger.error("Deepgram request timed out")
        raise HTTPException(status_code=504, detail="STT request timed out")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"STT error: {e}")
        raise HTTPException(status_code=500, detail="Speech-to-text failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
