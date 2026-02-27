# Audio Configuration
AUDIO_INPUT_DEVICE = 1  # Scarlett 2i4 USB
SCARLETT_SAMPLE_RATE = 48000  # Scarlett's native sample rate
AUDIO_OUTPUT_DEVICE = 3  # USB Audio Device for output

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
DYNAMIC_SILENCE_THRESHOLD = 1.5  # Seconds of silence before stopping
DYNAMIC_MAX_DURATION = 30  # Maximum recording time (safety)
DYNAMIC_CHUNK_SIZE = 4800  # Samples per chunk (~0.1 sec at 48kHz)
DYNAMIC_ENERGY_THRESHOLD = 500  # Audio energy level to detect speech vs silence
RECORDING_DURATION = 5  # seconds to record after wake word detected
STT_ENGINE = "whisper"  # Options: "vosk" or "whisper"
VOSK_MODEL_PATH = "models/vosk-model-small-en-us-0.15"
WHISPER_MODEL_SIZE = "tiny"  # Options: "tiny", "base", "small", "medium"
WHISPER_COMPUTE_TYPE = "int8"  # Optimized for Pi CPU

# Vosk STT Tuning
CHUNK_SIZE = 4000 #samples per read (~0.1 second at 48000 Hz). More samples = more latency but better accuracy. Should be a multiple of 4000.
SILENCE_THRESHOLD = 1.5 # seconds of silence before stopping

# Piper TTS Settings
TTS_VOICE = "alan"  # Options: "amy", "lessac", "alan", "alba"
# Voice model paths
TTS_VOICES = {
    "amy": "models/piper/en_US-amy-medium.onnx",      # US Female
    "lessac": "models/piper/en_US-lessac-medium.onnx", # US Male
    "alan": "models/piper/en_GB-alan-medium.onnx",    # UK Male
    "alba": "models/piper/en_GB-alba-medium.onnx"     # UK Female
}
TTS_MODEL_PATH = TTS_VOICES[TTS_VOICE]
TTS_SPEED = 2  # 1 = normal, <1 = faster, >1 = slower
TTS_NOISE_SCALE = 0.667
TTS_NOISE_W = 0.8

# Timer Settings
TIMER_ALARM_SOUND = "sounds/no-problem.wav"
TIMER_ALARM_REPEATS = 3  # Play 3 times

# Claude Settings
# Import API key from secrets
from config.secrets import CLAUDE_API_KEY

# Claude API Configuration
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 200  # Short responses for question mode
CLAUDE_TEMPERATURE = 1.0

# Budget Settings
BUDGET_WARNING_THRESHOLD = 15.00  # USD
BUDGET_HARD_LIMIT = 20.00  # USD
BUDGET_FILE = "logs/budget.json"  # Track spending

# Query Logging
CLAUDE_QUERY_LOG = "logs/claude_queries.log"