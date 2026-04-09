import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import logging
from config.settings import API_KEY, API_PORT
import speech_to_text
import intent_recognition
import audio_utils

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Workshop Forge API",
    description="Voice query API for Workshop Forge assistant",
    version="1.0.0"
)

# Add CORS middleware for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security scheme
security = HTTPBearer()

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify the API key from Authorization header"""
    if credentials.credentials != API_KEY:
        logger.warning(f"Invalid API key attempt: {credentials.credentials}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return credentials.credentials

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Workshop Forge API is running"}

@app.get("/health")
async def health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "service": "workshop-forge-api",
        "version": "1.0.0"
    }

@app.post("/query")
async def process_query(
    audio: UploadFile = File(...),
    api_key: str = Depends(verify_api_key)
):
    """
    Process audio query and return transcript, response, and TTS audio.

    Args:
        audio: WAV file uploaded via multipart/form-data

    Returns:
        JSON response with transcript, response text, and base64 audio
    """
    logger.info(f"Received API query from audio file: {audio.filename}")

    # Validate audio file
    if not audio.filename.lower().endswith(('.wav', '.wave')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file must be in WAV format"
        )

    try:
        # Read uploaded audio file
        audio_bytes = await audio.read()
        logger.info(f"Read {len(audio_bytes)} bytes of audio data")

        # Convert audio to numpy array for STT
        audio_array = audio_utils.wav_bytes_to_numpy(audio_bytes)

        # Transcribe using existing Whisper model
        transcript = await asyncio.to_thread(
            speech_to_text._transcribe_with_whisper,
            audio_array
        )
        logger.info(f"Transcribed: {transcript}")

        if not transcript.strip():
            return {
                "transcript": "",
                "response": "I didn't hear anything. Could you try again?",
                "audio": ""
            }

        # Process through existing intent recognition pipeline
        response_text = await intent_recognition.classify_intent(transcript, source="api")
        logger.info(f"Intent response: {response_text}")

        # Generate TTS audio
        audio_base64 = await asyncio.to_thread(
            audio_utils.text_to_audio_base64,
            response_text
        )

        return {
            "transcript": transcript,
            "response": response_text,
            "audio": audio_base64
        }

    except Exception as e:
        logger.error(f"Error processing audio query: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing audio: {str(e)}"
        )

async def start_api_server():
    """Start the FastAPI server"""
    import uvicorn

    logger.info(f"Starting FastAPI server on port {API_PORT}")

    # Configure uvicorn
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=API_PORT,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)

    # Start the server
    await server.serve()