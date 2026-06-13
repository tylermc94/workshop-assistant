# Vault Integration — Improvement Report (Phase B)

**Subject owner:** Vault / second-brain subsystem
**Files owned:** `src/second_brain.py`, `src/second_brain_agent.py`, `src/forge_capture.py`,
`src/ingress_processor.py`, spec `docs/superpowers/specs/second-brain-agent.md`
**Scope boundary:** I pick up *after* a command has been classified as a vault action
(CAPTURE / QUERY / PROCESS). I do **not** touch intent classification routing in `main.py` /
`api_server.py` (Intent & LLM lane) nor the ANSWER-path Claude call (`claude_integration.py`).
Note: `second_brain.classify_intent()` physically lives in a file I own, so I describe it but
defer any change to the Intent & LLM agent (see Dependencies).

All line numbers verified against current source on 2026-06-13.

---

## 1. Current state

### 1.1 Entry & path wiring (`second_brain.py`)
- On import (`second_brain.py:3-23`) the module: reconfigures stdout/stderr to UTF-8;
  pulls `CLAUDE_API_KEY` from `config.secrets` and exports it as `ANTHROPIC_API_KEY` into the
  environment (line 6, *before* the `forge_capture` import so `forge_capture` can read it);
  inserts the hardcoded path `/home/tyler/second-brain` onto `sys.path` (line 7); imports
  `forge_capture`; then overrides all of `forge_capture`'s vault-path globals
  (`VAULT`, `PROJECTS_DIR`, `ACTIVE_DIR`, …) from the Windows default to the Pi path
  (lines 12-20); and finally rebinds `forge_capture.client` to a fresh Anthropic client
  (line 23).
- `classify_intent(transcript)` (lines 36-57) — 4-way classifier (`CAPTURE | QUERY | ANSWER |
  PROCESS`) via `claude-sonnet-4-6`, `max_tokens=10`, defaulting to `ANSWER` on any failure or
  unexpected output. Runs the blocking SDK call through `asyncio.to_thread`.
- `handle(transcript, intent=None)` (lines 60-67) — thin wrapper that imports and calls
  `second_brain_agent.run`. Matches the spec exactly (`second-brain-agent.md:135-141`).

### 1.2 The agent (`second_brain_agent.py`)
- Constants (lines 24-29): `VAULT = /home/tyler/second-brain` (hardcoded), `FORGE_LOG`,
  `AGENT_MD`, `MODEL = 'claude-sonnet-4-6'` (hardcoded), `MAX_TOKENS = 2048`,
  `MAX_TOOL_ROUNDS = 15`.
- `SYSTEM_PROMPT` is built once at import (`_load_system_prompt`, lines 51-76): a `_BASE_SYSTEM`
  block (lines 33-48) plus the vault's `CLAUDE.md` and `AGENT.md` if present, plus a hardcoded
  path-override note. Failures to read those files are silently swallowed (`except: pass`,
  lines 59-60, 66-67).
- `TOOLS` (lines 79-153): `read_file`, `write_file`, `append_file`, `list_directory`,
  `run_command` (the last constrained to a git enum: `git_pull`, `git_add_all`, `git_commit`,
  `git_push`).
- `_safe_path(rel_path)` (lines 160-165): resolves `VAULT / rel_path` and rejects the result if
  it does not `str.startswith(str(VAULT.resolve()))`.
- `_execute_tool(name, inputs)` (lines 172-228): dispatches the tools; git enum is mapped to
  argv and run with `subprocess.run(..., cwd=VAULT)`. Tool exceptions are caught, logged, and
  returned as `"Error: ..."` strings back to Claude (lines 226-228).
- Framework-enforced git: `_git_pull()` (lines 235-244) before the loop and `_git_push()`
  (lines 247-262) after, *in addition to* whatever git tools the model chooses. `_git_push`
  does an unconditional `git add -A` + commit + push.
- `_run_agent_loop(transcript, intent)` (lines 269-316): sets
  `forge_state.state['second_brain_status']='working'`, pulls, seeds the conversation with
  `[Today's date: ...]`, loops up to `MAX_TOOL_ROUNDS`. On a no-tool-call response it sets status
  back to `ready` and returns the last text block; on exhausting the rounds it sets status
  `error` and returns "ran out of steps".
- `_run_agent_loop_with_push` (lines 319-324) adds a guaranteed `_git_push()` for CAPTURE/PROCESS.
- `run(transcript, intent)` (lines 360-375): `PROCESS` → daemon thread (`_run_background`,
  lines 345-353) + immediate "On it…"; `CAPTURE`/`QUERY` run synchronously inline.
