# UX / Interface — Improvement Report

Subject owner: UX / interface (touchscreen kiosk UI, SSE status push, on-screen presentation,
touch ergonomics, Pocket Forge companion client experience).

Scope note: I consume backend state (`forge_state`, `/status`, `/status/stream`, `/sensors`,
`/query`, `/text`) and present it. I do NOT touch how audio is captured/transcribed/synthesized
(Voice pipeline lane). All paths are relative to `/home/tyler/projects/workshop-assistant/`.
Line numbers verified against current source on 2026-06-13.

---

## 1. Current state

### 1.1 How the kiosk UI is served and displayed
- The UI is a single self-contained file, `static/index.html` (~1712 lines): inline CSS + vanilla
  JS, no build step, no framework. Served at `GET /` by `src/api_server.py:557-561` via
  `FileResponse(... static/index.html, headers={"Cache-Control": "no-store"})`. The `/static`
  mount (`api_server.py:38-40`) also exposes the directory.
- It is hard-sized for a **1024×600** panel: `<meta name="viewport" content="width=1024, height=600">`
  (`index.html:5`) and `html, body { width:1024px; height:600px; overflow:hidden }`
  (`index.html:12-16`). This is a fixed pixel layout, not responsive/fluid.
- Displayed by the `forge-ui` systemd service (Chromium `--kiosk` against `http://localhost:8080`;
  Dossier §5). Single fullscreen page, no navigation.
- `static/preview.html` (~968 lines) is an **offline design twin** that renders the same layout
  from `mockHistory`/mock data (`preview.html:562-588`) instead of live endpoints — useful for
  iterating on layout without the backend. It is NOT served by any route; it can drift from
  `index.html` because the two files duplicate all markup/CSS/JS by hand.

### 1.2 Layout & presentation of Forge state
- Theme: dark "forge", orange accent `#f97316`, `Share Tech Mono` font loaded from Google Fonts
  (`index.html:7-9`). Top bar with title + center clock (updates every 1s, `index.html:1235-1244`)
  + a vault status dot (`#vault-dot`, `index.html:42-46`).
- Two fixed 210px card columns (`#cards-left`/`#cards-right`, `index.html:48-56`) render Home
  Assistant sensor cards (UniFi/temp/humidity/power/OctoPrint/outlets) with 12h sparklines
  (`applySensors`, `index.html:1111`; `drawSparkline`, `index.html:1065`).
- Center "stage" (`#stage`, `index.html:92-99`) shows the pipeline state: a large `#status-label`,
  the live `#transcript`, and the `#response` text.
- A full-screen ASCII **fire canvas** animation runs behind everything (`#fire-canvas`,
  `index.html:18-24`; `loop()` at `index.html:933`), driven by `requestAnimationFrame`.

### 1.3 Live updates (SSE) — the core of this subject
- The backend exposes `forge_state.state` (`src/forge_state.py`): keys `status`
  (`idle|wake|listening|thinking|responding`), `transcript`, `response`, `second_brain_status`
  (`ready|working|error`).
- SSE endpoint `GET /status/stream` (`api_server.py:275-325`): polls the in-memory state dict
  every 50ms, serializes to JSON, and emits `data: ...` only when the payload changes; sends a
  `: keepalive` comment if 15s pass with no change. Sets `Cache-Control: no-cache` and
  `X-Accel-Buffering: no`. Hostname/IP are resolved once per connection.
- The UI subscribes with `EventSource('/status/stream')` (`index.html:1310-1313`) and routes each
  message into `applyState(data)` (`index.html:1266-1301`), which animates the status label,
  shows/hides the transcript, and lingers the final response for 10s after returning to idle
  (`index.html:1289-1293`). `STATE_MAP` (`index.html:1250-1257`) maps backend status → label+color
  and folds a `vault` status into the "THINKING…" presentation.
- Sensors are on a **separate slow poll**: `pollSensors()` every 3000ms (`index.html:1315-1323`)
  against `GET /sensors` (`api_server.py:252-255`). This split (push for fast state, poll for slow
  telemetry) is sound.

