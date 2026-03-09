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
)
import budget_tracker

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def log_query(question):
    """Log Claude queries to file for analysis"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # This is now handled by query_logger.py in intent_recognition
    # Keeping this function for backward compatibility
    pass

def ask_claude(question):
    """
    Send a question to Claude API and return the response.
    Logs the query for analysis.
    """
    logger.info(f"Sending to Claude: {question}")

    if budget_tracker.is_limit_reached():
        logger.warning("Claude API call blocked — budget hard limit reached")
        return "The Claude budget has been reached. Please check the logs."

    # Log query to file for pattern analysis
    log_query(question)

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            temperature=CLAUDE_TEMPERATURE,
            system="""You are Forge, a helpful workshop assistant. Be conversational and friendly like a helpful colleague, not robotic. 

Give concise, practical answers - just the key info needed, skip disclaimers and caveats unless critical. Respond in 1-2 sentences for simple questions, 2-3 for complex ones.

Examples:
- "What's the best temperature for PLA?" → "200 to 210 degrees Celsius works great for most PLA filaments."
- "Who won the Super Bowl?" → "The Chiefs beat the 49ers 25-22 in overtime at Super Bowl 58."

Be helpful and direct, not overly cautious.""",
            messages=[
                {"role": "user", "content": question}
            ]
        )
        
        response = message.content[0].text
        logger.info(f"Claude response: {response}")

        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        budget = budget_tracker.record_usage(input_tokens, output_tokens)

        if budget["warning"]:
            response += " Heads up — the Claude API budget is getting low."

        return response
        
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return "Sorry, I couldn't reach Claude right now. Please try again."
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return "Sorry, something went wrong."