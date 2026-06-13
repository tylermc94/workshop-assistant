# Forge Improvement Plan — Converged (Phase C)

This is the single, ordered plan that merges the five Phase B specialist reports
([voice-pipeline-audio](voice-pipeline-audio.md), [intent-llm-layer](intent-llm-layer.md),
[vault-integration](vault-integration.md), [infra-deployment](infra-deployment.md),
[ux-interface](ux-interface.md)), all of which build on the
[Forge Dossier](Forge-Dossier.md).

**Audience:** Tyler — a beginner Python dev running Forge on a Raspberry Pi 5, mid-Phase-4.
**Principles carried through:** resource-aware (no heavyweight rewrites), readable and
incremental changes, build on what exists, add tests/logging/error-handling alongside code,
and flag anything touching `config/secrets.py` / `.env` explicitly (marked 🔑 below).

Priorities: 🔴 do soon · 🟡 worthwhile · 🟢 nice-to-have. Effort: **S** (≲1 hr) · **M** (a few
hrs) · **L** (a day+).

---

## 1. Evaluation of the five reports

All five stayed cleanly in their lanes, cited real files and line numbers, and explicitly named
their cross-lane dependencies. Reasoning quality is high and grounded in the source as it exists
on 2026-06-13, not in the dossier's prose alone. Every proposal is Pi-friendly and beginner-sized;
no agent proposed a rewrite or a new heavyweight platform. Notably:

- **Intent & LLM** verified all model IDs/pricing against the live `claude-api` reference rather
  than memory, and correctly ruled out an Opus/Fable migration for this path (those models 400 on
  the `temperature` kwarg this code sends).
- **Vault** surfaced two *confirmed, present* bugs (not hypotheticals) by reading the actual
  function signatures.
- **Infra** verified everything against the live system (unit diffs, listening sockets, git creds,
  log sizes, crontab) — including a repo-health risk that is live *right now*.

The plan below adopts essentially all of it, sequenced across phases and de-conflicted.

---

## 2. Conflicts & overlaps between reports (resolved before merging)

These are the places where two or more reports touch the same surface. Each is resolved by
assigning a single **owner** for the change and **consumers** who adapt in lockstep.

