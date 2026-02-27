import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import logging
from datetime import datetime
from config.settings import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    CLAUDE_TEMPERATURE,
    CLAUDE_QUERY_LOG
)

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def ask_claude(question):
    """
    Send a question to Claude API and return the response.
    Logs the query for analysis.
    """
    logger.info(f"Sending to Claude: {question}")
    
    # Log query to file for pattern analysis
    log_query(question)
    
    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            temperature=CLAUDE_TEMPERATURE,
            system="You are a helpful workshop assistant. Give concise, direct answers in 2-3 sentences maximum. Be brief and practical.",
            messages=[
                {"role": "user", "content": question}
            ]
        )
        
        response = message.content[0].text
        logger.info(f"Claude response: {response}")
        
        # TODO: Track token usage for budget
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        logger.info(f"Tokens used - Input: {input_tokens}, Output: {output_tokens}")
        
        return response
        
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return "Sorry, I couldn't reach Claude right now. Please try again."
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return "Sorry, something went wrong."

def log_query(question):
    """Log Claude queries to file for analysis"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(CLAUDE_QUERY_LOG, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} | {question}\n")