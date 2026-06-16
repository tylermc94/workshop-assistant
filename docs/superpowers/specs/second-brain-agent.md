# Second Brain Agent — Spec

## What We're Building

A new module `src/second_brain_agent.py` that replaces the `handle()` dispatch in `second_brain.py` with an Anthropic SDK tool-use agentic loop. The agent has direct read/write access to the vault and uses Claude to decide what to do with any second-brain query.

The classifier (`classify_intent()`) stays as-is. The agent only runs for CAPTURE, QUERY, and PROCESS intents.

---

## Why

The current `second_brain.py` `handle()` function is a hard-coded dispatch to specific `forge_capture` functions. It can capture, query, and process ingress — but only in the exact ways it was programmed. The agent replaces this with a general-purpose vault operator that can:

- Append notes to arbitrary project files
- Read vault context to answer questions
- Process ingress files with full awareness of vault structure
- Follow natural-language instructions about where and how to store things

---

## Architecture

### Query Flow (unchanged at the routing layer)

```
Voice / /query / /text
    → second_brain.classify_intent()     # existing 4-way classifier
    → if CAPTURE / QUERY / PROCESS:
        → second_brain_agent.run(transcript, intent)   # NEW
    → else (ANSWER):
        → intent_recognition.classify_intent()          # existing
```

Both `main.py` (voice) and `api_server.py` (`/query`, `/text`) already call `second_brain.classify_intent()` and `second_brain.handle()`. The change is: `handle()` calls `second_brain_agent.run()` instead of dispatching to forge_capture directly.

---

## The Agent

### Module: `src/second_brain_agent.py`

```python
def run(transcript: str, intent: str) -> str:
    """
    Agentic tool-use loop. Returns spoken response string.
    For PROCESS intent, schedules background work and returns "On it."
    """
```

### System Prompt

Built at module init (`_load_system_prompt`) by concatenating, in order:
1. `_BASE_SYSTEM` — behavioral instructions (concise spoken responses, git commit after writes, pull before push).
2. The vault's `CLAUDE.md` (if present) — the primary vault reference: full conventions, task format, project structure.
3. The vault's `AGENT.md` (if present) — Forge-specific additions (Forge Log location, spoken response style).
4. A path-override note pinning the vault root to this device's path (the vault `CLAUDE.md` references Windows paths).

Read failures for the vault files are non-fatal — the agent still runs with the base prompt.

### Tools

| Tool | Description |
|------|-------------|
| `read_file(path)` | Read a file from the vault. Path relative to vault root. |
| `write_file(path, content)` | Write or overwrite a file in the vault. |
| `append_file(path, content)` | Append content to a file (creates if missing). |
| `list_directory(path)` | List files/folders at a vault path. |
| `run_command(command, message)` | Run an allowlisted git command. `command` is an enum (not a raw string); `message` is required for `git_commit`. |

**git allowlist** (enum → command): `git_pull` → `git pull --rebase`, `git_add_all` → `git add -A`, `git_commit` → `git commit -m <message>`, `git_push` → `git push`

All paths are relative to `/home/tyler/second-brain/`. The tool implementations validate that paths stay within the vault root (no `../` escapes).

---

## Fast vs. Slow Operations

| Intent | Mode | Behavior |
|--------|------|----------|
| CAPTURE | Sync | Agent runs inline, returns spoken confirmation |
| QUERY | Sync | Agent runs inline, returns spoken answer |
| PROCESS | Async | Agent says "On it", background thread runs, result appended to Forge Log.md |

**Async pattern (PROCESS):**

```python
if intent == 'PROCESS':
    # Start background thread
    threading.Thread(target=_run_background, args=(transcript,), daemon=True).start()
    return "On it, I'll process that in the background."

def _run_background(transcript):
    result = _run_agent_loop(transcript, intent='PROCESS')
    _append_forge_log(result)  # writes to Forge Log.md in vault
```

**Status check:** When the user later asks "how did the ingress processing go?" or "what happened with that task?", the classifier returns QUERY. The agent reads `Forge Log.md` and summarizes the relevant recent entries.

---

## Vault AGENT.md

Create `/home/tyler/second-brain/AGENT.md` — loaded as system context. Contents:

- Vault root: `/home/tyler/second-brain/`
- Active projects: `Projects/Active/`
- Someday projects: `Projects/Someday/`
- Areas: `Areas/`
- Inbox (unrouted notes): `Inbox/`
- Ingress (files to process): `Ingress/` (processed → `Ingress/Processed/`, review → `Ingress/Needs Review/`)
- Resources: `Resources/`
- Forge Log: `Forge Log.md` — append-only audit log, use for background task results
- Project files are Markdown. Frontmatter uses `forge-target:` to specify routing target.
- After any write, run `git pull --rebase`, `git add -A`, `git commit -m "<message>"`, `git push`.

---

## Response Style

The agent's final response should be a short spoken sentence, not a markdown dump:

- "Got it, added a task to Garden Box."
- "You have three active projects: The Forge, Garden Box, and Pocket Forge."
- "On it, I'll process that in the background."
- "Done, processed the ingress file into The Forge project."

The system prompt should instruct the agent to respond as if speaking aloud — no headers, no bullet points, no markdown in the final response.

---

## Integration Points

### `second_brain.py` changes

`handle()` becomes a thin wrapper:

```python
def handle(transcript: str, intent: str = None) -> str:
    from second_brain_agent import run
    return run(transcript, intent)
```

The `classify_intent()` function stays exactly as-is.

### No changes to `main.py` or `api_server.py`

The routing is already correct. Both call `second_brain.classify_intent()` then `second_brain.handle()` — no changes needed at the pipeline layer.

### `ingress_processor.py`

The webhook-triggered `process_ingress()` in `ingress_processor.py` stays as-is for the GitHub webhook path. The agent's PROCESS handling is a parallel path triggered by voice/API, not the webhook.

---

## Files Changed

| File | Change |
|------|--------|
| `src/second_brain_agent.py` | **New** — the agentic loop |
| `src/second_brain.py` | `handle()` → thin wrapper calling agent |
| `/home/tyler/second-brain/AGENT.md` | **New** — vault context loaded as system prompt |

No changes to `main.py`, `api_server.py`, `ingress_processor.py`, or `intent_recognition.py`.

---

## Out of Scope (at original design time)

- Conversation mode (multi-turn memory across queries) — separate pending feature
- Replacing `ingress_processor.py` webhook path — leave that as-is

---

## Subsequent changes (post-original-spec)

The agent has since gained the following (see `docs/improvement/Forge-Improvement-Plan.md`):

- **Budget tracking** of its Claude calls via `budget_tracker.record_message` (was out of scope here).
- **Prompt caching** of the static tools+system prefix via a `cache_control` breakpoint on the system block.
- **Graceful error handling** in `run()` — returns a spoken fallback and resets `second_brain_status` on failure, so `handle()` is no longer a bare thin wrapper.
- **Skip `git pull` on read-only QUERY** intents (only CAPTURE/PROCESS sync the vault first).
- The vault path and model id now come from `config/settings.py` (`VAULT_PATH`, `SECOND_BRAIN_MODEL`) instead of hardcoded literals.
