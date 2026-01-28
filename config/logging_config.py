import logging
import os

def setup_logging():
    """Configure logging for the workshop assistant"""
    os.makedirs('logs', exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/workshop_assistant.log')
            # Remove StreamHandler - no console output
        ]
    )
    
    # Suppress noisy library logs
    logging.getLogger('faster_whisper').setLevel(logging.WARNING)
    logging.getLogger('onnxruntime').setLevel(logging.ERROR)