- `_append_forge_log` (lines 331-342) appends background results to `Forge Log.md`.

### 1.3 The capture library (`forge_capture.py`)
- Standalone Windows-origin CLI (`VAULT = Path("C:/second-brain")`, line 27) used by the running
  system **as a library**. Path globals default to the `C:/` root and are overridden at runtime
  by `second_brain.py` and `ingress_processor.py`.
- Loads `.env` from the vault (line 56) and creates its own Anthropic client from
  `os.environ["ANTHROPIC_API_KEY"]` (line 58) — a hard `KeyError` if that env var is unset.
- `claude-sonnet-4-6` is hardcoded at three call sites (lines 304, 324) inside
  `call_claude` / `call_claude_with_web_search`.
- Rich helper set: vault scanning (`scan_vault_for_query`, line 80), system prompts (lines
  157-293), Claude helpers (lines 300-346), write helpers (lines 466-575), ingress/web helpers
  (lines 666-733), and a full interactive `main()` REPL (lines 1121-1198).

### 1.4 The ingress batch path (`ingress_processor.py`)
- Same import-time API-key injection + path override pattern as `second_brain.py`
  (lines 13-29). `NEEDS_REVIEW_DIR = Ingress/Needs Review` (line 34).
- `detect_target` (lines 38-94): frontmatter `forge-target:` → body `Target:` line →
  `[ProjectName]` filename prefix → Claude inference (medium/high confidence only).
- `route_content` (lines 97-151): asks Claude for an action
  (`append_research | create_subproject | add_tasks | append_note`), then calls
  `forge_capture` helpers to execute it.
- `process_ingress` (lines 154-251): git-pulls, scans immediate `*.md` children of `Ingress/`,
  routes each, moves to `Processed/` or `Needs Review/` (with a generated review file), appends
  to `Forge Log.md`, commits/pushes via `git_commit_all` (lines 254-261). Triggered by the
  GitHub webhook (`api_server.py:699-724`) or the commented cron line (`ingress_processor.py:1-2`).

### 1.5 Confirmed defects in the current code
These are not speculative — they are visible in the source as read today:

- **🔴 `route_content` calls `forge_capture` helpers with wrong signatures (broken webhook
  PROCESS path).** `ingress_processor.py:130` calls
  `forge_capture.upsert_section(target, "## Research: ...", content)` but `upsert_section`'s
  real signature is `upsert_section(filepath: Path, section_header, content)`
  (`forge_capture.py:435`) — it is passed a *project-name string* where it expects a `Path`, and
  will `AttributeError` on `filepath.exists()`. Line 133 calls
  `write_new_project(target, body=..., is_future=...)` but the real signature is
  `write_new_project(result: dict)` (`forge_capture.py:466`). Line 143 calls
  `write_project_task(target, task)` but the real signature is
  `write_project_task(result, projects, areas)` (`forge_capture.py:480`). **Any ingress file
  that successfully detects a target will crash inside `route_content`**, get caught by the
  per-file `except Exception` (line 243), and be logged as `❌ Error processing`. The webhook
  ingress path is effectively non-functional for routed files. This is the single highest-value
  fix in my subject.
- **🔴 `_safe_path` prefix check is bypassable** (`second_brain_agent.py:163`). `startswith`
  on the string form means a sibling path like `/home/tyler/second-brain-notes` passes the guard
  (`"/home/tyler/second-brain-notes".startswith("/home/tyler/second-brain")` is `True`). The
  correct check is `resolved.is_relative_to(VAULT.resolve())` (Python 3.9+; venv is 3.13). Low
  real-world exploitability (Claude generates the paths, not an attacker), but it is a real
  traversal-guard bug in a write-capable tool.
- **🟡 Double git work / race window.** Both the agent's own git tools *and* the framework
  `_git_pull`/`_git_push` run, so a normal CAPTURE can pull-commit-push twice. `_git_pull` runs
  at the start of every QUERY too (`_run_agent_loop:272`), adding network latency to read-only
  questions on a Pi.
- **🟡 `forge_capture.client = anthropic.Anthropic(...)` created three times.** Once in
  `forge_capture` itself (line 58), once in `second_brain.py:23`, once in
  `ingress_processor.py:29`, plus a separate client in `second_brain_agent.py:31`. Harmless but
  violates the "shared instances" principle for the Claude client specifically.

---

## 2. Proposed improvements

Each tagged 🔴/🟡/🟢 priority and S/M/L effort. Tests/logging/error-handling are *described*,
not implemented.

