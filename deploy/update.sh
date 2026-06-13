#!/usr/bin/env bash
# Pull the latest code and restart Forge so the running process picks it up.
# Run this as the normal 'tyler' user — git uses your credentials; only the
# systemctl restart needs sudo (it will prompt).
#
# Usage:  ./deploy/update.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

echo "Pulling latest code (fast-forward only)..."
git pull --ff-only

echo "Restarting workshop-forge (forge-ui restarts with it via BindsTo)..."
sudo systemctl restart workshop-forge.service

# Type=simple: the unit is 'active' as soon as the process execs. Models finish
# loading a few seconds later; this just confirms the process came back up.
sleep 2
if sudo systemctl is-active --quiet workshop-forge.service; then
  echo "workshop-forge is active."
else
  echo "ERROR: workshop-forge is not active after restart." >&2
  echo "Check logs with: journalctl -u workshop-forge -n 50" >&2
  exit 1
fi
