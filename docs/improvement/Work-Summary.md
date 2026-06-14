# Forge Improvement — Work Summary

_Branch: `forge-improvements-phase1` · 25 commits across Phases 0–5 · 45 tests passing · all applied and verified on the live Pi · not yet merged to `main`._

---

## TL;DR

- **Everything in the improvement plan (Phases 0–5) is implemented and verified running on the Pi.** Claude works (`claude-sonnet-4-6`), the kiosk works, audio works, the timer/alarm works, vault ingress is repaired, deploys are reproducible, and prompt caching is live.
- **The one thing that was actually broken — Claude — was an out-of-credits billing issue, not code.** With your $20 reload it now answers normally.
- **Headline wins:** model migrated off a model that retired 2 days later; the 527 MB log removed from git + rotation added; the dead GitHub-ingress path repaired; the kiosk Settings panel un-broken; the alarm is now stoppable by voice; prompt caching cuts vault-operation token cost ~75% on the static prefix.
- **A new test suite was stood up** (`tests/`, pytest) — there were zero tests before; there are now 45.
- **Nothing is merged or pushed** — the running service is on the branch. Review `forge-improvements-phase1` and merge to `main` when you're ready (push is yours).
- **A few things need _you_** (can't be done safely for you): back up `config/secrets.py` off-device, rotate the `API_KEY`, and document a git-credential method. Details at the bottom.

---

## Phase 0 — Time-critical (commit `13178e8`)

- **Migrated `CLAUDE_MODEL` to `claude-sonnet-4-6`.** The old `claude-sonnet-4-20250514` retired 2026-06-15 (two days after we started); after that every voice/API answer would have failed. Pricing and `temperature` were already compatible, so it was a one-line change.
- **Stopped tracking log files in git + fixed `.gitignore`.** A 527 MB `workshop_assistant.log` and `all_queries.jsonl` were tracked and one `git add -A` away from being committed. `git rm --cached`'d them (kept on disk), broadened the ignore rules, and fixed a malformed `.idea/logs/` line. (The big log was never actually committed, so no history rewrite was needed.)

## Phase 1 — Critical bug fixes & resilience

- **Intent/LLM (`e95338d`):** `ask_claude` now runs off the asyncio event loop via `asyncio.to_thread`, so a slow Claude call no longer stalls `/status`, the SSE stream, or `/sensors`. Added typed error branches (auth / not-found / rate-limit / connection) with distinct spoken messages and request-id logging — and it never logs the API key.
- **Vault (`8085727`):** Fixed `route_content`, which called three `forge_capture` helpers with the wrong argument shapes (a string where a `Path`/dict was expected). Every routed ingress file was crashing and being silently swallowed — this had broken your **only live ingress path** (the 10-minute cron job). Also hardened `_safe_path` (the traversal guard accepted sibling dirs like `second-brain-notes`) and made the swallow-everything `except` log the real traceback.
- **Audio (`1e97f9f`):** New `src/audio_devices.py` resolves devices **by name** so a USB re-plug/reboot can't break capture or playback. Fixed the bug where the wake-word's name detection never reached the STT module (they held separate copies of the index), and the wake word now re-resolves the device after an error so a replug self-heals. (Confirmed live: it correctly picks the Scarlett at index 0, not the hardcoded `1`.)
- **UX (`286f827`):** The kiosk Settings/Budget panel was silently broken (the kiosk sends no API key, so every authed call 401'd). Added a loopback-trusted auth path: same-device (kiosk) requests work without the key being embedded in the page, while LAN/remote callers still need the bearer token (`/query` and `/text` stay strict). Also made the SSE connection self-healing (reconnect + a "RECONNECTING…" badge) and stopped logging rejected tokens.

## Phase 2 — Deployment & operational reliability (`4c4bfb4`)

- **Log rotation** — `RotatingFileHandler` (~10 MB × 5) replaces the unbounded handler.
- **Version-controlled systemd units** in `deploy/` — `workshop-forge.service` was reconciled with the live copy (the repo was missing the UTF-8 env lines) and `forge-ui.service` was captured in the repo for the first time (it lived only on the SD card). Added crash-loop protection, a real `/health` readiness gate (replacing a blind `sleep 15`), and `BindsTo` so the kiosk restarts with the backend.
- **Deploy scripts** — `deploy/install.sh` (idempotent unit install) and `deploy/update.sh` (`git pull --ff-only` + restart), plus a `deploy/README.md`.

## Phase 3 — Configuration hygiene & budget

- **Centralized vault config (`4cd9971`):** `VAULT_PATH` and `SECOND_BRAIN_MODEL` now live in `config/settings.py` instead of being hardcoded across the vault modules — the biggest step toward decoupling Forge from this specific machine.
- **Budget (`e33c272`):** `/budget` now returns the canonical token-count shape (the UI was reading a shape that was never written), and **vault Claude calls now count toward the budget** (they previously bypassed it entirely — so spend was undercounted). Visibility only; vault ops aren't blocked by the limit.
- **Stop/alarm routing + deps (`05ccd2c`):** "stop alarm" / "stop the timer" now reach the alarm handler (they were being swallowed by the generic "stop"). Declared the previously-undeclared vault deps (`requests`, `beautifulsoup4`, `python-dotenv`).
- **Vault robustness (`df3b008`):** read-only QUERY skips the git pull (faster), and a vault failure now returns a spoken fallback instead of crashing the pipeline or leaving the UI stuck on "working".

## Phase 4 — UX polish, efficiency & audio

- **Alarm-stop fix + timer cancellation (`76c2a1e`)** — _verified live._ The alarm used a blocking `subprocess.run` inside an async task (froze the event loop) and never stored a handle, so a ringing alarm could never be silenced. It now uses a non-blocking interruptible playback; "stop" silences a ringing alarm, and a pending timer can be cancelled before it rings.
- **Whisper temp-file leak fix + dead-code cleanup (`769bd37`)** — the STT temp WAV is now always cleaned up (a transcribe error used to leak it), and unused params/imports were removed.
- **TTS knobs + logging (`09631d0`)** — removed three dead TTS settings that looked meaningful but did nothing, and dropped the `[DEBUG]` history-echo log lines to `debug` so user content isn't written to the log on every call.
- **UX efficiency (`90a6216`-adjacent)** — capped the ASCII fire animation at ~24 fps (it redrew the full grid at ~60 fps forever — continuous CPU/heat on the fanless Pi), and put the fire dev-panel behind a deliberate long-press so a stray bottom-edge tap no longer opens it.
- **Deferred** (change a working audio path that needs live mic/speech to verify): dynamic energy-threshold calibration, the wake-word resample swap, the API double-resample. Plus three larger items: on-screen transcript RETRY, `index.html`/`preview.html` de-dup, and self-hosting the web font.

## Phase 5 — Prompt caching, web search, spec, failure-notify

- **Prompt caching on the vault agent** — _verified live._ One `cache_control` breakpoint caches the static tools+system prefix (measured at 2,720 tokens — clears Sonnet 4.6's 2048 minimum). On a multi-round vault op, rounds 2+ read that prefix at 0.1× instead of full price (saw `cache_write=2720` → `cache_read=2720`). The budget tracker was updated to price cache write (1.25×) and read (0.1×) tokens correctly. **Note:** this only works on Sonnet 4.6 (Opus 4.8's minimum is 4096) — there's a code comment to re-verify if the model ever changes.
- **Opt-in web search** — _verified live._ The ANSWER path can use Claude's `web_search` tool, gated behind `WEB_SEARCH_ENABLED` (default **OFF**) with a `pause_turn` continuation cap. Flip it on in settings to let Forge answer time-sensitive questions; with it on, a test query returned a post-cutoff fact at ~$0.05 vs ~$0.001 for a normal answer (hence default-off). A per-search fee is not captured by the token budget.
- **Spec reconciliation** — updated `docs/superpowers/specs/second-brain-agent.md` to match the implemented agent (system-prompt sources, `run_command` enum, and the enhancements added since the original spec).
- **Failure-notification hook** — `deploy/forge-notify@.service`, triggered by `OnFailure=` on both units, records a timestamped line to `logs/forge-failures.log` and an ERR journal entry when a unit fails (e.g. after exhausting the crash-loop cap). Edit it to push to Home Assistant for a phone alert.

---

## What was verified live on the Pi

- Service restarts cleanly throughout (`NRestarts=0`); no errors in the log.
- Claude answers normally (`claude-sonnet-4-6`); both the vault-classifier and answer calls are budget-tracked.
- Kiosk auth: loopback open, LAN requires the token, bad token rejected.
- Audio output resolver drives `aplay`; the input resolver picks the Scarlett correctly.
- Alarm: set → ring → stop, and set → cancel-before-ring.
- Prompt caching: `cache_read` > 0 on a vault query, priced correctly.
- Web search: returned current info when enabled, then reverted to off.
- Log rotation: the old oversized log rotated to `.1` and the active log is small.
- All three installed systemd units are in sync with the repo.

## What needs you (🔑 — intentionally not done for you)

1. **Back up `config/secrets.py` and the vault `.env` off-device.** Every key (Anthropic, Porcupine, Forge API key, HA token, webhook secret) lives only on the SD card — a card failure loses all of them.
2. **Rotate the Forge `API_KEY`** to a long random token (it's currently a human-readable string) and update the clients in lockstep.
3. **Document one git-credential method** (a fine-grained PAT or deploy key) so deploys are reproducible after a reimage.
4. **Review and merge `forge-improvements-phase1` to `main`**, then push. The running service is currently on the branch.

## Still open / deferred (not blocking)

- Audio-path tuning that needs live speech: energy-threshold calibration, wake-word resample swap, API double-resample.
- Larger UX items: on-screen transcript RETRY/CANCEL, `index.html`/`preview.html` de-dup, self-hosted web font.
- `classify_intent` keyword-router rewrite, a Pocket Forge reference client.
- Cloudflare Tunnel + CORS tightening (deferred while LAN-only — your decision).
- Optional: route the GitHub-webhook ingress through the agent (we did the surgical fix instead).

Full detail and per-item priorities are in `docs/improvement/Forge-Improvement-Plan.md`.