### 2.1 🔴 / S — Fix the broken `route_content` → `forge_capture` calls
The webhook ingress PROCESS path is dead for any routed file (see §1.5). Two viable directions:
- **Option A (smaller, surgical):** rewrite the three call sites in `route_content`
  (`ingress_processor.py:130,133,143`) to build the `dict` / `Path` arguments the helpers
  actually expect. For `append_research`/`append_note`, resolve the target to a `Path` via
  `forge_capture.find_project_file(target)` (and the Areas fallback), then call
  `upsert_section(path, header, content)`. For `add_tasks`, build a `result` dict per task and
  pass `(result, projects, areas)`.
- **Option B (more consistent, recommended long-term):** retire `route_content`'s bespoke
  `forge_capture` dispatch and have the ingress path reuse the **agent** (`second_brain_agent`)
  the same way the voice/API PROCESS path does — feed the file content to `run(..., 'PROCESS')`.
  This collapses two write implementations into one, but is M effort and overlaps the spec's
  "leave the webhook path as-is" note (`second-brain-agent.md:149-151,171`), so flag for product
  decision rather than doing silently.
- **Tests:** a unit test that feeds a small fixture markdown file with a known
  `forge-target:` frontmatter through `route_content` against a temp git repo acting as the
  vault, asserting the target file gains the expected section and no exception is raised. Add a
  regression test per action (`append_research`, `add_tasks`, `append_note`).
- **Logging:** in the per-file `except Exception` (line 243), log `exc_info=True` to a logger
  instead of only appending a one-line `❌` to the return list — right now the stack trace that
  would have revealed this bug is discarded.
- **Error handling:** distinguish "Claude routing failed" from "write failed" so a transient API
  error doesn't look like a permanent routing failure in `Forge Log.md`.

### 2.2 🔴 / S — Harden `_safe_path`
Replace the `startswith` string check (`second_brain_agent.py:163`) with
`resolved.is_relative_to(VAULT.resolve())`. 
- **Tests:** parametrized unit test passing `"../etc/passwd"`, `"../second-brain-evil/x.md"`,
  `"Projects/Active/x.md"`, `"./x"`, and an absolute `/etc/passwd`, asserting only in-vault paths
  resolve and the rest raise `ValueError`.
- **Logging:** log rejected paths at WARNING (currently the `ValueError` only surfaces as a
  generic `"Error: ..."` tool result to Claude).
- **Error handling:** already correct (caught in `_execute_tool`); just ensure the rejection
  message returned to Claude is actionable ("path must be inside the vault").

