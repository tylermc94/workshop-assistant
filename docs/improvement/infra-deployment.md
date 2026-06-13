# Infra & Deployment — Review (Phase B)

Subject owner scope: systemd services, remote-access path, GitHub webhook + secret, the
Pi's git/deploy mechanism, log rotation, restart policies, startup ordering, process
supervision, and boot/resource reliability. **Not** in scope: application logic (voice
pipeline, intent classification, vault processing, UI rendering).

All paths are absolute. Line numbers were verified against the working tree at review time
(`/home/tyler/projects/workshop-assistant`). This report proposes changes; it does not make
them.

---

## 1. Current state

### 1.1 systemd services

Two units exist, both enabled at boot (symlinked into
`/etc/systemd/system/multi-user.target.wants/`):

**`workshop-forge.service`** — committed in the repo at
`/home/tyler/projects/workshop-assistant/workshop-forge.service` and installed at
`/etc/systemd/system/workshop-forge.service`.

- `After=network-online.target sound.target`, `Wants=network-online.target` (repo file
  lines 4–5).
- `Type=simple`, `User=tyler`, `Group=tyler`, `SupplementaryGroups=audio` (lines 8–9, 20).
- `WorkingDirectory=/home/tyler/projects/workshop-assistant` (line 11) — this is what makes
  `query_logger`'s relative `logs/all_queries.jsonl` path resolve correctly.
- `ExecStart=/home/tyler/projects/workshop-assistant/venv/bin/python src/main.py` (line 13).
- `Restart=always`, `RestartSec=10`, `TimeoutStopSec=15`, `KillMode=mixed` (lines 14–15,
  23–24).
- Output to journal (lines 16–17).

**Drift — the installed unit is NOT identical to the committed one.** `diff` of repo vs
`/etc/systemd/system/workshop-forge.service` shows the installed copy has two extra lines
the repo lacks:

```
Environment=PYTHONIOENCODING=utf-8
Environment=LANG=en_US.UTF-8
```

So the source of truth (repo) is stale relative to the running system. Anyone redeploying
the unit from the repo would silently drop the UTF-8 environment that the live process
depends on.

