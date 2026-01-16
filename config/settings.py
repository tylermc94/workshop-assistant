# Audio Configuration
AUDIO_DEVICE = 1  # Scarlett 2i4 USB
SCARLETT_SAMPLE_RATE = 48000
PORCUPINE_SAMPLE_RATE = 16000  # Required by Porcupine
RECORDING_DURATION = 5  # seconds to record after wake word

# Model Paths (relative to project root)
WAKE_WORD_MODEL = 'models/Hey-Forge_en_raspberry-pi_v4_0_0.ppn'
VOSK_MODEL = 'models/vosk-model-small-en-us-0.15'

# Wake Word Settings
WAKE_WORD_SENSITIVITY = 0.9  # 0.0 to 1.0, higher = more sensitive