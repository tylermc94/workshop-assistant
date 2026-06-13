import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from config.secrets import CLAUDE_API_KEY as ANTHROPIC_API_KEY
from config.settings import VAULT_PATH, SECOND_BRAIN_MODEL
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY  # must be before forge_capture import
sys.path.insert(0, VAULT_PATH)
import forge_capture
from pathlib import Path

# Override Windows vault path with Pi path
forge_capture.VAULT = Path(VAULT_PATH)
forge_capture.PROJECTS_DIR = forge_capture.VAULT / "Projects"
forge_capture.ACTIVE_DIR   = forge_capture.VAULT / "Projects" / "Active"
forge_capture.SOMEDAY_DIR  = forge_capture.VAULT / "Projects" / "Someday"
forge_capture.AREAS_DIR    = forge_capture.VAULT / "Areas"
forge_capture.INBOX_DIR    = forge_capture.VAULT / "Inbox"
forge_capture.RESOURCES_DIR = forge_capture.VAULT / "Resources"
forge_capture.INGRESS_DIR = forge_capture.VAULT / "Ingress"
forge_capture.INGRESS_PROCESSED_DIR = forge_capture.VAULT / "Ingress" / "Processed"

import anthropic
forge_capture.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

import asyncio
import budget_tracker

INTENT_SYSTEM_PROMPT = """\
Classify the user's message as one of: CAPTURE, QUERY, ANSWER, or PROCESS.
CAPTURE = the user wants to add a quick note, task, or idea to an existing project or inbox (simple, fast append)
QUERY = the user is asking a question about their vault contents, projects, or notes
PROCESS = the user wants complex multi-step vault work: creating a new project file, processing ingress files, reorganizing notes, or anything that requires reading multiple files and writing structured content
ANSWER = general question not related to the vault
Respond with exactly one word: CAPTURE, QUERY, ANSWER, or PROCESS."""


async def classify_intent(transcript: str) -> str:
    """
    Returns 'CAPTURE', 'QUERY', 'ANSWER', or 'PROCESS'.
    CAPTURE = save something to vault
    QUERY = ask a question about vault contents
    PROCESS = process a file from Ingress into a project note
    ANSWER = normal Claude response, do not touch vault
    """
    try:
        response = await asyncio.to_thread(
            forge_capture.client.messages.create,
            model=SECOND_BRAIN_MODEL,
            max_tokens=10,
            system=INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}]
        )
        budget_tracker.record_message(response)  # track vault spend (visibility only)
        result = response.content[0].text.strip().upper()
        if result in ('CAPTURE', 'QUERY', 'ANSWER', 'PROCESS'):
            return result
        return 'ANSWER'
    except Exception:
        return 'ANSWER'


def handle(transcript: str, intent: str = None) -> str:
    """
    Called by the voice pipeline when classify_intent returns CAPTURE, QUERY, or PROCESS.
    Delegates to the second_brain_agent agentic loop.
    Returns a spoken response string.
    """
    from second_brain_agent import run
    return run(transcript, intent)
