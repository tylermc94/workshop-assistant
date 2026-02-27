import json
from datetime import datetime
from pathlib import Path

QUERY_LOG_FILE = "logs/all_queries.jsonl"  # JSON Lines format - one JSON object per line

def log_query(query, handler, response, error=None):
    """
    Log all queries with metadata
    
    Args:
        query (str): The user's question
        handler (str): Which handler processed it ("local_timer", "local_calculator", "claude", etc)
        response (str): The response given
        error (str, optional): Any error that occurred
    """
    Path("logs").mkdir(exist_ok=True)
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "handler": handler,
        "response": response,
        "error": error
    }
    
    with open(QUERY_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry) + '\n')