### 2.3 🔴 / S — Centralize the hardcoded vault path & model id
The path `/home/tyler/second-brain` is hardcoded in **four** places
(`second_brain.py:7,12`, `second_brain_agent.py:24`, `ingress_processor.py:16,20`) and the model
`claude-sonnet-4-6` in **four+** places (`second_brain.py:47`, `second_brain_agent.py:27`,
`forge_capture.py:304,324`, and indirectly via ingress). The dossier flags both as drift
(Known Gaps #2, #11). Add `VAULT_PATH` and `SECOND_BRAIN_MODEL` to `config/settings.py` and have
all four modules import them. This is the single change that most reduces this subject's coupling
to "this exact machine."
- **Beginner-friendly:** one new settings constant each, mechanical find-and-replace, no logic
  change. Highly testable by import.
- **Tests:** a smoke test asserting `second_brain_agent.VAULT == settings.VAULT_PATH` and that
  the model constant matches settings — guards against future drift.
- **Logging:** log the resolved vault path once at agent import (INFO) so a misconfigured path is
  obvious in `logs/workshop_assistant.log`.
- **Coordination:** the model id is *shared* with the Intent & LLM lane's concern about the
  `claude-sonnet-4-20250514` vs `claude-sonnet-4-6` split — propose the setting; let that agent
  decide the canonical value. **Do not unilaterally change the model string** (it may be a real,
  intentionally different model — verify before touching, do not guess from memory).

### 2.4 🟡 / M — Make `forge_capture` importable without side effects
`forge_capture.py` does three risky things at import: hardcodes a Windows `VAULT` path (line 27),
calls `load_dotenv(VAULT / ".env")` (line 56), and constructs an Anthropic client that
**raises `KeyError`** if `ANTHROPIC_API_KEY` is unset (line 58). The whole subsystem only works
because `second_brain.py` happens to set the env var *before* importing it. Proposal: move the
client construction into a small `get_client()` lazy-init function, and default `VAULT` from
`config.settings.VAULT_PATH` (§2.3) instead of `C:/second-brain`. Keep the override hooks so the
CLI still works.
- **Beginner note:** incremental — change only the module-level side effects, leave every helper
  function untouched.
- **Tests:** `import forge_capture` with no env var set should not raise; calling a Claude helper
  without a key should raise a *clear* error ("set ANTHROPIC_API_KEY"), tested with monkeypatch.
- **Logging:** none needed beyond the clear exception message.
- **Error handling:** wrap the missing-key case in a friendly `RuntimeError` mirroring the
  existing `beautifulsoup4` pattern (`forge_capture.py:677`).

### 2.5 🟡 / S — Reduce redundant git operations & skip pull on QUERY
QUERY is read-only but still triggers `_git_pull()` (`second_brain_agent.py:272`), adding network
round-trips to a spoken question. Proposal: only pull at the start of CAPTURE/PROCESS, and rely on
the framework `_git_push` (or the agent's own git tools, not both). Pick **one** git mechanism
to avoid the double commit in §1.5.
- **Tests:** assert `_run_agent_loop(..., 'QUERY')` performs no `git pull` (monkeypatch
  `subprocess.run` and count git invocations).
- **Logging:** log which git mechanism committed (framework vs agent tool) so we can confirm we
  removed the duplication.
- **Error handling:** `_git_push` already treats "nothing to commit" as fine; keep that.

### 2.6 🟡 / M — Surface vault errors to the user and the UI
Today many failures are invisible: `_load_system_prompt` swallows read errors
(`second_brain_agent.py:59-60,66-67`); `MAX_TOOL_ROUNDS` exhaustion returns a generic apology
and sets `second_brain_status='error'` but nothing tells the user *why*; ingress per-file errors
only land as a `❌` line in `Forge Log.md`. Proposal: keep spoken responses short (per spec) but
log full context, and ensure `forge_state.state['second_brain_status']` transitions are always
reset to `ready` even on the exception paths in `_run_background` (currently it can be left as
`error`, with no recovery until the next successful run — `second_brain_agent.py:351`).
- **Tests:** simulate an API exception inside `_run_agent_loop` and assert
  `second_brain_status` is left in a sane state and a Forge Log entry is written.
- **Logging:** add INFO-level "vault CAPTURE/QUERY/PROCESS started/finished" bookends with the
  intent and a truncated transcript, so the log shows the vault lifecycle (it currently logs
  individual tool calls but not the high-level operation outcome).
- **Error handling:** wrap `run()` itself in a try/except returning a friendly spoken fallback
  ("Sorry, I had trouble reaching your vault") rather than letting an exception bubble into the
  voice pipeline.

### 2.7 🟢 / S — Declare and verify the optional dependencies
`forge_capture` imports `requests` (line 25, top-level) and lazily `beautifulsoup4` (line 675)
and `python-dotenv` (line 23), none of which are in `requirements.txt` (dossier Known Gaps #13).
`requests` and `dotenv` are imported at module top, so a fresh install on a clean reimage (the
planned "Clean reinstall" future project) would `ImportError` on the very first vault command.
Proposal: add `requests`, `beautifulsoup4`, `python-dotenv` to `requirements.txt`.
- **Tests:** an import smoke test in CI / a manual checklist item.
- **Logging/error handling:** the bs4 lazy-import already raises a helpful message; mirror it for
  `requests`/`dotenv` if you keep them lazy, or just declare them.

### 2.8 🟢 / M — A first test harness for the vault subsystem
There are **no automated tests anywhere in the repo** (dossier Known Gaps #19). The vault modules
are the best candidate for the *first* tests because the helpers are pure-ish functions over a
filesystem. Proposal: a `tests/` dir with a `pytest` fixture that creates a temp dir, `git init`s
it, and points `VAULT_PATH` at it; cover `_safe_path`, `upsert_section`, `build_task_line`,
`detect_target`, and a mocked-Claude `route_content`. No network: stub the Anthropic client.
- **Beginner note:** start with the three or four pure functions (`build_task_line`,
  `build_project_note`, `detect_mode`, `upsert_section`) that need no mocking — easiest possible
  on-ramp to testing for a beginner.
- **Effort M** only because of the git-temp-vault fixture; the individual tests are tiny.

### 2.9 🟢 / S — Spec/code drift cleanup
The spec's `run_command(command, args)` tool signature (`second-brain-agent.md:68`) does not match
the implemented `run_command(command, message)` enum (`second_brain_agent.py:129-152`), and the
spec says the system prompt loads from `AGENT.md` + behavioral instructions while the code *also*
loads the vault `CLAUDE.md` (`second_brain_agent.py:55-58`). Update the spec to match reality (the
code is the source of truth here). Documentation-only, no runtime risk.

### 2.10 SECRETS / .env — flagged separately per instructions
The following touch secrets or token-bearing paths and must be reviewed explicitly, **not**
changed casually:
- **GitHub webhook secret usage** (`api_server.py:699-724`): the HMAC verification is correct,
  but the webhook fires `process_ingress` on *any* validly signed POST without inspecting the
  GitHub event type or payload — a replayed valid payload re-runs ingress. Out of my lane to fix
  in `api_server.py` (Infra/UX), but it directly drives my subsystem, so I flag it. Any change
  here is a secrets-adjacent change.
- **`forge_capture` loads `/home/tyler/second-brain/.env`** (`forge_capture.py:56`). That `.env`
  is a *separate* secret store from `config/secrets.py`. If §2.4 (lazy/centralized config) is
  done, be careful **not** to log the loaded env contents and **not** to move the `.env` read
  into a path that could expose its values in `logs/`. The vault `.env` may contain an Anthropic
  key duplicated from `config/secrets.py`.
- **API key injected into the process environment** (`second_brain.py:6`,
  `ingress_processor.py:14`). This is necessary for `forge_capture`, but means
  `os.environ['ANTHROPIC_API_KEY']` is readable by any code in-process. Do not add anything that
  dumps `os.environ` to logs. Keep the injection as narrow as possible.

**Do not** rotate, print, or commit any of these values; any settings change that moves where the
vault path or model id is read from should be reviewed to ensure it does not pull a secret into a
checked-in file.

---

## 3. Dependencies on other subjects

- **Intent & LLM layer** — owns `second_brain.classify_intent()` routing semantics and the
  canonical Claude model id. My §2.3 (centralize model id) and any change to what counts as
  CAPTURE vs PROCESS must be coordinated with them. The `claude-sonnet-4-6` vs
  `claude-sonnet-4-20250514` reconciliation is jointly theirs.
- **Voice pipeline** — calls `second_brain.handle()` synchronously for CAPTURE/QUERY; my §2.6
  (wrap `run()` in try/except, reset `second_brain_status`) must not change the function's return
  contract (a spoken string) that the pipeline relies on. `forge_state['second_brain_status']`
  is read by the UI, written by me.
- **Infra & deployment** — owns `config/settings.py`, `requirements.txt`, the systemd unit, and
  the GitHub webhook in `api_server.py`. My §2.3 (new settings constants), §2.7 (requirements),
  and §2.10 (webhook event validation) land in files they own; I propose, they implement.
- **UX / interface** — consumes `second_brain_status` (`ready|working|error`) for the kiosk UI.
  My §2.6 error-state handling affects what the UI shows.

---

## 4. Non-goals / out of scope

- **Conversation/multi-turn memory** for vault queries — explicitly out of scope per spec
  (`second-brain-agent.md:169`) and a separate pending feature.
- **Budget tracking for the vault's Claude calls** — the vault modules call Claude directly and do
  **not** go through `budget_tracker`. Wiring vault spend into the budget tracker is a real gap,
  but it belongs to the Intent & LLM / budget owner; I only note it here.
- **Rewriting the vault agent architecture** — no swap to a different agent framework, no
  heavyweight indexing/embeddings over the vault (the Pi can't afford it and `scan_vault_for_query`
  / `rglob` are adequate at current vault size).
- **Changing intent classification** — I describe `classify_intent` but defer all changes to it.
- **The interactive `forge_capture.main()` REPL** — it is dead weight in the running appliance but
  harmless; I won't remove it (it's still a useful manual tool), only de-risk its import-time side
  effects (§2.4).
- **Anything in `api_server.py`, `main.py`, `intent_recognition.py`, `claude_integration.py`** —
  other lanes own these.

---

## Top 3 recommendations (summary)

1. **🔴 Fix `route_content` (`ingress_processor.py:130,133,143`)** — it calls three
   `forge_capture` helpers with the wrong argument shapes, so the GitHub-webhook ingress path
   crashes on every file it actually manages to route. Highest-value, smallest fix.
2. **🔴 Harden `_safe_path` (`second_brain_agent.py:163`)** — the `startswith` traversal guard is
   bypassable by sibling paths; switch to `is_relative_to`. Small, security-relevant, on a
   write-capable tool.
3. **🔴 Centralize the hardcoded `/home/tyler/second-brain` path and `claude-sonnet-4-6` model id
   into `config/settings.py`** — four duplicated copies of each across my four files; this is the
   change that most decouples the subsystem from this one machine and sets up the planned clean
   reinstall. (Coordinate the model id with the Intent & LLM lane; do not change the string
   blindly.)
