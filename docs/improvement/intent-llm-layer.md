# Intent & LLM Layer — Review (Phase B)

Subject owner scope: the Claude API call itself (`src/claude_integration.py`), the
ANSWER-path intent classification and its trigger prompt (`src/intent_recognition.py`),
model selection, budget/cost tracking as it relates to API usage (`src/budget_tracker.py`),
token usage, latency of the API path, and web_search tool usage.

Out of my lane (flagged as dependencies, not changed): the vault classifier model in
`src/second_brain.py` and the vault agent in `src/second_brain_agent.py`; anything that
happens to a CAPTURE/QUERY/PROCESS command *after* classification.

Model/pricing facts below were checked against the `claude-api` skill reference (cached
2026-05-26), not memory.

---

## 1. Current state

### 1.1 ANSWER-path intent classification (`src/intent_recognition.py`)

`classify_intent(text, source="voice")` (line 29) is a flat keyword router. It lowercases
the transcript and checks substring membership against module-level trigger lists in this
fixed order:

1. `STOP_TRIGGERS` (line 18) — `"thank you", "thanks", "stop", "never mind", ...` → returns
   `"Got it."` and calls `claude_integration.clear_history(source)` (lines 33-37).
2. `CALENDAR_TRIGGERS` (line 13) → `skills.calendar.calendar_query` (lines 42-45).
3. `CALCULATOR_TRIGGERS` (line 14) — `"what is", "what's", "calculate", "how much is"` →
   `skills.calculator.calculate`; on `ValueError` falls back to Claude (lines 48-59).
4. `TIMER_TRIGGERS` (line 16) → `skills.timer.set_timer` (lines 61-65).
5. `HOME_ASSISTANT_TRIGGERS` (line 15) — `"turn on", "turn off"` → `home_assistant.control_device`
   (lines 67-70).
6. `ALARM_TRIGGERS` (line 17) → `skills.timer.stop_alarm` (lines 72-75).
7. else → `claude_integration.ask_claude` (lines 78-81).

Every branch logs via `query_logger.log_query` with a handler tag.

Notable behaviors and rough edges in the routing layer:

- **Order/overlap collisions.** `STOP_TRIGGERS` contains the bare token `"stop"`, and so does
  `ALARM_TRIGGERS`. Because `STOP_TRIGGERS` is checked first (line 33) with a substring match,
  "stop the timer" / "stop alarm" hit the stop-and-clear-history branch and **never reach the
  alarm branch** at line 72. The alarm branch is effectively unreachable for any phrase
  containing "stop". Only "turn off alarm" can reach it.
- **`CALCULATOR_TRIGGERS` is very greedy.** `"what is"` / `"what's"` catch the majority of
  natural questions ("what's the best temp for PLA", "what is a kerf"). These all go through
  `calculator.calculate`, raise `ValueError`, and *then* fall back to Claude (lines 54-59).
  Functionally correct, but it means a large share of real questions take the calculator-parse
  detour first, and they are logged as `claude_fallback_calc` rather than `claude`.
- **Substring matching with no word boundaries.** "I want to turn one screw" contains
  "turn on" → routed to Home Assistant. No anchoring or tokenization.
- **The classifier is synchronous Claude under an `async def`.** See 1.2 — `ask_claude` is a
  blocking call invoked directly (not via `asyncio.to_thread`) at lines 57 and 80.

### 1.2 The Claude API call (`src/claude_integration.py`)

`ask_claude(question, source="voice")` (line 40):

- Module-level singleton client `anthropic.Anthropic(api_key=CLAUDE_API_KEY)` (line 22) —
  good (one client instance, matches the "shared instances" principle).
- Per-source history dicts `_history = {"voice": [], "api": []}` and `_last_exchange`
  (lines 24-25). History is reset if the gap since the last exchange exceeds
  `CONVERSATION_TIMEOUT` (lines 51-54), trimmed to `CONVERSATION_MAX_TURNS*2` entries
  (lines 84-85).
- Budget gate first: `budget_tracker.is_limit_reached()` returns a spoken refusal if the
  hard limit is hit (lines 47-49).
- The call (lines 63-77): `model=CLAUDE_MODEL`, `max_tokens=CLAUDE_MAX_TOKENS` (200),
  `temperature=CLAUDE_TEMPERATURE` (1.0), a hardcoded inline system prompt, and
  `messages = _history[source] + [user msg]`.