**`forge-ui.service`** — installed at `/etc/systemd/system/forge-ui.service`, **not present
in the repo at all** (dossier gap #20, confirmed). Contents:

- `After=network.target workshop-forge.service`, `Requires=workshop-forge.service` — UI
  starts only with the backend, and is stopped if the backend is stopped.
- `Environment=DISPLAY=:0`, `User=tyler`.
- `ExecStartPre=/bin/sleep 15` — a fixed sleep to wait for the API to bind port 8080.
- `ExecStart=chromium --kiosk --noerrdialogs --disable-infobars --no-sandbox
  --password-store=basic --disable-background-networking --disable-gcm --disable-gpu
  http://localhost:8080`.
- `Restart=on-failure`, `RestartSec=5`.

This file lives only on the SD card. If the card dies or is reimaged, this unit is lost —
there is no version-controlled copy and no install script that recreates it.

### 1.2 Startup ordering & supervision

- The backend waits for network + sound targets. There is **no health gate** — the unit is
  considered "started" the moment the Python process execs, not when the API is listening or
  Whisper/Piper/Porcupine have finished loading at import time.
- `forge-ui` papers over this with a blind `ExecStartPre=/bin/sleep 15`. On a cold boot where
  model loading is slow, 15s may be too short (Chromium loads `/` before the API binds → blank
  page until the next `Restart=on-failure`); on a warm restart it is wasted time.
- Supervision is `Restart=always` with a 10s backoff. There is no `StartLimitIntervalSec` /
  `StartLimitBurst` cap, so a hard crash-loop (e.g. a missing audio device) restarts forever
  every 10s with no escalation or alert.

### 1.3 Remote access / public URL

- Listening sockets on the Pi: `0.0.0.0:8080` (the Forge API, pid is the `python` process)
  and `0.0.0.0:22` (SSH). Nothing else.
- **No reverse proxy, no tunnel.** `cloudflared` is not installed; there is no
  nginx/caddy/NPM/frp/ngrok unit (`systemctl list-unit-files` returns nothing matching).
  `/etc/cloudflared/` does not exist.
- The API binds `0.0.0.0` (`/home/tyler/projects/workshop-assistant/src/api_server.py:736`),
  so it is reachable from anywhere on the LAN with no TLS. Any external reach (for the GitHub
  webhook, Pocket Forge over the internet, etc.) currently depends on something outside the
  Pi — most likely router port-forwarding or a manual tunnel — which is **not captured in the
  repo or on the device**. As it stands the webhook is only reachable on the LAN.
- CORS is wide open (`allow_origins=["*"]`, `allow_credentials=True`) per the dossier; that's
  an app/API concern but it compounds the "no front door" exposure story.

### 1.4 GitHub webhook

- Endpoint: `POST /webhook/ingress` in
  `/home/tyler/projects/workshop-assistant/src/api_server.py:699-724`.
- HMAC-SHA256 verification against `GITHUB_WEBHOOK_SECRET` using `hmac.compare_digest`
  (lines 712–721) — correct constant-time comparison.
- **Verification is conditional.** `webhook_secret = getattr(_secrets, 'GITHUB_WEBHOOK_SECRET',
  None)` (line 707) and the signature check is inside `if webhook_secret:` (line 709). If the
  secret is absent/empty, the endpoint accepts **any unauthenticated POST** and fires
  `ingress_processor.process_ingress()` in a background thread (line 723). The dossier confirms
  the secret is present today, so this is latent rather than active — but it is a fail-open
  design.
- The endpoint returns `{"status": "processing"}` immediately and does the work fire-and-forget
  in a thread; there is no result surfaced, no rate limiting, and no log line on success/failure
  at the infra layer.

### 1.5 Git credentials & deploy/pull mechanism

- Remote: `workshop-assistant -> https://github.com/tylermc94/workshop-assistant.git` (HTTPS,
  not SSH).
- `~/.git-credentials` exists but is **0 bytes / empty**, and **no credential helper is
  configured** anywhere (`git config --list` shows no `credential.helper`, neither repo nor
  global). So interactive `git pull`/`push` over HTTPS would prompt for a username/token. How
  pushes actually authenticate today is unclear — likely a token typed by hand or injected by
  the agent tooling. There is no documented, reproducible auth path.
- **Deploys are manual `git pull`.** The reflog shows a steady stream of
  `pull: Fast-forward` and branch checkouts — no deploy script, no CI, no auto-pull.
  `grep` for deploy/pull scripts finds only the vault git logic inside
  `src/forge_capture.py` and `src/second_brain_agent.py` (vault content, not app deploy).
- **No restart-after-deploy step.** Pulling new code does not restart the service. The only
  self-restart path is `os.execv` triggered by a `/settings` write of a `_RESTART_KEYS` key
  (`/home/tyler/projects/workshop-assistant/src/api_server.py:441-494`), which is an in-place
  re-exec of the *current* process image — unrelated to code deploys. After a `git pull` the
  running process keeps the old code until someone manually `systemctl restart
  workshop-forge`.
- A **cron job runs every 10 minutes** (user crontab):
  `*/10 * * * * cd /home/tyler/projects/workshop-assistant && venv/bin/python -c "from
  src.ingress_processor import process_ingress; process_ingress()"`. This is a second,
  parallel supervision path outside systemd — it runs the vault ingress processor on a timer
  in addition to the `/webhook/ingress` route. Its output goes to cron mail (likely unread),
  not the journal or a log file.

### 1.6 Logging & rotation

- `/home/tyler/projects/workshop-assistant/logs/workshop_assistant.log` is **527 MB**
  (confirmed via `ls -lh`). There is **no logrotate config** for it (`/etc/logrotate.d/` has
  no forge/workshop entry) and `config/logging_config.py` uses a plain `FileHandler`, not a
  `RotatingFileHandler`. It grows unbounded.
- **The big log is tracked in git.** Despite `.gitignore` listing `logs/all_queries.jsonl`,
  `logs/claude_queries.log`, and `logs/budget.json`, `git ls-files logs/` shows
  `logs/all_queries.jsonl` **and** `logs/workshop_assistant.log` are tracked. `.gitignore`
  has no effect on already-tracked files, and `workshop_assistant.log` was never even listed.
  `git status` at session start shows both as modified — meaning the 527 MB log is part of the
  working tree git is diffing, and a careless `git add -A` / `git commit` would commit a
  half-gig blob into history (and push it). This is the single biggest deployment-reliability
  and repo-health risk.
- `.gitignore` quality issues:
  - `workshop_assistant.log` is not ignored at all (no `*.log` rule).
  - Line `.idea/logs/` (under the IDE section) is a malformed pattern — almost certainly meant
    to be `.idea/` and a separate `logs/` rule; as written it ignores nothing useful.
- journald itself is healthy: `journalctl --disk-usage` = 88.6 MB (default vacuuming working).
  The unbounded growth is purely the app's own file handler.

### 1.7 Boot / resource reliability

- Pi 5, 7.9 GiB RAM, 2 GiB swap (0 used), root fs 116 GB with 24% used — plenty of headroom.
  Uptime 3d, load avg ~2.3 on 4 cores — fine.
- No `MemoryMax`/`CPUQuota` / OOM protection on either unit; not urgent given headroom, but
  the model-loading-at-import design means a restart loop re-loads Whisper/Piper/Porcupine
  each cycle (CPU/IO spike), which the missing start-limit cap would let run unbounded.

---

## 2. Proposed improvements

Each tagged priority (🔴 high / 🟡 medium / 🟢 low) and effort (S/M/L). All are
Pi-friendly, incremental, and chosen to suit a beginner — simple ops over heavy tooling.

> **Secrets items are collected separately in §2.A below**, per the brief.

### 🔴 S — Stop tracking log files in git; fix `.gitignore`
The 527 MB `workshop_assistant.log` and `all_queries.jsonl` are tracked
(`git ls-files logs/`), so they are one `git add -A` away from being committed and pushed.
- Action: `git rm --cached logs/workshop_assistant.log logs/all_queries.jsonl` (keep files on
  disk), add `*.log` and `logs/*.jsonl` to `.gitignore`, fix the malformed `.idea/logs/`
  line, then commit the removal.
- Note: this only stops *future* commits. If a large log blob is already in pushed history,
  that's a separate (L-effort, risky) history-rewrite decision — flag it, don't auto-do it.
- **Validation:** after the change, `git status` shows no `logs/` entries and
  `git check-ignore logs/workshop_assistant.log` prints the path. Add a one-line note to
  `README.md` that logs are local-only.
- **Logging/errors:** none needed — this is a repo hygiene change.

### 🔴 S — Add log rotation for `workshop_assistant.log`
Two simple options; pick one and document it.
- **Option A (preferred, in-app, beginner-friendly):** change `config/logging_config.py` from
  `FileHandler` to `logging.handlers.RotatingFileHandler` with e.g. `maxBytes=10_000_000`,
  `backupCount=5` (~50 MB cap). Self-contained, no root, survives reimage with the code.
  *(This edits app logging config — coordinate the exact change with the UX/logging owner if
  that file is considered application logic; the rotation policy itself is infra.)*
- **Option B (system logrotate):** drop `/etc/logrotate.d/workshop-forge` with
  `weekly`, `rotate 4`, `compress`, `copytruncate` (copytruncate avoids needing to signal the
  running process). Requires root and lives outside the repo (capture it in §2 install
  script).
- **Validation:** truncate the live log first (`: > logs/workshop_assistant.log` after a
  `systemctl stop`, or `copytruncate`), then generate >maxBytes of log and confirm rollover
  files appear and the active file stays bounded. For Option B: `logrotate -d
  /etc/logrotate.d/workshop-forge` (dry-run) then `-f`.
- **Errors:** RotatingFileHandler handles rollover internally; just confirm the `logs/` dir is
  created first (it already is, in `setup_logging`).

### 🔴 S — Version-control `forge-ui.service` and the installed `workshop-forge.service` env lines
The UI unit exists only on the SD card, and the installed backend unit has two `Environment`
lines the repo lacks.
- Action: copy `/etc/systemd/system/forge-ui.service` into the repo (e.g.
  `deploy/forge-ui.service`), and add the missing
  `PYTHONIOENCODING=utf-8` / `LANG=en_US.UTF-8` lines to the committed
  `workshop-forge.service` so repo == installed. Move both units under a `deploy/` directory.
- **Validation:** `diff deploy/workshop-forge.service /etc/systemd/system/workshop-forge.service`
  → identical; same for forge-ui. `systemd-analyze verify deploy/*.service` reports no
  warnings.
- **Logging/errors:** n/a (static files).

### 🔴 S — Write a tiny `deploy/install.sh` + `deploy/update.sh`
There is no reproducible way to recreate the appliance or to deploy code. Two short, readable
bash scripts (not a CI system):
- `install.sh`: copy the two unit files to `/etc/systemd/system/`, `systemctl daemon-reload`,
  `enable --now` both, install the logrotate file. Idempotent, commented.
- `update.sh`: `git pull --ff-only`, then `sudo systemctl restart workshop-forge` (UI restarts
  via its `Requires=`/`BindsTo` relationship — see next item). This closes the "pull doesn't
  restart" gap (§1.5).
- **Validation:** run `install.sh` on the live Pi and confirm `systemctl status` is green for
  both; run `update.sh` with no upstream changes and confirm it's a no-op fast-forward + clean
  restart. Add a "Deploy" section to `README.md`.
- **Errors:** `set -euo pipefail` at the top; `git pull --ff-only` fails loudly rather than
  creating merge commits; check `systemctl is-active` after restart and exit non-zero if not.

### 🟡 S — Add crash-loop protection + start-limit to `workshop-forge.service`
`Restart=always` with no `StartLimit*` means a hard failure restarts forever every 10s,
re-loading the heavy models each time.
- Action: add `StartLimitIntervalSec=300` and `StartLimitBurst=5` to `[Unit]`, and
  `RestartSteps`/`RestartMaxDelaySec` (or just keep `RestartSec=10`) to back off. After 5
  failures in 5 min the unit enters `failed` and stops hammering the CPU.
- **Validation:** temporarily point `ExecStart` at a script that `exit 1`s, confirm it stops
  after 5 tries and `systemctl status` shows `start-limit-hit`. Revert.
- **Logging:** the journal already records each restart; optionally add `OnFailure=` pointing
  at a notify unit (see 🟢 below).

### 🟡 M — Replace the UI's blind `sleep 15` with a real readiness gate
Tie `forge-ui` start to the API actually listening on 8080 rather than a guess.
- Action: change `forge-ui`'s `ExecStartPre` to a short poll loop against
  `http://localhost:8080/health` (the endpoint already exists per the dossier), e.g. a 1-line
  `bash -c 'until curl -sf localhost:8080/health; do sleep 1; done'` with an overall timeout.
  Optionally promote `workshop-forge` to a `Type=notify` or add a `forge-ready.target` later,
  but the curl gate is the beginner-friendly first step. Also consider `BindsTo=` instead of
  `Requires=` so the UI is restarted (not just stopped) when the backend restarts on deploy.
- **Validation:** cold-boot the Pi (or `systemctl restart workshop-forge.service`) and confirm
  Chromium never shows the "can't connect" page; check journal timestamps that UI start
  follows the first successful `/health`.
- **Errors:** cap the wait (e.g. `timeout 60`) so a dead backend doesn't hang UI start
  forever; on timeout let `Restart=on-failure` retry.

### 🟡 M — Decide and document the remote-access path
The webhook and Pocket Forge imply external reach, but nothing on the Pi provides it and
8080 is plaintext on 0.0.0.0. For a beginner, a **Cloudflare Tunnel** is the simplest secure
front door (no port-forwarding, TLS terminated by Cloudflare, survives CGNAT).
- Action: install `cloudflared` as a systemd service exposing only the needed routes
  (`/webhook/ingress`, `/query`, `/text`) to a hostname; keep the LAN bind for the kiosk.
  Document the tunnel config (not the token) in `deploy/`. Until then, narrow the API bind or
  add a firewall rule so 8080 isn't open to the whole network.
- **Validation:** `cloudflared tunnel info` shows healthy; external `curl` to the public
  hostname reaches `/health`; LAN kiosk still loads. Confirm the tunnel unit auto-starts on
  boot (`systemctl is-enabled`).
- **Logging/errors:** cloudflared logs to journal; add it to the `OnFailure` notify path.
- *Cross-subject:* the CORS-`*` and bind-address hardening overlap with the Intent/LLM-layer
  and UX owners who own the API app code — coordinate, don't unilaterally change CORS here.

### 🟡 S — Make the GitHub webhook fail-closed
`/webhook/ingress` accepts unauthenticated POSTs when `GITHUB_WEBHOOK_SECRET` is unset
(`src/api_server.py:709`).
- Action (infra-adjacent, but the failure mode is a deploy/exposure concern): if the secret is
  missing, return `503`/`500` and log a warning at startup rather than silently accepting. The
  one-line edit is in app code, so coordinate with the API owner; the *requirement* (never
  fail-open on a publicly reachable trigger) is ours.
- **Validation:** unset the secret in a test config → POST returns 503; set it → valid HMAC
  passes, bad HMAC 401.
- **Logging:** log `webhook signature missing/invalid from <ip>` at WARNING (do not log the
  signature or body).

### 🟢 S — Move the ingress cron job into a systemd timer (or document why it's cron)
The every-10-min ingress run is an undocumented second supervision path; its output goes to
unread cron mail.
- Action: replace the crontab line with a `forge-ingress.service` + `forge-ingress.timer`
  (`OnUnitActiveSec=10min`), so output lands in the journal alongside everything else and is
  version-controlled in `deploy/`. Keeps all supervision under systemd.
- **Validation:** `systemctl list-timers | grep forge-ingress` shows the schedule; trigger
  manually (`systemctl start forge-ingress.service`) and confirm journal output. Remove the
  crontab line only after the timer is confirmed.
- **Errors:** the service runs the same Python one-liner; set `WorkingDirectory` so relative
  paths resolve, and let failures show in the journal.

### 🟢 S — Failure notification hook
Right now a crash-looped or failed unit is silent.
- Action: a `forge-notify@.service` referenced by `OnFailure=` on the main units that posts a
  message (the project already has a Home Assistant token / could hit an HA notify service, or
  append to a status file the UI reads). Keep it dead simple.
- **Validation:** `systemctl kill` the backend into a failed state and confirm the notification
  fires.

---

## 2.A Secrets & credentials — flagged separately (central to this subject)

The dossier reports all secrets live in plaintext in
`/home/tyler/projects/workshop-assistant/config/secrets.py` (git-ignored, present on disk):
`PORCUPINE_ACCESS_KEY`, `CLAUDE_API_KEY`, `API_KEY` (Forge bearer), `GITHUB_WEBHOOK_SECRET`,
`HA_TOKEN`. I did **not** print or read their values. Observations and proposals, none of
which move secrets into git:

1. **🔴 S — Confirm `config/secrets.py` is and stays ignored, and is backed up off-device.**
   It is matched by `.gitignore` (`config/secrets.py`) and is *not* tracked
   (`git ls-files` does not list it). But because it exists only on the SD card with no
   off-device copy, a card failure loses every key. Action: document a manual, encrypted
   off-device backup of `config/secrets.py` (and the vault `.env`); do **not** commit it.
   Validation: `git check-ignore config/secrets.py` prints the path; restore-from-backup
   drill on a scratch dir.

2. **🔴 S — Forge `API_KEY` is a human-readable descriptive string** (dossier gap #1) and the
   API binds 0.0.0.0 with open CORS. Until the remote-access front door (§2 Cloudflare item)
   is in place, this bearer token is the only thing protecting `/query`, `/settings`
   (which rewrites `config/settings.py` and can re-exec the process), `/budget`, etc. Action:
   rotate it to a long random token. Rotation touches only `config/secrets.py` and every
   client's stored key — flag that clients (Pocket Forge, the kiosk's `soFetch` bearer in
   `static/index.html`) must be updated in lockstep. Validation: old key → 401, new key →
   200, kiosk still loads after its token is updated.

3. **🟡 S — `verify_api_key` logs the rejected token** (`src/api_server.py:57`, dossier gap
   #6). Rejected tokens are often *valid secrets typed against the wrong host*; writing them
   to the unbounded, git-tracked `workshop_assistant.log` is a real leak vector. Action: log
   only that auth failed + source IP, never the token value. (App-code edit — coordinate with
   API owner; the requirement is ours because it's a secret-handling/logging concern.)
   Validation: send a bad bearer, grep the log, confirm the token is absent.

4. **🟡 S — `GITHUB_WEBHOOK_SECRET` fail-open** — see §2 webhook item. The secret's *absence*
   silently disables verification. Treat the secret as mandatory for a publicly reachable
   webhook.

5. **🟡 M — Git credentials are undefined.** `~/.git-credentials` is empty and no credential
   helper is set, yet pushes happen. Action: settle on one explicit, documented auth method —
   a **fine-grained GitHub PAT scoped to this one repo**, stored via `git credential-store`
   (file mode 600) or a deploy key (SSH). Document it in `deploy/`. This keeps deploys
   reproducible after a reimage and avoids an over-scoped token. Flag: the PAT/deploy key is a
   secret — store it 600, never commit, include in the off-device backup. Validation:
   `git pull`/`push` succeed non-interactively as user `tyler`; `git config --get
   credential.helper` shows the chosen helper.

6. **🟢 S — `CLAUDE_API_KEY` is exported to the process env** by `second_brain.py` /
   `ingress_processor.py`. Env-var secrets can leak via crash dumps or `/proc`. Low priority
   on a single-user appliance; note it, don't churn it.

---

## 3. Dependencies on other subjects

- **UX / interface owner:** `static/index.html` holds the kiosk's bearer token and calls
  `/settings`, `/budget`, `/test-audio`, `/status`. Any `API_KEY` rotation (§2.A.2) or CORS
  tightening (§2 remote-access) must be coordinated so the kiosk keeps working. The UI
  readiness gate (§2 `sleep 15` replacement) depends on the `/health` endpoint they own.
- **Intent & LLM layer owner:** owns the app code I'd only adjust at the policy level — the
  webhook fail-closed change, the `verify_api_key` log-redaction, and the `0.0.0.0`/CORS bind.
  I define the infra/security requirement; they make the in-code edit.
- **Vault integration owner:** the ingress cron→timer migration (§2) and the `/webhook/ingress`
  hardening both trigger `ingress_processor.process_ingress`. Behavior of that function is
  theirs; *how and how-safely it is invoked* (timer, webhook auth) is mine. Git auth (§2.A.5)
  also affects the vault's own push/pull at `/home/tyler/second-brain`.
- **Voice pipeline owner:** the crash-loop start-limit (§2) and any `MemoryMax`/restart-policy
  tuning interact with their model-load-at-import design; a restart reloads Whisper/Piper/
  Porcupine, so restart frequency is a shared concern. The log-rotation change touches
  `config/logging_config.py` which they may consider app logic.

---

## 4. Non-goals / out of scope

- **No application-logic changes.** I will not modify the voice pipeline, intent
  classification, vault processing, or UI rendering. Where a fix lives in app code
  (webhook fail-closed, auth-log redaction, log-handler swap), I specify the requirement and
  hand the edit to the owning subject.
- **No git history rewrite** to purge the large log blob unless explicitly approved — it is
  destructive and rewrites pushed history; flagged as a separate decision.
- **No heavyweight ops tooling** (Ansible, Docker, k3s, full CI/CD). This is a single
  appliance owned by a beginner; the deliverables are two short bash scripts, version-
  controlled unit files, a logrotate rule, and a documented tunnel — nothing requiring a new
  platform.
- **No secret values printed, moved into git, or rotated by me.** I flag rotation and storage;
  the user performs key changes.
- **No `MemoryMax`/`CPUQuota` enforcement** added now — current headroom (6 GB free, 0 swap
  used) doesn't justify it; revisit only if restart-loop CPU spikes become a problem.
- **The OS-level reimage / "clean reinstall" future project** is explicitly deferred by
  CLAUDE.md until v1.0; the `install.sh` script (§2) is the down payment that makes it easy
  later, but the reimage itself is out of scope here.
