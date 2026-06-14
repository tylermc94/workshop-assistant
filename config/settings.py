# Audio Configuration
# Devices are resolved BY NAME at runtime (see src/audio_devices.py) so a USB
# re-plug / reboot that renumbers indices doesn't break capture or playback.
# The numeric values below are fallbacks used only if the name isn't found.
AUDIO_INPUT_DEVICE = 1  # Scarlett 2i4 USB (PortAudio index fallback)
AUDIO_INPUT_NAME = "Scarlett"  # substring matched against capture device names
SCARLETT_SAMPLE_RATE = 48000  # Scarlett's native sample rate
AUDIO_OUTPUT_DEVICE = 3  # USB speakers (ALSA card index fallback)
AUDIO_OUTPUT_NAME = "USB PnP Audio Device"  # substring matched against ALSA card names

# Model Paths (relative to project root)
WAKE_WORD_MODEL = 'models/Hey-Forge_en_raspberry-pi_v4_0_0.ppn' # Porcupine wake word model path
VOSK_MODEL = 'models/vosk-model-small-en-us-0.15'  # Vosk speech-to-text model path

# Wake Word Settings
PORCUPINE_SAMPLE_RATE = 16000  # Required by Porcupine

# Wake Word Tuning
WAKE_WORD_SENSITIVITY = 0.9  # 0.0 to 1.0, higher = more sensitive

#STT Settings
# Dynamic Recording Settings
USE_DYNAMIC_RECORDING = True  # Toggle between fixed and dynamic
DYNAMIC_SILENCE_THRESHOLD = 2.5  # Seconds of silence before stopping (raise = more pause tolerance, less laggy when lower)
DYNAMIC_MAX_DURATION = 30  # Maximum recording time (safety)
DYNAMIC_CHUNK_SIZE = 4800  # Samples per chunk (~0.1 sec at 48kHz)
DYNAMIC_ENERGY_THRESHOLD = 350  # Below this a chunk counts as silence. Lower = quieter speech still counts as talking (less early cutoff); too low and background noise prevents it ever stopping.
RECORDING_DURATION = 5  # seconds to record after wake word detected
STT_ENGINE = "whisper"  # Options: "vosk" or "whisper"
VOSK_MODEL_PATH = "models/vosk-model-small-en-us-0.15"
WHISPER_MODEL_SIZE = "tiny"  # Options: "tiny", "base", "small", "medium"
WHISPER_COMPUTE_TYPE = "int8"  # Optimized for Pi CPU

# Vosk STT Tuning
CHUNK_SIZE = 4000 #samples per read (~0.1 second at 48000 Hz). More samples = more latency but better accuracy. Should be a multiple of 4000.
SILENCE_THRESHOLD = 1.5 # seconds of silence before stopping

# Piper TTS Settings
TTS_VOICE = "alba"  # Options: "amy", "lessac", "alan", "alba"
# Voice model paths
TTS_VOICES = {
    "amy": "models/piper/en_US-amy-medium.onnx",      # US Female
    "lessac": "models/piper/en_US-lessac-medium.onnx", # US Male
    "alan": "models/piper/en_GB-alan-medium.onnx",    # UK Male
    "alba": "models/piper/en_GB-alba-medium.onnx"     # UK Female
}
TTS_MODEL_PATH = TTS_VOICES[TTS_VOICE]
# (TTS_SPEED / TTS_NOISE_SCALE / TTS_NOISE_W were declared here but never wired
# into Piper — removed to avoid misleading dead knobs. To tune the voice later,
# pass a piper SynthesisConfig to PiperVoice.synthesize in text_to_speech.py.)

# Timer Settings
TIMER_ALARM_SOUND = "sounds/no-problem.wav"
TIMER_ALARM_REPEATS = 3  # Play 3 times

# Claude Settings
# Import API key from secrets
from config.secrets import CLAUDE_API_KEY

# API Settings
from config.secrets import API_KEY

# Claude API Configuration
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 200  # Short responses for question mode
CLAUDE_TEMPERATURE = 1.0

# Web search (server-side tool) for time-sensitive questions on the ANSWER path.
# OFF by default — it adds latency and a per-search fee on top of token cost.
# Flip to True to let Forge look things up (current events, prices, versions).
WEB_SEARCH_ENABLED = False
WEB_SEARCH_MAX_CONTINUATIONS = 3  # cap server-tool pause_turn loops so cost can't run away

# Second Brain / Vault
# Centralized here so the path and model aren't duplicated across the vault
# modules (second_brain.py, second_brain_agent.py, ingress_processor.py).
# NOTE: forge_capture.py lives in the vault itself and is not part of this repo,
# so its own hardcoded model id can only be changed there.
VAULT_PATH = "/home/tyler/second-brain"
SECOND_BRAIN_MODEL = "claude-sonnet-4-6"

# Budget Settings
BUDGET_WARNING_THRESHOLD = 15.00  # USD
BUDGET_HARD_LIMIT = 20.00  # USD
BUDGET_FILE = "logs/budget.json"  # Track spending

# Claude Pricing (USD per million tokens)
CLAUDE_INPUT_PRICE_PER_MTOK = 3.00
CLAUDE_OUTPUT_PRICE_PER_MTOK = 15.00

# Conversation Mode
CONVERSATION_TIMEOUT = 120      # seconds of Claude-turn inactivity before history resets
CONVERSATION_MAX_TURNS = 10     # max user+assistant pairs to retain

# Query Logging
CLAUDE_QUERY_LOG = "logs/claude_queries.log"

# API Configuration
API_ENABLED = True
API_PORT = 8080

# Home Assistant
HA_URL = "http://homeassistant.local:8123"
# Network card — the old UniFi/Dream Machine entities were removed from HA
# (migrated to OPNsense, which isn't integrated into HA yet). Empty = the NETWORK
# card is hidden. When OPNsense/Grafana is wired into HA, list its WAN latency /
# clients / device-state entities here and the card comes back automatically.
HA_UNIFI_ENTITIES = []
# Power card — the old `workshop_power` device no longer exists in HA. Empty =
# the ENERGY/POWER cards are hidden. To re-enable, fill in a power-metered
# device's entities, e.g. for the `network_power` plug:
#   "switch.network_power", "sensor.network_power_power",
#   "sensor.network_power_summation_delivered", "sensor.network_power_voltage",
#   "binary_sensor.<device>_overloaded"
# (and update the hardcoded ids in api_server._fetch_sensors_data to match).
HA_POWER_ENTITIES = []
HA_OUTLET_ENTITIES = [
    "switch.workshop_light_1",
    "switch.workshop_light_2",
    "switch.tp_link_power_strip_503c_exhaust_fan",
    "switch.tp_link_power_strip_503c_plug_2",
    "switch.tp_link_power_strip_503c_plug_3",
]
HA_OCTOPRINT_ENTITIES = [
    "binary_sensor.octoprint_printing",
    "sensor.octoprint_job_percentage",
    "sensor.octoprint_current_state",
    "sensor.octoprint_current_file",
    "sensor.octoprint_estimated_finish_time",
    "sensor.octoprint_actual_bed_temp",
    "sensor.octoprint_actual_tool0_temp",
]