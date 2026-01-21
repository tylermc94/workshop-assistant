import logging
import os

def setup_logging():
    """Configure logging for the workshop assistant"""
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/workshop_assistant.log'),
            logging.StreamHandler()  # Also print to console
        ]
    )