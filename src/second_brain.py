import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from config.secrets import CLAUDE_API_KEY as ANTHROPIC_API_KEY
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY  # must be before forge_capture import
sys.path.insert(0, '/home/tyler/second-brain')
import forge_capture
from pathlib import Path

# Override Windows vault path with Pi path
forge_capture.VAULT = Path('/home/tyler/second-brain')
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

INTENT_SYSTEM_PROMPT = """\
Classify the user's message as one of: CAPTURE, QUERY, ANSWER, or PROCESS.
CAPTURE = the user wants to save something (task, idea, project, note) to their second brain vault
QUERY = the user is asking a question about their vault contents, projects, or notes
PROCESS = the user wants to process a file from the Ingress folder into a project note. Examples: "process the ingress file into The Forge project", "process ingress for Pocket Forge"
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
            model="claude-sonnet-4-6",
            max_tokens=10,
            system=INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}]
        )
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
