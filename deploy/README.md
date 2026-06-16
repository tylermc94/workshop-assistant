# Deploy

Version-controlled systemd units and helper scripts for the Lab Pi appliance.

## Files
- `workshop-forge.service` — the voice assistant + API backend (`Restart=always`,
  crash-loop capped at 5 failures / 5 min).
- `forge-ui.service` — the Chromium kiosk. Waits for the API's `/health` to answer
  before launching (instead of a blind sleep), and is `BindsTo` the backend so it
  restarts with it.
- `forge-notify@.service` — a template triggered by `OnFailure=` on the two main
  units. When a unit enters the failed state (e.g. after the crash-loop cap) it
  records a timestamped line to `logs/forge-failures.log` and an ERR journal entry
  (`journalctl -t forge-notify`). Edit it to push to Home Assistant if you want a
  phone alert. Installed but not enabled (it runs on demand).
- `install.sh` — copy both units into `/etc/systemd/system/`, reload systemd, and
  enable + start them. Idempotent; re-execs itself with sudo if needed.
- `update.sh` — `git pull --ff-only` then restart the backend (the UI restarts with
  it). Run as the `tyler` user; only the restart needs sudo.

## First-time install / after changing a unit file
```bash
./deploy/install.sh
```

## Deploy new code
```bash
./deploy/update.sh
```

## Notes
- Logs rotate automatically (`RotatingFileHandler`, ~10 MB × 5). The first run after
  this change rotates the old oversized `logs/workshop_assistant.log` to `.1`; to
  reclaim that space immediately instead of waiting for it to age out:
  `sudo systemctl stop workshop-forge && : > logs/workshop_assistant.log && sudo systemctl start workshop-forge`.
- Secrets live in `config/secrets.py` (git-ignored) — never committed. Keep an
  off-device backup; a card failure loses every key.
