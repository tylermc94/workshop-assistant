import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from fastapi import FastAPI, HTTPException, Depends, File, Request, UploadFile, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import hashlib
import hmac
import logging
from config.settings import API_KEY, API_PORT, HA_URL, HA_UNIFI_ENTITIES, HA_POWER_ENTITIES, HA_OUTLET_ENTITIES, HA_OCTOPRINT_ENTITIES
import speech_to_text
import intent_recognition
import audio_utils
import forge_state
from second_brain import classify_intent, handle as second_brain_handle
import ingress_processor

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Workshop Forge API",
    description="Voice query API for Workshop Forge assistant",
    version="1.0.0"
)

# Mount static files
_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

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

def _ha_request(path: str, token: str):
    """Make a single HA API request, return parsed JSON or None."""
    import urllib.request
    import json as _json
    try:
        req = urllib.request.Request(
            f"{HA_URL}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return _json.loads(resp.read())
    except Exception as e:
        logger.warning(f"HA request failed for {path}: {e}")
        return None


def _fetch_sensors_data() -> dict:
    """Fetch all sensor data + 12h history synchronously (run in thread)."""
    from datetime import datetime, timedelta, timezone
    import json as _json

    try:
        import config.secrets as _secrets
        token = getattr(_secrets, 'HA_TOKEN', '')
    except Exception:
        token = ''

    # --- Current states ---
    all_entities = (
        ["sensor.workshop_temp_humidity_temperature", "sensor.workshop_temp_humidity_humidity"]
        + HA_UNIFI_ENTITIES
        + HA_POWER_ENTITIES
        + HA_OUTLET_ENTITIES
        + HA_OCTOPRINT_ENTITIES
    )
    states = {}
    for eid in all_entities:
        data = _ha_request(f"/api/states/{eid}", token)
        if data:
            states[eid] = {
                "state": data.get("state"),
                "name":  data.get("attributes", {}).get("friendly_name", eid),
                "unit":  data.get("attributes", {}).get("unit_of_measurement", ""),
            }
        else:
            states[eid] = {"state": "unavailable", "name": eid, "unit": ""}

    # --- 12h history for temp, humidity, and power draw ---
    start = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    history_entities = ",".join([
        "sensor.workshop_temp_humidity_temperature",
        "sensor.workshop_temp_humidity_humidity",
        "sensor.workshop_power_current_consumption",
        "sensor.dream_machine_cloudflare_wan_latency",
        "sensor.dream_machine_google_wan_latency",
        "sensor.dream_machine_microsoft_wan_latency",
    ])
    history_data = _ha_request(
        f"/api/history/period/{start}?filter_entity_id={history_entities}"
        f"&minimal_response=true&no_attributes=true",
        token
    ) or []

    def sample_history(series, n=24):
        """Downsample a history series to n numeric values."""
        points = []
        for entry in series:
            try:
                points.append(float(entry["state"]))
            except (ValueError, KeyError):
                pass
        if len(points) <= n:
            return points
        step = len(points) / n
        return [points[int(i * step)] for i in range(n)]

    temp_history  = []
    hum_history   = []
    power_history = []
    cf_history    = []
    google_history = []
    ms_history    = []
    for series in history_data:
        if not series:
            continue
        eid = series[0].get("entity_id") or ""
        if "temperature" in eid and "humidity" not in eid:
            temp_history = sample_history(series)
        elif "humidity" in eid:
            hum_history = sample_history(series)
        elif "current_consumption" in eid:
            power_history = sample_history(series)
        elif "cloudflare" in eid:
            cf_history = sample_history(series)
        elif "google_wan" in eid:
            google_history = sample_history(series)
        elif "microsoft" in eid:
            ms_history = sample_history(series)

    # --- Build response ---
    temp = states.get("sensor.workshop_temp_humidity_temperature", {})
    hum  = states.get("sensor.workshop_temp_humidity_humidity", {})

    octo_printing   = states.get("binary_sensor.octoprint_printing", {}).get("state") == "on"
    octo_pct        = states.get("sensor.octoprint_job_percentage", {}).get("state", "0")
    octo_state      = states.get("sensor.octoprint_current_state", {}).get("state", "unknown")
    octo_file       = states.get("sensor.octoprint_current_file", {}).get("state", "")
    octo_finish     = states.get("sensor.octoprint_estimated_finish_time", {}).get("state")
    octo_bed_temp   = states.get("sensor.octoprint_actual_bed_temp", {}).get("state")
    octo_nozzle_temp = states.get("sensor.octoprint_actual_tool0_temp", {}).get("state")

    outlets = []
    for eid in HA_OUTLET_ENTITIES:
        s = states.get(eid, {})
        name = s.get("name", eid)
        for prefix in ["TP-LINK_Power Strip_503C ", "TP-Link Power Strip 503C "]:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        outlets.append({"entity_id": eid, "name": name, "on": s.get("state") == "on"})

    def _speed(s):
        """Format KiB/s to a readable string."""
        try:
            kib = float(s)
            if kib >= 1024:
                return f"{kib/1024:.1f} MiB/s"
            return f"{kib:.0f} KiB/s"
        except (TypeError, ValueError):
            return "—"

    unifi_clients   = states.get("sensor.dream_machine_clients", {})
    unifi_cf_lat    = states.get("sensor.dream_machine_cloudflare_wan_latency", {})
    unifi_google_lat = states.get("sensor.dream_machine_google_wan_latency", {})
    unifi_ms_lat    = states.get("sensor.dream_machine_microsoft_wan_latency", {})
    udm_state         = states.get("sensor.dream_machine_state", {}).get("state", "")
    u6_pro_state      = states.get("sensor.u6_pro_state", {}).get("state", "")
    u6_mesh_state     = states.get("sensor.u6_mesh_state", {}).get("state", "")
    usw_lite_state    = states.get("sensor.usw_lite_8_poe_state", {}).get("state", "")
    usw_flex_state    = states.get("sensor.usw_flex_mini_state", {}).get("state", "")

    pwr_on       = states.get("switch.workshop_power", {}).get("state") == "on"
    pwr_watts    = states.get("sensor.workshop_power_current_consumption", {})
    pwr_today    = states.get("sensor.workshop_power_today_s_consumption", {})
    pwr_voltage  = states.get("sensor.workshop_power_voltage", {})
    pwr_overload = states.get("binary_sensor.workshop_power_overloaded", {}).get("state") == "on"

    return {
        "unifi": {
            "cf_latency":     unifi_cf_lat.get("state", "—"),
            "cf_history":     cf_history,
            "google_latency": unifi_google_lat.get("state", "—"),
            "google_history": google_history,
            "ms_latency":     unifi_ms_lat.get("state", "—"),
            "ms_history":     ms_history,
            "latency_unit":   unifi_google_lat.get("unit", "ms"),
            "clients":        unifi_clients.get("state", "—"),
            "udm":            udm_state == "connected",
            "u6_pro":         u6_pro_state == "connected",
            "u6_mesh":        u6_mesh_state == "connected",
            "usw_lite":       usw_lite_state == "connected",
            "usw_flex":       usw_flex_state == "connected",
        },
        "temperature": {"value": temp.get("state", "—"), "unit": temp.get("unit", "°F"), "history": temp_history},
        "humidity":    {"value": hum.get("state",  "—"), "unit": hum.get("unit",  "%"),  "history": hum_history},
        "power": {
            "on":       pwr_on,
            "watts":    pwr_watts.get("state", "—"),
            "today_kwh": pwr_today.get("state", "—"),
            "voltage":  pwr_voltage.get("state", "—"),
            "overloaded": pwr_overload,
            "history":  power_history,
        },
        "octoprint": {
            "printing":     octo_printing,
            "state":        octo_state,
            "job_pct":      octo_pct,
            "file":         octo_file,
            "finish_time":  None if octo_finish in (None, "unknown") else octo_finish,
            "bed_temp":     None if octo_bed_temp in (None, "unknown", "unavailable") else octo_bed_temp,
            "nozzle_temp":  None if octo_nozzle_temp in (None, "unknown", "unavailable") else octo_nozzle_temp,
        },
        "outlets": outlets,
    }


@app.get("/sensors")
async def get_sensors():
    """Fetch live sensor data from Home Assistant."""
    return await asyncio.to_thread(_fetch_sensors_data)


@app.get("/status")
async def get_status():
    """Return current Forge pipeline state for the UI"""
    return forge_state.state

@app.get("/")
async def root():
    """Serve the touchscreen UI"""
    static_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html")
    return FileResponse(static_path, headers={"Cache-Control": "no-store"})

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

        # Check second brain intent first
        intent = await classify_intent(transcript)
        if intent in ('CAPTURE', 'QUERY', 'PROCESS'):
            response_text = await asyncio.to_thread(second_brain_handle, transcript, intent)
        else:
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

class TextQuery(BaseModel):
    text: str

@app.post("/text")
async def process_text(
    body: TextQuery,
    api_key: str = Depends(verify_api_key)
):
    """
    Process a text query and return response and TTS audio (no STT step).

    Args:
        body: JSON body with a "text" field

    Returns:
        JSON response with transcript, response text, and base64 audio
    """
    transcript = body.text.strip()
    logger.info(f"Received text query: {transcript}")

    if not transcript:
        return {
            "transcript": "",
            "response": "I didn't receive any text. Could you try again?",
            "audio": ""
        }

    try:
        # Check second brain intent first
        intent = await classify_intent(transcript)
        if intent in ('CAPTURE', 'QUERY', 'PROCESS'):
            response_text = await asyncio.to_thread(second_brain_handle, transcript, intent)
        else:
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
        logger.error(f"Error processing text query: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing text: {str(e)}"
        )

@app.post("/webhook/ingress")
async def webhook_ingress(request: Request):
    """
    GitHub webhook endpoint for Ingress folder processing.
    Validates X-Hub-Signature-256 if GITHUB_WEBHOOK_SECRET is configured.
    Triggers process_ingress() in a background thread and returns immediately.
    """
    import config.secrets as _secrets
    webhook_secret = getattr(_secrets, 'GITHUB_WEBHOOK_SECRET', None)

    if webhook_secret:
        sig_header = request.headers.get('X-Hub-Signature-256', '')
        body = await request.body()
        expected = 'sha256=' + hmac.new(
            key=webhook_secret.encode('utf-8'),
            msg=body,
            digestmod=hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

    asyncio.create_task(asyncio.to_thread(ingress_processor.process_ingress))
    return {"status": "processing"}


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