import logging
import logging.handlers
import os

def setup_logging():
    """Configure logging for the workshop assistant"""
    os.makedirs('logs', exist_ok=True)

    # Rotate at ~10 MB, keep 5 old files (~50 MB cap total). Previously a plain
    # FileHandler let workshop_assistant.log grow unbounded (it reached 527 MB).
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.handlers.RotatingFileHandler(
                'logs/workshop_assistant.log',
                maxBytes=10_000_000,
                backupCount=5,
                encoding='utf-8',
            ),
            # Remove StreamHandler - no console output
        ]
    )
    
    # Suppress noisy library logs
    logging.getLogger('faster_whisper').setLevel(logging.WARNING)
    logging.getLogger('onnxruntime').setLevel(logging.ERROR)