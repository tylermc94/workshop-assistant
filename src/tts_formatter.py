import re

def format_for_speech(text):
    """Format text to sound more natural when spoken by TTS"""
    
    # Temperature ranges: 190-220°C → "190 to 220 degrees Celsius"
    text = re.sub(r'(\d+)-(\d+)°C', r'\1 to \2 degrees Celsius', text)
    text = re.sub(r'(\d+)°C', r'\1 degrees Celsius', text)
    text = re.sub(r'(\d+)°F', r'\1 degrees Fahrenheit', text)
    
    # Dimension ranges: 220x220x250mm → "220 by 220 by 250 millimeters"
    text = re.sub(r'(\d+)x(\d+)x(\d+)mm', r'\1 by \2 by \3 millimeters', text)
    text = re.sub(r'(\d+)mm', r'\1 millimeters', text)
    
    # Other common abbreviations
    text = text.replace('e.g.', 'for example')
    text = text.replace('i.e.', 'that is')
    text = text.replace('etc.', 'and so on')
    
    return text