- Reads `message.content[0].text` directly (line 79) — assumes the first block is text.
- Records usage via `budget_tracker.record_usage(input_tokens, output_tokens)` (lines 88-90)
  and appends a spoken low-budget warning when the threshold is first crossed (lines 92-93).
- Error handling: catches `anthropic.APIError` and bare `Exception` with spoken fallbacks
  (lines 97-103).
- Three `[DEBUG]`-prefixed INFO log lines (lines 28, 31, 60) echo full conversation history
  to `logs/workshop_assistant.log` — verbose, and they write user content to a log that has
  no rotation (see Infra dependency).

`log_query` (lines 33-38) appends a timestamped question line to `CLAUDE_QUERY_LOG`.

### 1.3 Model selection and pricing

- `CLAUDE_MODEL = "claude-sonnet-4-20250514"` (`config/settings.py:59`). Per the skill's
  model catalog this is **Claude Sonnet 4 (deprecated), retiring 2026-06-15**, drop-in
  replacement `claude-sonnet-4-6`. Today is 2026-06-13 — **this model retires in two days.**
- `CLAUDE_INPUT_PRICE_PER_MTOK = 3.00`, `CLAUDE_OUTPUT_PRICE_PER_MTOK = 15.00`
  (`settings.py:69-70`). These happen to be exactly the `claude-sonnet-4-6` prices ($3/$15),
  so a swap to `claude-sonnet-4-6` needs **no pricing change** and keeps the budget math correct.
- `CLAUDE_TEMPERATURE = 1.0` is passed on every call. Fine on Sonnet 4.x. Important constraint
  for any future model change: `temperature` (and `top_p`/`top_k`) **return a 400 on Opus 4.7+,
  Opus 4.8, and Fable 5** — those models removed sampling parameters. So Sonnet 4.6 is the
  natural, lowest-risk migration target for this path; moving to an Opus/Fable tier would
  require removing the `temperature` kwarg.
- The dossier's reported split is real: ANSWER path = `claude-sonnet-4-20250514`; the vault
  classifier (`second_brain.py:47`) and vault agent (`second_brain_agent.py`) hardcode
  `claude-sonnet-4-6`. Migrating the ANSWER path to `claude-sonnet-4-6` would *unify* the
  whole codebase on one model string. (Vault side is a dependency — see §3.)

### 1.4 Budget tracking (`src/budget_tracker.py`)

- `_load`/`_save` against `logs/budget.json`; schema `{total_cost, total_input_tokens,
  total_output_tokens}` (lines 21-25).
- `record_usage` computes cost from the per-MTok constants, persists, and returns
  `{total_cost, warning, limit_reached}`; the one-shot `warning` flag resets per process
  (lines 18-19, 52-85).
- Works correctly for the single ANSWER-path caller. **Gap:** the vault classifier and vault
  agent make their own Claude calls and **do not** call `record_usage`, so budget tracking
  only sees ANSWER-path spend. This undercounts true API spend (dependency — see §3).
- Schema drift (dossier item 3): the API's `GET /budget` FileNotFound fallback and
  `DELETE /budget` write `{total_cost: 0, sessions: []}`, a different shape than the tracker
  produces. The tracker never writes `sessions`. Reading `_load()["total_cost"]` still works
  because both shapes carry `total_cost`, but it's fragile.

### 1.5 Latency of the API path

- The ANSWER-path Claude call is **synchronous and blocks the asyncio event loop.**
  `intent_recognition.classify_intent` is `async`, but it calls `claude_integration.ask_claude`
  directly (lines 57, 80) — a blocking `client.messages.create`. On the voice pipeline this is
  invoked from a thread, so it's contained. On the **API path** it is awaited on the main loop
  (`api_server.py:622, 677`) — wait, it's `await`ed but the function body still runs the
  blocking SDK call inline, so the loop is blocked for the duration of the Claude call. Any
  concurrent `/status`, `/status/stream`, or `/sensors` request stalls until Claude returns.
- No prompt caching is used. The system prompt is small (~120 tokens) and below the cacheable
  minimum anyway, so caching would not help here — correctly absent.