| # | Shared surface | Reports involved | Resolution |
|---|----------------|------------------|------------|
| O1 | **Claude model id** (`claude-sonnet-4-6`) | Intent §2.1, Vault §2.3 | **Intent owns the canonical value.** Verified: `claude-sonnet-4-20250514` retires **2026-06-15**; `claude-sonnet-4-6` is the drop-in (same $3/$15 pricing, `temperature=1.0` still valid). Vault's caution ("don't change the string blindly") is satisfied — the value is confirmed. Vault centralizes it into `settings.SECOND_BRAIN_MODEL`; Intent's `CLAUDE_MODEL` converges on the same string. |
| O2 | **`/budget` schema drift** | Intent §2.6 (writer), UX §"reconcile /budget" (reader), Vault §4 (vault spend bypasses tracker) | **Intent owns the canonical schema** + a `budget_tracker.empty_budget()` helper. UX fixes the consumer (`loadBudget`) to read `total_*` and tolerate both shapes during transition. Wiring *vault* Claude spend into the tracker is a separate open question (Q3). |
| O3 | **`config/logging_config.py` → RotatingFileHandler** | Infra §2 (owner), Voice §2 (audio-retry log spam), Intent §2 (`[DEBUG]` history echo) | **Infra owns rotation** (the handler swap). Voice's "cap audio-error log spam" and Intent's "drop `[DEBUG]` history lines to `debug()`" are independent reductions that ride alongside it. |
| O4 | **`api_server.py` security edits** — webhook fail-closed, stop logging rejected token, CORS `*` | Infra §2/§2.A (requirements), UX §1.6/§5, Vault §2.10 | **Infra sets the requirements; the app-code edits need a single API owner.** This plan assigns the `api_server.py` edits to the **Intent & LLM lane** (it already owns that file's request path) executing Infra's spec. CORS tightening is gated on the remote-access decision (Q1). |
| O5 | **`ask_claude` blocking the event loop** vs **SSE stalls** | Intent §2.3, UX §1.3 | Same root cause. **Intent owns the fix** (`asyncio.to_thread` at the two call sites in `intent_recognition.py`). UX's SSE self-healing is complementary, not duplicative — keep both. |
| O6 | **`audio_status` in `forge_state`** | Voice §2 (defines/populates), UX §3 (renders) | Clean producer/consumer split. **Voice writes the field; UX renders it.** No conflict. |
| O7 | **TTS tuning knobs** (`TTS_SPEED`/noise) | Voice §2 (wire-or-delete), UX §3 (settings UI) | **Voice decides wire-vs-delete first;** UX only keeps/removes the matching settings-panel knobs to match. |
| O8 | **`wav_bytes_to_numpy` double-resample** | Voice §2 (owner), Intent §3 (shared `/query` flow) | **Voice owns the change**, coordinates with Intent because it sits on the shared API request path. Low risk; behind the same testing as the temp-file fix. |
| O9 | **First `tests/` harness + pytest scaffolding** | Voice §2, Vault §2.8, Intent (throughout) | **Merge into one foundation item.** Vault's pure filesystem helpers and Voice's pure audio-logic helpers are the easiest on-ramps; stand up `tests/` once and let all three lanes add to it. |
| O10 | **Git credentials / deploy auth** | Infra §2.A.5 (owner), Vault §3 (vault's own push/pull) | **Infra owns** the documented PAT/deploy-key. Vault's `/home/tyler/second-brain` git operations benefit from the same credential being in place. |

### Gaps with no clear owner (surfaced, not silently absorbed)

- **`skills/timer.py` alarm-can't-be-stopped bug** (Dossier gap #9): `start_timer` never sets
  `alarm_process`, so `stop_alarm` always reports "No alarm is playing." Intent explicitly scoped
  this *out* (routing-only) and Voice scoped it *out* (audio-I/O-only). **Neither lane claimed the
  skills fix.** It is included below under Phase 4 and raised as **Q5**. (Distinct from Intent's
  trigger-*ordering* fix, which is owned and included.)
- **`route_content` direction** — Vault offers a surgical fix (Option A) vs. routing ingress
  through the agent (Option B). This is a product decision → **Q2**.

---

## 3. The plan, in incremental phases

### Phase 0 — Time-critical (do this week, before 2026-06-15)

| Item | Lane | Pri/Effort | Notes |
|------|------|-----------|-------|
| **Swap `CLAUDE_MODEL` → `claude-sonnet-4-6`** (`config/settings.py:59`) | Intent | 🔴 S | The deployed model retires **2026-06-15**; after that every voice/API answer fails into the generic error branch. Pricing constants ($3/$15) and `temperature=1.0` stay valid → one-line change. Adopt the canonical value here (O1). |
| **Stop tracking log files in git; fix `.gitignore`** | Infra | 🔴 S | `git ls-files logs/` shows `workshop_assistant.log` (527 MB) **and** `all_queries.jsonl` are tracked and currently show as modified — one `git add -A` from committing a half-GB blob. `git rm --cached` them (keep on disk), add `*.log` + `logs/*.jsonl`, fix the malformed `.idea/logs/` line. *(Already-pushed history is a separate decision — Q7.)* |

> **Convergence note:** This very Phase-C commit must itself avoid `git add -A`. Stage only
> `docs/improvement/` — the tracked logs are exactly the risk Infra flagged.

### Phase 1 — Critical bug fixes & resilience (mostly S, high value)

| Item | Lane | Pri/Effort | Notes |
|------|------|-----------|-------|
| **Run `ask_claude` off the event loop** via `await asyncio.to_thread(...)` at the two call sites in `intent_recognition.py` | Intent | 🔴 S | Today the blocking SDK call stalls `/status`, `/status/stream`, `/sensors` on the API path — including the kiosk SSE. Fixes O5. |
| **Typed error branches in `ask_claude`** (`AuthenticationError`/`NotFoundError`/`RateLimitError`/`APIConnectionError`) with distinct spoken messages + `request_id` logging | Intent | 🔴 S | 🔑 The auth branch must **never** log `CLAUDE_API_KEY`. |
| **Fix `route_content` broken signatures** (`ingress_processor.py:130,133,143`) | Vault | 🔴 S | Webhook ingress crashes on every routed file today. Start with surgical Option A; Option B is Q2. |
| **Harden `_safe_path`** → `resolved.is_relative_to(VAULT.resolve())` (`second_brain_agent.py:163`) | Vault | 🔴 S | `startswith` lets a sibling like `/home/tyler/second-brain-notes` pass; real traversal-guard bug on a write-capable tool. |
| **Centralize name-based audio device resolution** into one `src/audio_devices.py` used by wake word, STT, and TTS | Voice | 🔴 M | The top fragility: `wake_word.py`'s input auto-detect never reaches `speech_to_text.py`, and output (`aplay plughw:3`) isn't detected at all. **Document the ALSA-card-index vs PortAudio-index distinction** and prefer `plughw:CARD=<name>` for output. |
| **Re-resolve device index on wake-word stream-open failure** | Voice | 🔴 S | A USB replug currently retries the stale index forever → Forge goes deaf until manual restart. |
| **Fix kiosk settings/budget panel auth** | UX | 🔴 S | 🔑 The kiosk never sets `localStorage.forgeApiKey`, so every authed endpoint 401s and Settings is silently broken. **Preferred fix (decide with Infra): make UI-supporting GETs localhost-only/unauthenticated; keep Bearer on mutating/remote endpoints** — removes the token from the browser. Do **not** inline the key into `index.html` (served unauthenticated at `/`). |
| **Make SSE self-healing** — add `EventSource.onerror`, a "LINK LOST" indicator, and a ~20s stale-data watchdog (server already sends 15s keepalive) | UX | 🔴 S | The unattended kiosk can wedge with stale status after a backend re-exec/restart. |

### Phase 2 — Deployment & operational reliability (Infra-led)

| Item | Lane | Pri/Effort | Notes |
|------|------|-----------|-------|
| **Add log rotation** — `RotatingFileHandler` (~10 MB ×5) in `config/logging_config.py` | Infra | 🔴 S | Owner of O3. Truncate the live 527 MB file after a stop before/while switching. |
| **Version-control the unit files** — copy `forge-ui.service` into `deploy/`, add the live unit's missing `PYTHONIOENCODING`/`LANG` env lines to the committed `workshop-forge.service` | Infra | 🔴 S | The UI unit exists only on the SD card; the installed backend unit has drifted from the repo. |
| **`deploy/install.sh` + `deploy/update.sh`** (idempotent, `set -euo pipefail`) | Infra | 🔴 S | `update.sh` does `git pull --ff-only` **then** `systemctl restart` — closes the "pull doesn't restart" gap. |
| **Crash-loop protection** — `StartLimitIntervalSec=300`, `StartLimitBurst=5` on `workshop-forge.service` | Infra | 🟡 S | `Restart=always` currently reloads Whisper/Piper/Porcupine forever on a hard failure. |
| **Readiness gate** — replace `forge-ui`'s blind `sleep 15` with a `curl -sf localhost:8080/health` poll (capped); consider `BindsTo=` | Infra | 🟡 M | Stops the kiosk showing a blank/"can't connect" page on a slow cold boot. |
| **Webhook fail-closed** — `/webhook/ingress` returns 503 if `GITHUB_WEBHOOK_SECRET` is unset, instead of accepting any POST | Intent (per Infra spec) | 🟡 S | 🔑 O4. Currently fail-open. Log "signature missing/invalid from \<ip\>" at WARNING — never the signature/body. |
| **Stop logging rejected tokens** (`api_server.py:57`) — log only "auth failed + source IP" | Intent (per Infra spec) | 🟡 S | 🔑 Rejected bearers are often valid secrets typed at the wrong host, currently written to the unbounded log. |
| **Ingress cron → systemd timer** (`forge-ingress.service` + `.timer`, `OnUnitActiveSec=10min`) | Infra | 🟢 S | Moves the undocumented every-10-min run into the journal and into version control. |
| **Decide & document the remote-access path** (Cloudflare Tunnel recommended) | Infra | 🟡 M | Q1. Until then, narrow the `0.0.0.0:8080` bind / add a firewall rule. CORS tightening rides on this. |

### Phase 3 — Configuration hygiene & maintainability

| Item | Lane | Pri/Effort | Notes |
|------|------|-----------|-------|
| **Centralize `VAULT_PATH` + `SECOND_BRAIN_MODEL`** into `config/settings.py`; replace the 4× hardcoded `/home/tyler/second-brain` and 4×+ hardcoded model id | Vault | 🔴 S | Single biggest decoupling from "this exact machine"; sets up the planned clean reinstall. Model id uses Intent's canonical value (O1). |
| **Make `forge_capture` importable without side effects** — lazy `get_client()`, default `VAULT` from settings | Vault | 🟡 M | 🔑 It currently `KeyError`s on import without `ANTHROPIC_API_KEY` and reads a separate vault `.env`. Don't log env contents. |
| **Reduce redundant git ops; skip `git pull` on QUERY** — pick one git mechanism (framework vs agent tools), not both | Vault | 🟡 S | Removes network latency from read-only spoken questions. |
| **Budget schema reconciliation** — `budget_tracker.empty_budget()` helper (Intent) + `loadBudget` reads `total_*` and tolerates both shapes (UX) | Intent + UX | 🟡 S | O2. Fix writer and consumer in lockstep. |
| **Surface vault errors / always reset `second_brain_status`** even on exception paths | Vault | 🟡 M | Wrap `run()` in try/except returning a friendly spoken fallback; UX consumes the `ready/working/error` states. |
| **Surface audio-device health** to `forge_state` (`audio_status`) | Voice (+UX render) | 🟡 S | O6. Voice writes; UX renders. |
| **Correct stop/alarm trigger ordering** — check `ALARM_TRIGGERS` before `STOP_TRIGGERS` (or drop bare `"stop"` from stop) | Intent | 🟡 S | Routing-only fix; the alarm branch is currently unreachable for any phrase containing "stop". |
| **Declare optional deps** (`requests`, `beautifulsoup4`, `python-dotenv`) in `requirements.txt` | Vault | 🟢 S | A clean reimage currently `ImportError`s on the first vault command. |

### Phase 4 — UX polish, efficiency & remaining audio items

| Item | Lane | Pri/Effort | Notes |
|------|------|-----------|-------|
| **On-screen transcript confirmation / RETRY-CANCEL** | UX (+Voice hook) | 🔴 M | Most common workshop friction (misheard query, no touch recovery). Needs a small Voice-owned "re-listen" backend hook — design jointly; UX won't touch audio internals. |
| **Throttle/pause the fire canvas** (~20–24 fps cap; idle freeze) | UX | 🟡 S | Continuous full-grid `requestAnimationFrame` redraw burns CPU/heat on a fanless Pi even when idle. |
| **De-duplicate `index.html`/`preview.html`** into shared `forge.css`/`forge.js` | UX | 🟡 M | Two ~1000-line files drift today; extract incrementally, no bundler. |
| **Fix `skills/timer.py` alarm-stop bug** (`alarm_process` never set) | *unowned — see Q5* | 🟡 S | Distinct from the routing fix above. |
| **Fix Whisper temp-file leak + drop double 48k↔16k resample** (pass numpy array to faster-whisper) | Voice | 🟢 S | O8 — coordinate with Intent on the shared `/query` path. |
| **Calibrate dynamic-recording energy threshold** to the noise floor | Voice | 🟢 S | Fixed `500` lets a loud workshop defeat the silence cutoff (every utterance runs to the 30s max). |
| **Wire or delete the TTS tuning knobs** (`TTS_SPEED`/noise) | Voice (+UX knobs) | 🟢 S | O7 — half-wired today; pick one. |
| **Quiet/gate the `[DEBUG]` history-echo log lines** (`claude_integration.py:28,31,60`) | Intent | 🟢 S | Writes full user/assistant history at INFO to the unbounded log. |
| **Hide the fire dev-tuning panel** behind a deliberate long-press/multi-tap | UX | 🟢 S | A bottom-20% tap currently opens a dev panel — easy to trigger by accident. |
| **Self-host the web font** (`Share Tech Mono` → vendored `.woff2`) | UX | 🟢 S | Appliance should render fully offline; Chromium runs with `--disable-background-networking`. |
| **Remove per-frame FFT resample** in the wake-word loop (`resample_poly`/decimation) | Voice | 🟢 S | Only if profiling shows the loop is hot. |
| **Dead-code cleanup** — unused `check_interrupt_callback`, unused `format_for_speech` import | Voice | 🟢 S | Trivial readability win. |

### Phase 5 — Testing foundation & longer-term

| Item | Lane | Pri/Effort | Notes |
|------|------|-----------|-------|
| **Stand up `tests/` + `pytest`** with pure-logic unit tests | Voice + Vault + Intent | 🟢 M | O9. No tests exist anywhere. Start with pure functions (vault: `build_task_line`/`upsert_section`/`_safe_path`; audio: device resolver/silence helper/`wav_bytes_to_numpy`; intent: trigger routing table). 🔑 Tests must not import `config.secrets` or hit the network — guard Porcupine/model creation so pure helpers import in isolation. |
| **Replace keyword `classify_intent`** with a small ordered match table + word-boundary matching | Intent | 🟢 M | Fixes substring collisions ("turn one screw" → HA) and greedy `"what is"`. Do only after the 🔴 items. |
| **Opt-in `web_search` tool** on the ANSWER path (`web_search_20260209`, `WEB_SEARCH_ENABLED` flag, `pause_turn` loop with a cap) | Intent | 🟢 M | Q6 — adds latency/cost on the Pi; keep flag-gated and budget-aware. |
| **Pocket Forge reference client + client-UX spec** (record WAV → `POST /query` → play base64 audio) | UX | 🟢 M | 🔑 Client reads its bearer key from local config/env, never hardcoded. De-risks Phases 6-7. |
| **Spec/code drift cleanup** (`second-brain-agent.md` vs implemented tool signatures) | Vault | 🟢 S | Docs-only; code is source of truth. |
| **Document one git credential method** (fine-grained PAT or deploy key, stored 600) | Infra | 🟡 M | 🔑 O10 — makes deploys reproducible after a reimage. |
| **Failure-notification hook** (`OnFailure=` → HA notify / status file) | Infra | 🟢 S | A crash-looped unit is silent today. |
| **Off-device encrypted backup of `config/secrets.py`** + vault `.env` | Infra | 🔴 S | 🔑 Keys exist only on the SD card; a card failure loses every credential. Documented manual drill, never committed. |
| **Rotate the Forge `API_KEY`** to a long random token | Infra | 🟡 S | 🔑 Currently a human-readable string; rotate in lockstep with all clients (kiosk `soFetch`, future Pocket Forge). Best done *after* Q1's front door exists. |

---

## 4. 🔑 Secrets / `.env` summary (consolidated)

Every item that touches secrets is marked 🔑 above. Pulled together for one review:

- **Never log secrets:** typed-error auth branch (Phase 1), rejected-token logging (Phase 2),
  `forge_capture` env loading (Phase 3), `[DEBUG]` history lines (Phase 4).
- **Token handling:** kiosk auth must not embed the bearer in the served page (Phase 1); Pocket
  Forge client loads its key locally (Phase 5); `API_KEY` rotation in lockstep (Phase 5).
- **Storage/continuity:** off-device backup of `config/secrets.py` + vault `.env` (Phase 5); one
  documented git credential method (Phase 5).
- **All secret changes are Tyler's to perform** — no agent should rotate, print, move into git, or
  back up a key automatically.

---

## 5. Open questions for Tyler (please decide before the affected item)

1. **Remote access (Q1, Phase 2):** Is anything *outside* the Pi currently exposing port 8080
   (router port-forward, an existing tunnel)? The repo/device show none. Adopt **Cloudflare Tunnel**
   as the front door? This also gates CORS tightening.
2. **Ingress routing (Q2, Phase 1):** Fix `route_content`'s signatures surgically (Option A, ships
   now) **or** retire it and route ingress through the existing agent like the voice/API PROCESS
   path (Option B, cleaner but larger and contradicts the spec's "leave webhook as-is" note)?
3. **Vault budget accounting (Q3, Phase 3):** Should the vault's direct Claude calls
   (`second_brain.py`, `second_brain_agent.py`, `forge_capture.py`) record usage into
   `budget_tracker`? Today they bypass it, so total spend is undercounted.
4. **Log history (Q7, Phase 0):** A large log blob may already be in *pushed* git history. Leave it,
   or do a one-time history rewrite (destructive, rewrites shared history)?
5. **Alarm-stop bug (Q5, Phase 4):** Confirm the intended behavior for stopping a sounding alarm,
   and which lane owns the `skills/timer.py` fix (currently unclaimed by both Voice and Intent).
6. **Web search (Q6, Phase 5):** Do you want Forge to answer time-sensitive questions via the
   server-side `web_search` tool? It adds latency and cost on the Pi (flag-gated, budget-aware).

---

## 6. Suggested execution order at a glance

**This week:** Phase 0 (model swap before 2026-06-15; untrack logs). →
**Next:** Phase 1 critical fixes (all small except the audio-device helper). →
**Then:** Phase 2 deployment reliability (gives you safe deploys + rotation + crash protection). →
**After that:** Phase 3 config hygiene, Phase 4 polish, Phase 5 testing/longer-term — picked off
opportunistically, lowest-effort 🟡/🟢 first.

Stand up the Phase 5 `tests/` harness *early in parallel* (even during Phase 1) so each fix can ship
with a small test, per the cross-cutting constraint.
