# Workshop Forge — Project Context

## What This Is
Workshop Forge is a voice-controlled AI assistant running on a Raspberry Pi 5 ("Lab Pi") in a home workshop. It provides hands-free help while working on projects. A companion device, Pocket Forge (Pi Zero 2W), can send queries wirelessly via HTTP API.

## Hardware
- Raspberry Pi 5 (hostname: labpi.local, user: tyler) — dedicated Forge appliance, no keyboard/mouse
- Small USB+HDMI touchscreen — displays terminal with Forge output (interim until Phase 3 GUI)
- Scarlett 2i4 audio interface
- USB speakers
- Runs as a systemd service

## Project Location
`/home/tyler/projects/workshop-assistant/`

## Tech Stack
- Python (async architecture)
- faster-whisper (tiny model) — STT
- Piper TTS (amy voice) — Text to Speech
- Claude API (`claude-sonnet-4-20250514`) via Anthropic SDK
- Porcupine wake word ("Hey Forge")
- systemd service
- FastAPI (being added) — HTTP API for remote clients

## Architecture
The main pipeline is async and mic-driven:
```
Mic → Wake Word (Porcupine) → STT (faster-whisper) → Local Skills → Claude API fallback → Piper TTS → Speaker
```

For API requests (Pocket Forge, Home Assistant, etc.):
```
WAV upload → STT (faster-whisper, shared instance) → Local Skills → Claude API fallback → Piper TTS → base64 audio response
```

## Local Skills
Local skills are checked first before forwarding to Claude. Skills include:
- Timer
- Calculator
- Calendar

## Key Design Principles
- **Local skills first, Claude as fallback** — always try local skills before hitting the API
- **Shared model instances** — Whisper and Piper are loaded once at startup, shared across voice pipeline and API
- **Async throughout** — do not introduce blocking calls into the main loop
- **Low latency is a priority** — minimize time from question to answer at every stage

## Logging
- All queries logged to `logs/all_queries.jsonl`
- Each entry includes: query, handler (local skill or claude), response, errors, source (voice or api)

## API ✅
- FastAPI server on port 8080
- Runs concurrently with voice pipeline via asyncio.gather()
- Single hardcoded API key in config/secrets.py
- Auth: `Authorization: Bearer <api_key>` header

### Endpoint
```
POST /query
Headers: Authorization: Bearer <api_key>
Body: multipart/form-data
  - audio: WAV file (16kHz mono)
Response: JSON
  {
    "transcript": "...",
    "response": "...",
    "audio": "<base64 encoded WAV>"
  }
```

## Config File
Contains API keys, model settings, budget limits, and feature flags including `api_enabled`, `api_key`, and `API_PORT`.

## Phase Roadmap
- Phase 1: ✅ Voice pipeline + local skills
- Phase 2: 🔄 Claude API (question mode ✅, HTTP API ✅, budget tracker and conversation mode pending)
- Phase 3: Touchscreen GUI — must be designed for touchscreen appliance, not desktop. Consider fullscreen pygame or browser kiosk mode served via FastAPI
- Phase 4: Notion API integration
- Phase 5: Home Assistant integration
- Phase 6-7: Pocket Forge companion integration

## Known Pending Features
- Budget tracking ($15 warning, $20 limit) — next up
- Conversation mode (multi-turn dialogue)
- Pocket Forge client integration (send WAV, receive text + audio)

## Clients That Will Use the API
- **Pocket Forge** (Pi Zero 2W) — primary companion device, sends WAV, receives text + audio
- **Home Assistant** — home automation integration (planned)
- **OctoPrint** — 3D printer integration (planned)
- **Mobile Forge** — potential phone app (planned)

## Style Conventions
- Async Python throughout
- Do not load Whisper or Piper more than once — reuse existing instances
- Follow existing patterns before introducing new libraries
- Log all queries with source field indicating origin (voice/api)

## Future Projects (Planned, Not Started)
- **Clean reinstall** — reimage Pi 5 with fresh Raspberry Pi OS, install only Forge dependencies, decommission old Lab Pi setup (shared folders etc.). Do this once Forge reaches a stable v1.0 state, not mid-development.
- **Phase 3 GUI** — design for touchscreen from the start, not a desktop app retrofit. Fullscreen pygame or a web UI served by FastAPI are the leading options.
- **Mobile Forge** — phone app client using the same FastAPI endpoint