- No streaming. With `max_tokens=200` and a short system prompt, non-streaming is fine and
  simpler; streaming is not warranted for this workload.

### 1.6 web_search tool usage

- The ANSWER path does **not** use any server-side tools. `ask_claude` is a plain
  `messages.create` with no `tools=` — so Forge cannot answer time-sensitive questions
  ("who won last night", "current price of X") on the voice/ANSWER path.
- The only `web_search` usage in the repo is `forge_capture.call_claude_with_web_search`
  (uses `web_search_20250305`), which is on the vault side (dependency — see §3).

---

## 2. Proposed improvements

Priority: 🔴 do soon / 🟡 worthwhile / 🟢 nice-to-have. Effort: S/M/L. All are
beginner-friendly, incremental, and Pi-resource-aware. None require a rewrite.

### 🔴 S — Migrate the ANSWER model off the retiring `claude-sonnet-4-20250514`
**Why:** `claude-sonnet-4-20250514` retires 2026-06-15 (two days from the review date). After
that the API returns 404 and the voice/ANSWER path silently falls into the
`anthropic.APIError` branch ("Sorry, I couldn't reach Claude right now") for every question.
**Change:** set `CLAUDE_MODEL = "claude-sonnet-4-6"` in `config/settings.py:59`. Pricing
constants already match ($3/$15) so the budget math stays correct. `temperature=1.0` is still
valid on Sonnet 4.6, so no other code changes. This also unifies the ANSWER path with the
vault modules (which already use `claude-sonnet-4-6`).
**Secrets note:** none — this does not touch the API key or `.env`/`secrets.py`.
**Tests to add:** a tiny smoke test that asserts `response.model.startswith("claude-sonnet-4-6")`
on one live call (gated behind an env flag so it doesn't run offline). A pure-unit test isn't
possible without mocking the SDK; describe a `monkeypatch`-based test that stubs
`client.messages.create` to return a fake `Message` and asserts `ask_claude` returns the text.
**Logging:** log the resolved `message.model` once at INFO on the first successful call so a
future model swap is visible in the log.
**Error handling:** add a `NotFoundError` branch (see next item) so a retired/typo'd model ID
produces a clear spoken message ("That model isn't available") instead of the generic
network-error string.

### 🔴 S — Distinguish error types in `ask_claude`
**Why:** today every failure that isn't `anthropic.APIError` collapses to "something went
wrong", and `APIError` collapses to "couldn't reach Claude". A 404 (bad model), 401 (bad key),
and 429 (rate limit) all read the same to the user and to whoever debugs the log.
**Change:** add typed branches before the bare `except`: `anthropic.AuthenticationError`,
`anthropic.NotFoundError`, `anthropic.RateLimitError`, `anthropic.APIConnectionError`, then
`anthropic.APIError`, then `Exception`. Keep the spoken strings short and friendly; log the
distinct cause and `message._request_id` at ERROR.
**Secrets note:** the `AuthenticationError` branch must **not** log the key — log only the
fact, never `CLAUDE_API_KEY`.
**Tests:** unit tests that stub `client.messages.create` to raise each exception type and
assert the correct spoken string is returned (no real API needed).
**Logging:** include `message._request_id` on success and on `APIStatusError` so failures are
traceable with Anthropic.

### 🔴 S — Stop the ANSWER-path Claude call from blocking the event loop on the API path
**Why:** `intent_recognition.classify_intent` is `async` but `ask_claude` runs a blocking SDK
call inline. On the API server (`api_server.py:622, 677`) this is awaited on the main loop, so
a single slow Claude response stalls `/status`, `/status/stream`, and `/sensors` for all
clients (including the kiosk UI's SSE stream). This directly contradicts the "async throughout,
do not introduce blocking calls into the main loop" design principle.
**Change (smallest, most readable):** wrap the blocking call in
`await asyncio.to_thread(...)`. The cleanest spot is inside `intent_recognition.classify_intent`
at the two `claude_integration.ask_claude(...)` call sites — change them to
`await asyncio.to_thread(claude_integration.ask_claude, text, source=source)`. `ask_claude`
stays synchronous (no rewrite). The voice pipeline already runs the whole classify call in a
thread, so this is a no-op there and a strict improvement on the API path.
**Secrets note:** none.
**Tests:** a test that fires a `/status` request concurrently with a slow stubbed Claude call
and asserts `/status` returns promptly (integration-style; describe it, don't necessarily build
it). At minimum, a unit test asserting the call site uses `to_thread`.
**Logging:** none new.

### 🟡 S — Make the stop/alarm trigger ordering correct
**Why:** "stop the timer" / "stop alarm" hit `STOP_TRIGGERS` (line 33) before the alarm branch
(line 72) because both lists contain the bare `"stop"`. The alarm branch is largely
unreachable, so users can't stop a sounding alarm by voice with the obvious phrase.
(Note: there is a *separate*, vault-side bug where `stop_alarm` can't interrupt a sounding
alarm — that's dossier item 9 and a Voice/skills concern, not this layer. This item is only
about routing the phrase to the right handler.)
**Change:** check `ALARM_TRIGGERS` before `STOP_TRIGGERS`, or remove the bare `"stop"` from
`STOP_TRIGGERS` and keep specific stop phrases ("never mind", "that's all", "cancel"). Keep it
to a reorder + comment so it's easy to follow.
**Tests:** table-driven unit test mapping representative phrases → expected handler tag
(`local_alarm` vs `local_stop`). No API needed — `query_logger` and skills can be stubbed.
**Logging:** none new; the existing handler tags already make the routing visible in
`all_queries.jsonl`.

### 🟡 M — Add a typed-tool web_search to the ANSWER path (opt-in, budget-aware)
**Why:** Forge can't answer time-sensitive questions today. The skill's
`web_search_20260209` tool (server-side, supports dynamic filtering on Sonnet 4.6) would let
"who won the game / current price / latest version" questions actually resolve.
**Change:** add `tools=[{"type": "web_search_20260209", "name": "web_search"}]` to the
`messages.create` call, gated behind a new `WEB_SEARCH_ENABLED` feature flag in
`settings.py` (default off until tested). Handle `stop_reason == "pause_turn"` by re-sending
(the skill documents the loop) with a small `max_continuations` cap so a runaway loop can't
blow the budget. Web search adds tokens and latency, so keep `max_tokens` modest and let the
budget tracker (which already records `usage`) absorb the extra spend.
**Secrets note:** none — server-side tool, no extra credentials, uses the existing key.
**Tests:** stub a response containing a `server_tool_use` block + final text and assert
`ask_claude` returns the text and that `record_usage` is still called. Add a test that a
`pause_turn` response triggers exactly one continuation and stops at the cap.
**Logging:** log when web_search is invoked (handler tag `claude_web_search`) so its cost
contribution is visible in the query log.
**Latency caveat:** on the Pi this noticeably increases response time; document that and keep
it flag-gated.

### 🟡 S — Centralize the budget threshold semantics and fix the `/budget` schema drift origin
**Why (this layer's part):** the tracker writes `{total_cost, total_input_tokens,
total_output_tokens}` and never writes `sessions`, while the API's empty/reset payloads use
`{total_cost, sessions: []}`. The mismatch lives at the API boundary (UX/interface lane), but
the *source of truth* is this module. Aligning the empty/reset shape to the tracker's schema
removes the drift.
**Change (in-lane):** expose a single `budget_tracker.empty_budget()` returning
`dict(_EMPTY_BUDGET)` and have the API import/use it for both the FileNotFound fallback and
`DELETE /budget`, instead of hand-writing a different dict. The actual API edits are the
UX/interface agent's to apply, but the helper belongs here.
**Tests:** assert `empty_budget()` matches `_EMPTY_BUDGET` keys; assert `record_usage` on a
fresh file produces the same key set.
**Logging:** none new.

### 🟢 S — Quiet or gate the `[DEBUG]` history-echo log lines
**Why:** lines 28, 31, 60 in `claude_integration.py` write full conversation history (user
questions and prior answers) at INFO to `logs/workshop_assistant.log`, which has no rotation
and is already very large (dossier item 10). This is verbose and embeds user content in an
unbounded file.
**Change:** drop these to `logger.debug(...)` (the root logger is at INFO, so they'd stop
writing) or remove them. Keep the concise "Sending to Claude" / "Claude response" lines.
**Secrets note:** none, but reducing logged user content is a mild privacy improvement.
**Tests:** none needed; optionally assert the logger level guard.
**Logging:** this *is* the logging change.

### 🟢 M — Replace the keyword `classify_intent` with a small, testable matcher
**Why:** the current substring router has the boundary-collision and greediness problems noted
in §1.1. This is not urgent (it works), but it's the most fragile part of the layer.
**Change:** keep the same architecture (local-first, Claude fallback) but move triggers into a
small ordered table of `(handler, phrases, match_mode)` and add word-boundary matching for the
short tokens ("stop", "turn on"). Pure-Python, no new dependency, no model call — keeps the Pi
footprint identical. Do this only after the 🔴 items; it's a readability/correctness
investment, not a fix for a live failure.
**Tests:** a single parametrized test covering each handler's representative phrases plus the
known collision cases ("stop the timer", "what's the best temp for PLA", "turn one screw").
**Logging:** unchanged handler tags.

---

## 3. Dependencies on other subjects

- **Vault integration (Vault agent's lane).** The reported model split is half mine: I own the
  ANSWER side (`claude-sonnet-4-20250514`); the vault side hardcodes `claude-sonnet-4-6` in
  `second_brain.py:47` and `second_brain_agent.py`. My 🔴 model migration *converges* both sides
  on `claude-sonnet-4-6`. **Flag for the Vault agent:** the vault classifier and vault agent make
  Claude calls that do **not** go through `budget_tracker.record_usage`, so total API spend is
  undercounted; if budget accuracy matters, the vault calls should also record usage. Also, the
  only `web_search` usage today is vault-side (`forge_capture.call_claude_with_web_search`,
  `web_search_20250305`).
- **Voice pipeline.** The voice path runs `classify_intent` in a thread, so my "don't block the
  loop" fix is API-path-specific; the Voice agent owns barge-in, STT, and the alarm-can't-be-
  stopped-while-sounding bug (dossier item 9), which is distinct from my trigger-ordering fix.
- **Infra & deployment.** My 🟢 logging fix interacts with the no-log-rotation issue (dossier
  item 10) — reducing logged history helps, but rotation is theirs. The retiring-model 🔴 item
  is time-critical for the deployed service; whoever owns deploys should be aware the live
  service breaks on 2026-06-15 without the model swap.
- **UX/interface.** The `/budget` schema-drift *fix* (the API-side edits) and the
  budget-warning spoken string surface are UX-owned; I only provide the `empty_budget()` helper
  and own the threshold semantics.

---

## 4. Non-goals / out of scope

- Any change to what happens to a CAPTURE/QUERY/PROCESS command after classification
  (`second_brain.py`, `second_brain_agent.py`, `forge_capture.py`, `ingress_processor.py`).
- The vault classifier prompt/model and the vault agent's tool loop (only flagged as deps).
- The alarm-can't-be-stopped-mid-sound bug in `skills/timer.py` (Voice/skills lane).
- STT/TTS, wake word, barge-in, audio devices (Voice lane).
- CORS, API-key logging on auth failure, the settings-rewrite/`os.execv` mechanism, log
  rotation (Infra/UX lanes).
- No migration to an Opus/Fable tier is proposed: the ANSWER path passes `temperature`, which
  400s on those models, and the workload (1–2 sentence workshop answers) does not justify the
  cost — Sonnet 4.6 is the right target.
- No secrets/`.env` changes. The only places that touch the API key are flagged: the
  `AuthenticationError` branch must never log the key.

---

## Top 3 recommendations (summary)

1. **🔴 Swap `CLAUDE_MODEL` to `claude-sonnet-4-6` now** — `claude-sonnet-4-20250514` retires
   2026-06-15 (two days out); after that every voice/API question fails. Pricing constants and
   `temperature=1.0` stay valid, and this unifies the codebase on one model string.
2. **🔴 Run the ANSWER-path Claude call off the event loop** via `asyncio.to_thread` at the two
   `ask_claude` call sites in `intent_recognition.py` — today it blocks `/status`,
   `/status/stream`, and `/sensors` on the API path, violating the project's async principle.
3. **🔴 Add typed error branches in `ask_claude`** (NotFound/Auth/RateLimit/Connection) with
   distinct spoken messages and `request_id` logging — so a retired model, bad key, or rate
   limit is diagnosable instead of collapsing to one generic string. (Never log the API key.)