### 1.4 Touch ergonomics today
- Most interactive controls already meet a 44px minimum touch target: the gear button
  (`#gear-btn`, `min-width/height:44px`, `index.html:153-162`), settings close
  (`index.html:184-189`), tabs (`min-height:48px`, `index.html:191-204`), tune-panel tabs
  (`index.html:135-141`), and save buttons. There are **7** `min-height:44px` declarations.
- Settings are reached via a gear button (top-right) opening a full-screen overlay
  (`openSettings`, `index.html:1373`) with SETTINGS/BUDGET tabs and a left nav of sections.
- The fire canvas doubles as a hidden control: clicking the **bottom 20%** toggles a fire-tuning
  dev panel (`index.html:1326-1332`). This is a developer affordance shipped in the live UI.
- No on-screen affordance exists for a user to **see or correct** a misheard transcript, retry,
  or interact by touch with Forge's answer — the screen is display-only for the conversation.

### 1.5 The settings/budget panel auth path (BUG — see §1.6)
- Authenticated calls (`/settings`, `/devices`, `/status`, `/budget`, `/test-audio`) go through
  `soFetch` (`index.html:1362-1367`), which only attaches `Authorization: Bearer <key>` **if**
  `SO_API_KEY` is non-empty. `SO_API_KEY` is sourced solely from
  `localStorage.getItem('forgeApiKey')` (`index.html:1357-1360`).
- Save flow: `saveSection` POSTs dirty keys to `/settings` (`index.html:1534-1568`); a
  `restarting` response triggers `enterRestartMode()` (`index.html:1570-1595`), which polls
  `/status` up to 60×/2s waiting for the re-exec'd backend to return.

### 1.6 Pocket Forge companion client experience
- **There is no Pocket Forge client code in this repo.** A search for "pocket" across
  `.py/.md/.html` returns nothing; it exists only as a planned device (CLAUDE.md, Dossier §12).
- The contract it must implement is defined by the server: `POST /query` (multipart WAV,
  `api_server.py:572-642`) and `POST /text` (JSON `{text}`, `api_server.py:647-697`), both
  requiring `Authorization: Bearer <API_KEY>` and returning
  `{"transcript", "response", "audio"(base64 WAV)}`. Empty/failed transcripts return a spoken
  fallback string with `audio: ""` (`api_server.py:610-615`). The client-facing experience
  (how it captures, sends, and plays back) is entirely unbuilt.

---

## 2. Proposed improvements

Each item is tagged priority 🔴/🟡/🟢 and effort S/M/L.

### 🔴 S — Fix the kiosk settings/budget panel auth (it is silently broken today)
**Problem.** The kiosk Chromium never sets `localStorage.forgeApiKey`, so `soFetch` sends
**no** `Authorization` header (`index.html:1355-1366`), and every authenticated endpoint
(`/settings`, `/budget`, `/devices`, `/test-audio`) requires `verify_api_key`
(`api_server.py:54-62`). Result: opening Settings on the touchscreen yields 401s — load shows
nothing, Save fails. The save error path only flips a status chip to "✗ ERROR"
(`index.html:1559-1567`), so the failure is opaque.
**Touches secrets — see §5 for the explicit options.** Do NOT inline the bearer token into
`index.html` (it is served unauthenticated at `/`).
- **Tests:** a small request-level test asserting `GET /settings` with no header → 401 and with
  the correct header → 200 (documents the contract). A manual kiosk checklist: open Settings →
  values populate → toggle a non-restart key → Save → "✓ SAVED".
- **Logging:** keep server-side 401 logging but stop logging the rejected token verbatim
  (`api_server.py:57` currently logs the credential — flag to Infra/Security too).
- **Error handling:** in `soFetch`, detect `401` and surface a clear on-screen banner
  ("Settings locked — API key not configured") instead of a generic ✗.

