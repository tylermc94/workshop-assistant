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

# Vosk STT Settings
USE_DYNAMIC_RECORDING = False  # If True, use dynamic recording until silence detected. If False, use RECORDING_DURATION to set fixed recording time.
RECORDING_DURATION = 5  # seconds to record after wake word detected

# Vosk STT Tuning
CHUNK_SIZE = 4000 #samples per read (~0.1 second at 48000 Hz). More samples = more latency but better accuracy. Should be a multiple of 4000.
SILENCE_THRESHOLD = 1.5 # seconds of silence before stopping

# Piper TTS Settings
TTS_MODEL_PATH = "models/piper/en_US-amy-medium.onnx"
TTS_SPEED = 1.0  # 1.0 = normal, <1 = faster, >1 = slower
TTS_NOISE_SCALE = 0.667
TTS_NOISE_W = 0.8