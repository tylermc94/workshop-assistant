import sys
import os
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import logging
from datetime import datetime
from pathlib import Path
from config.settings import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    CLAUDE_TEMPERATURE,
    CONVERSATION_TIMEOUT,
    CONVERSATION_MAX_TURNS,
    CLAUDE_QUERY_LOG,
)
import budget_tracker

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

_history = {"voice": [], "api": []}
_last_exchange = {"voice": 0.0, "api": 0.0}

def clear_history(source="voice"):
    logger.info(f"[DEBUG] clear_history called for source={source!r}, history before clear: {_history[source]}")
    _history[source].clear()
    _last_exchange[source] = 0.0
    logger.info(f"[DEBUG] clear_history done, history after clear: {_history[source]}")

def log_query(question):
    """Log Claude queries to claude_queries.log for analysis"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    Path("logs").mkdir(exist_ok=True)
    with open(CLAUDE_QUERY_LOG, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} | {question}\n")

def ask_claude(question, source="voice"):
    """
    Send a question to Claude API and return the response.
    Logs the query for analysis.
    """
    logger.info(f"Sending to Claude: {question}")

    if budget_tracker.is_limit_reached():
        logger.warning("Claude API call blocked — budget hard limit reached")
        return "The Claude budget has been reached. Please check the logs."

    now = time.monotonic()
    if _last_exchange[source] and (now - _last_exchange[source]) > CONVERSATION_TIMEOUT:
        logger.info(f"Conversation timeout for {source}, clearing history")
        clear_history(source)

    # Log query to file for pattern analysis
    log_query(question)

    messages_to_send = _history[source] + [{"role": "user", "content": question}]
    logger.info(f"[DEBUG] ask_claude source={source!r}, history_len={len(_history[source])}, messages_to_send={messages_to_send}")

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
            messages=messages_to_send,
        )
        
        response = message.content[0].text
        logger.info(f"Claude response: {response}")

        _history[source].append({"role": "user", "content": question})
        _history[source].append({"role": "assistant", "content": response})
        if len(_history[source]) > CONVERSATION_MAX_TURNS * 2:
            del _history[source][:2]
        _last_exchange[source] = time.monotonic()

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