### 🔴 S — Make the SSE connection self-healing (add `onerror`/reconnect)
**Problem.** `EventSource` is created once (`index.html:1310`) with only an `onmessage`
handler; there is no `onerror`. Native `EventSource` auto-reconnects on a dropped connection,
but when the backend re-execs during a settings save (`_restart_self_after_delay`, Dossier §3),
or crashes and is restarted by systemd (`Restart=always`), the stream can wedge in a state
where the on-screen status is stale with no visual indication. The kiosk runs unattended.
- **Tests:** manual — restart the `workshop-forge` service while watching the kiosk; confirm the
  status label recovers within a few seconds and shows a transient "reconnecting" hint.
- **Logging:** `console.warn` on `onerror` with `readyState`; optionally a tiny client error beacon
  later, but console is enough for a kiosk you can inspect via remote DevTools.
- **Error handling:** add `statusSource.onerror`; show a subtle "LINK LOST" indicator (e.g. dim
  the status label / a small dot) while `readyState === CONNECTING`, clear it on next `onmessage`.
  Add a stale-data watchdog: if no message/keepalive for ~20s, mark the UI as stale (the server
  already sends a 15s keepalive, so absence of it for 20s is a reliable signal).

### 🔴 M — On-screen transcript confirmation / "didn't catch that" feedback
**Problem.** When STT mishears, the screen shows the wrong transcript and the spoken answer,
but the user has no touch path to correct or retry — the conversation area is display-only
(§1.4). On a noisy workshop bench this is the most common friction.
- **Approach (UI-only, consumes existing state):** when `status === 'listening'/'thinking'`,
  render the interim transcript prominently (already partly done, `index.html:1279-1281`) and
  add a large touch "RETRY" / "CANCEL" pair on the stage that, when tapped, calls existing
  endpoints. RETRY can re-arm listening; CANCEL maps to the existing stop behavior. This needs a
  small backend affordance to trigger a re-listen — coordinate with the Voice pipeline agent
  rather than reaching into audio code (dependency in §3).
- **Tests:** UI unit-ish tests with `preview.html` mocks driving each `status` through
  `applyState` and asserting the controls show/hide correctly. Manual: speak a garbled phrase,
  confirm RETRY is reachable and ≥44px.
- **Logging:** log RETRY/CANCEL taps client-side (console) and, if a backend trigger is added,
  via the existing `query_logger` with a new handler tag (`source="ui"`).
- **Error handling:** debounce the buttons; disable during `thinking`/`responding` to avoid
  double-fires.

### 🟡 S — Throttle / pause the fire canvas to cut idle CPU on the Pi 5
**Problem.** `loop()` runs an unthrottled `requestAnimationFrame` (`index.html:933`) doing a full
`ROWS×COLS` grid simulation (`update`, `index.html:884-915`) plus per-cell `ctx.fillText`
(`draw`, `index.html:917-931`) **every frame, forever**, even when Forge is idle. On a fanless
Pi 5 kiosk this is continuous, pointless CPU/GPU draw and heat.
- **Approach:** cap the animation to ~20-24 fps with a timestamp gate in `loop()`; optionally drop
  to a very low frame rate (or freeze on a static last frame) when `status === 'idle'` for >N
  seconds, resuming full rate on the next state change in `applyState`. Pure presentation change.
- **Tests:** measure `top`/`vcgencmd measure_temp` before/after over a 10-min idle window
  (document numbers, no automated harness needed).
- **Logging:** none needed.
- **Error handling:** guard the rAF gate so a backgrounded tab (Chromium throttles rAF when not
  visible) resumes cleanly.

### 🟡 S — Reconcile `/budget` response shape with the tracker (UI reads the wrong shape)
**Problem.** `loadBudget` (`index.html:1634-1653`) reads `data.sessions[]` and per-session
`input_tokens`/`output_tokens`, but `budget_tracker` writes
`{total_cost, total_input_tokens, total_output_tokens}` and `sessions` is **never** populated
(Dossier §11 items 3-4). So the budget tab's per-session breakdown is always empty even when spend
exists; only `total_cost` renders. This is primarily a backend schema decision (Intent & LLM /
Infra lane), but the UI is the consumer and should be fixed in lockstep.
- **Tests:** with a budget.json containing real `total_*` fields, assert the budget tab renders
  totals (not the empty state). Add a fixture file.
