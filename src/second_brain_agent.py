"""
second_brain_agent.py — Anthropic SDK tool-use agentic loop for vault operations.

Replaces the hard-coded forge_capture dispatch in second_brain.handle().
Tools: read_file, write_file, append_file, list_directory, run_command (git allowlist).
"""

import os
import sys
import threading
import subprocess
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.secrets import CLAUDE_API_KEY as ANTHROPIC_API_KEY

import anthropic

logger = logging.getLogger(__name__)

VAULT = Path('/home/tyler/second-brain')
FORGE_LOG = VAULT / 'Forge Log.md'
AGENT_MD = VAULT / 'AGENT.md'
MODEL = 'claude-sonnet-4-6'
MAX_TOKENS = 2048
MAX_TOOL_ROUNDS = 15

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_BASE_SYSTEM = """\
You are Forge, a voice-controlled workshop assistant with read/write access to the user's \
second-brain vault. You help capture notes, answer questions about vault contents, and process \
ingress files into the right projects.

Use your tools to explore the vault before writing anything. For captures, check existing \
project files so you append tasks or notes to the right place. For queries, read the relevant \
files before answering.

After any write to the vault, always run git operations in order: git_pull, git_add_all, \
git_commit (with a short descriptive message), git_push.

IMPORTANT — response style: your final text response must be one or two short spoken sentences. \
No markdown, no bullet points, no headers. Respond as if speaking aloud.\
"""


def _load_system_prompt() -> str:
    if AGENT_MD.exists():
        try:
            vault_ref = AGENT_MD.read_text(encoding='utf-8')
            return _BASE_SYSTEM + '\n\n' + vault_ref
        except Exception:
            pass
    return _BASE_SYSTEM


SYSTEM_PROMPT = _load_system_prompt()


TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the vault. Path is relative to vault root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to vault root"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the vault. Path is relative to vault root. "
                       "Prefer append_file for adding content to existing files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to vault root"},
                "content": {"type": "string", "description": "Full file content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "append_file",
        "description": "Append content to an existing file in the vault. Creates the file if it "
                       "does not exist. Use this to add tasks, notes, or sections to project files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to vault root"},
                "content": {"type": "string", "description": "Content to append"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_directory",
        "description": "List files and subdirectories at a vault path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Directory path relative to vault root. Use '.' for root."}
            },
            "required": ["path"]
        }
    },
    {
        "name": "run_command",
        "description": "Run an allowlisted git command in the vault directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["git_pull", "git_add_all", "git_commit", "git_push"],
                    "description": (
                        "git_pull = git pull --rebase | "
                        "git_add_all = git add -A | "
                        "git_commit = git commit -m <message> (requires message field) | "
                        "git_push = git push"
                    )
                },
                "message": {
                    "type": "string",
                    "description": "Commit message. Required when command is git_commit."
                }
            },
            "required": ["command"]
        }
    }
]


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_path(rel_path: str) -> Path:
    """Resolve a relative vault path, rejecting traversal attempts."""
    resolved = (VAULT / rel_path).resolve()
    if not str(resolved).startswith(str(VAULT.resolve())):
        raise ValueError(f"Path escapes vault root: {rel_path}")
    return resolved


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == 'read_file':
            p = _safe_path(inputs['path'])
            if not p.exists():
                return f"File not found: {inputs['path']}"
            return p.read_text(encoding='utf-8')

        elif name == 'write_file':
            p = _safe_path(inputs['path'])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(inputs['content'], encoding='utf-8')
            return f"Written: {inputs['path']}"

        elif name == 'append_file':
            p = _safe_path(inputs['path'])
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, 'a', encoding='utf-8') as f:
                f.write(inputs['content'])
            return f"Appended to: {inputs['path']}"

        elif name == 'list_directory':
            p = _safe_path(inputs['path'])
            if not p.exists():
                return f"Directory not found: {inputs['path']}"
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            lines = [f"{'DIR ' if e.is_dir() else 'FILE'} {e.name}" for e in entries]
            return '\n'.join(lines) or '(empty)'

        elif name == 'run_command':
            cmd = inputs['command']
            if cmd == 'git_pull':
                args = ['git', 'pull', '--rebase']
            elif cmd == 'git_add_all':
                args = ['git', 'add', '-A']
            elif cmd == 'git_commit':
                msg = inputs.get('message', 'forge: update vault')
                args = ['git', 'commit', '-m', msg]
            elif cmd == 'git_push':
                args = ['git', 'push']
            else:
                return f"Unknown command: {cmd}"

            result = subprocess.run(
                args, cwd=str(VAULT), capture_output=True, text=True
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                return output or 'OK'
            # Non-zero exit — return stderr so Claude can decide what to do
            return f"Exit {result.returncode}: {output}"

        return f"Unknown tool: {name}"

    except Exception as e:
        logger.error(f"Tool error ({name}): {e}", exc_info=True)
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _run_agent_loop(transcript: str, intent: str) -> str:
    """Run the tool-use loop and return a final spoken response string."""
    messages = [{"role": "user", "content": transcript}]

    for round_num in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )
        logger.debug(f"Agent round {round_num + 1}: stop_reason={response.stop_reason}")

        tool_calls = [b for b in response.content if b.type == 'tool_use']
        text_blocks = [b for b in response.content if b.type == 'text']

        if not tool_calls:
            # No more tool calls — return the final text
            if text_blocks:
                return text_blocks[-1].text.strip()
            return "Done."

        # Append assistant message with tool calls
        messages.append({"role": "assistant", "content": response.content})

        # Execute all tool calls and collect results
        tool_results = []
        for tc in tool_calls:
            logger.info(f"Tool call: {tc.name}({tc.input})")
            result = _execute_tool(tc.name, tc.input)
            logger.debug(f"Tool result ({tc.name}): {result[:200]}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result
            })

        messages.append({"role": "user", "content": tool_results})

    logger.warning("Agent hit MAX_TOOL_ROUNDS without finishing")
    return "Sorry, I ran out of steps before finishing that task."


# ---------------------------------------------------------------------------
# Background task support
# ---------------------------------------------------------------------------

def _append_forge_log(message: str) -> None:
    """Append a background task result to Forge Log.md."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    section = f"\n## {now}\n- {message}\n"
    try:
        if not FORGE_LOG.exists():
            FORGE_LOG.write_text(f"# Forge Log\n{section}", encoding='utf-8')
        else:
            with open(FORGE_LOG, 'a', encoding='utf-8') as f:
                f.write(section)
    except Exception as e:
        logger.error(f"Failed to write Forge Log: {e}")


def _run_background(transcript: str) -> None:
    try:
        result = _run_agent_loop(transcript, 'PROCESS')
        _append_forge_log(result)
        logger.info(f"Background task complete: {result}")
    except Exception as e:
        logger.error(f"Background agent error: {e}", exc_info=True)
        _append_forge_log(f"Error during background processing: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(transcript: str, intent: str = None) -> str:
    """
    Run the second-brain agent. Returns a spoken response string.

    CAPTURE / QUERY — runs synchronously, returns answer inline.
    PROCESS         — fires a background thread, returns "On it" immediately.
    """
    if intent == 'PROCESS':
        threading.Thread(
            target=_run_background,
            args=(transcript,),
            daemon=True
        ).start()
        return "On it, I'll process that in the background."

    return _run_agent_loop(transcript, intent or 'CAPTURE')
