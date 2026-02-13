import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn
import logging
from openai import OpenAI
from agent import agent_instance

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For prototype, allow all. In prod, lock this down.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI client for TTS
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI()

# Voice mapping: detective name → OpenAI voice
VOICE_MAP = {
    "Reynolds": "onyx",    # Deep, authoritative
    "Chen": "nova",        # Warm, measured
}

class ChatRequest(BaseModel):
    message: str
    session_id: str

class TTSRequest(BaseModel):
    text: str
    voice: str = "onyx"  # Default to Reynolds

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

    try:
        response = openai_client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=request.text,
            response_format="mp3",
        )

        audio_bytes = response.content

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )

    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail="TTS generation failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