- **Logging:** none client-side.
- **Error handling:** make `loadBudget` tolerant of both shapes during the transition (read
  `total_input_tokens` if present, else sum `sessions`).
- **Dependency:** coordinate the canonical shape with the Intent & LLM / budget owner (§3).

### 🟡 M — De-duplicate `index.html` / `preview.html` (shared layout, divergent data source)
**Problem.** `preview.html` hand-duplicates the entire markup/CSS/JS of `index.html` with mock
data swapped in (Dossier §9; `preview.html:562-588`). Two ~1000+ line files drift; a CSS fix in
one is easily missed in the other. For a beginner dev this doubles maintenance and review.
- **Approach (incremental, no framework):** extract the shared CSS into one `static/forge.css`
  and shared JS into `static/forge.js`, leaving each HTML file as thin markup + a small data-source
  shim (live `EventSource`/`fetch` vs. a mock object). Keep vanilla, no bundler.
- **Tests:** visual diff — load both pages, confirm identical layout. A trivial Node/py check
  that both reference the same `forge.css`/`forge.js`.
- **Logging:** n/a.
- **Error handling:** n/a; this is a refactor. Do it incrementally (CSS first, then JS) so each
  step is reviewable.

### 🟢 M — Pocket Forge companion: minimal reference client + presentation spec
**Problem.** No Pocket Forge client exists (§1.6); the device is the primary planned API consumer.
A small reference client (and a short client-UX spec) would de-risk Phases 6-7 and exercise the
API end-to-end.
- **Approach:** a minimal Python client (record WAV → `POST /query` with Bearer → decode base64
  `audio` → play) with clear states surfaced on whatever indicator the Zero 2W has (LED/sound):
  "listening", "sending", "playing", "error/offline". Document the request/response contract and
  the empty-transcript fallback behavior (`api_server.py:610-615`). Keep it a separate small file;
  it is a new client, not a change to the served kiosk UI.
- **Tests:** point the client at a running backend with `test_query.wav`; assert it gets a
  non-empty `response` and playable `audio`. A negative test: wrong/missing key → 401 handled
  with a clear local error, not a crash.
- **Logging:** client-side log of transcript/response and HTTP status per request.
- **Error handling:** timeouts, 401, 5xx, and empty-`audio` responses each map to a distinct local
  indication; never hang silently.
- **Secrets:** the client must hold the bearer `API_KEY` — see §5 (load from a local config/env,
  never hardcode).

### 🟢 S — Hide the fire dev-tuning panel behind an explicit gesture
**Problem.** A single tap in the bottom 20% of the screen opens the developer fire-tuning panel
(`index.html:1326-1332`). On a touchscreen this is easy to trigger accidentally and confusing for
a non-developer.
- **Approach:** gate it behind a deliberate long-press or a multi-tap, or move it under the gear
  Settings overlay as a "Display" dev section. Presentation-only.
- **Tests:** manual — confirm normal bottom-edge taps no longer open it.
- **Logging:** none.
- **Error handling:** none.

### 🟢 S — Self-host the web font (kiosk should not depend on Google Fonts at boot)
**Problem.** `Share Tech Mono` loads from `fonts.googleapis.com` (`index.html:7-9`). The
`forge-ui` service launches Chromium with `--disable-background-networking`; if the network is
down at boot or the CDN is unreachable, the kiosk falls back to a default monospace and the
"forge" aesthetic breaks. An appliance should render fully offline.
- **Approach:** vendor the `.woff2` into `static/` and `@font-face` it locally.
- **Tests:** load the kiosk with networking disabled; confirm the intended font renders.
- **Logging:** none.
- **Error handling:** keep a monospace fallback in the stack.

---

## 3. Dependencies on other subjects

- **Voice pipeline** — The transcript-confirmation/RETRY feature (🔴 M) needs a backend hook to
  re-arm listening or cancel cleanly; I present state and trigger an endpoint but must not modify
  Porcupine/Whisper/Piper handling. Barge-in/stop semantics (`STOP_COMMANDS`, Dossier §2.1) are
  owned there. Any new UI-driven "listen now" affordance must be designed jointly.
- **Intent & LLM layer / budget** — The `/budget` shape reconciliation (🟡 S) depends on the
  canonical schema decision (`budget_tracker` vs. the API's `{total_cost, sessions:[]}` fallback,
  Dossier §11.3-4). I consume `/budget`; the writer must agree on the shape.
- **Vault integration** — The `second_brain_status` (`ready|working|error`) drives the vault dot
  (`index.html:1296-1298`). If the vault layer adds richer progress/states, the UI presentation
  can grow with it; I depend on what `forge_state` exposes.
- **Infra & deployment** — `forge-ui.service` (Chromium kiosk flags, the 15s `ExecStartPre` sleep,
  `DISPLAY=:0`) and how/whether an API key is provisioned to the kiosk page live in the infra lane.
  The CORS-wide-open and rejected-token-logging issues (Dossier §11.5-6) are security/infra; I flag
  them because they intersect the UI's auth path but should be fixed there. The self-hosted-font
  change touches the served static assets only (mine), but offline-boot behavior is an infra
  concern.

---

## 4. Non-goals / out of scope

- **No audio backend changes.** I will not modify mic capture, wake-word, STT, or TTS internals
  (Voice pipeline lane). I only consume `forge_state`/`/status` and trigger existing endpoints.
- **No heavyweight framework / build tooling.** No React/Vue/bundler rewrite. Stay with vanilla
  HTML/JS/CSS that a beginner can read and edit; the de-dup refactor (🟡 M) is plain file
  extraction, not a toolchain.
- **No new server endpoints invented here** beyond what a feature explicitly requires, and any new
  endpoint touching audio is co-owned with the Voice pipeline agent.
- **No CORS / auth-policy redesign** — flagged for Infra/Security, not changed in this lane.
- **No responsive/multi-resolution layout work** beyond the existing 1024×600 target unless the
  panel hardware changes; the appliance has one fixed screen.
- **No full Pocket Forge product build** — the 🟢 M item is a minimal reference client + spec to
  validate the contract, not the finished companion device firmware/UX.
- **No log rotation, model-id, or settings-regex-rewrite fixes** (Dossier §11) — other lanes.

---

## 5. Secrets / .env flag (explicit, per task constraint)

Two proposals touch the bearer `API_KEY` (lives in `config/secrets.py`, git-ignored; Dossier §6):

1. **Kiosk settings panel auth (🔴 S).** The fix must get a valid bearer token to the same-origin
   kiosk page **without** embedding it in `index.html` (served unauthenticated at `/`, so anyone
   who can reach the page would read the key). Options, in order of preference, all to be decided
   with Infra/Security:
   - Make the UI-supporting GET endpoints (`/settings`, `/budget`, `/devices`, `/status`)
     **same-origin / localhost-only** and unauthenticated, keeping Bearer auth on the mutating and
     remote endpoints (`/query`, `/text`, POST `/settings`, DELETE `/budget`). This removes the
     token from the browser entirely. (Backend/infra decision.)
   - Or have `forge-ui.service` seed `localStorage.forgeApiKey` via a Chromium flag / a tiny
     localhost-only `/kiosk-config` endpoint. Less clean — the key still lands in the browser.
   - Do NOT: hardcode the key in `index.html`, in a committed JS file, or in a query string.

2. **Pocket Forge reference client (🟢 M).** The client must present `Authorization: Bearer
   <API_KEY>`. The key must be read from a local config/env file on the Pocket Forge device, never
   hardcoded into the client source or committed. Document this in the client spec.

Also flagged (security-adjacent, Infra lane): `verify_api_key` logs the rejected token verbatim
(`api_server.py:57`) and CORS is `allow_origins=["*"]` with credentials (Dossier §11.5-6).
