#!/usr/bin/env bash
# Install or refresh the Workshop Forge systemd units. Idempotent — safe to
# re-run any time the unit files in this directory change.
#
# Usage:  ./deploy/install.sh        (re-execs itself with sudo if needed)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR=/etc/systemd/system
# All unit files to install. forge-notify@ is a template triggered on demand by
# OnFailure= — it is copied (so instances can start) but never enabled directly.
UNIT_FILES=(workshop-forge.service forge-ui.service forge-notify@.service)
ENABLE_UNITS=(workshop-forge.service forge-ui.service)

# Installing units and talking to systemd needs root.
if [[ $EUID -ne 0 ]]; then
  echo "Re-running with sudo..."
  exec sudo "$0" "$@"
fi

echo "Installing unit files into ${SYSTEMD_DIR}..."
for unit in "${UNIT_FILES[@]}"; do
  cp "${SCRIPT_DIR}/${unit}" "${SYSTEMD_DIR}/${unit}"
  echo "  installed ${unit}"
done

echo "Reloading systemd..."
systemctl daemon-reload

echo "Enabling and starting units..."
for unit in "${ENABLE_UNITS[@]}"; do
  systemctl enable --now "${unit}"
done

echo
echo "Done. Current status:"
for unit in "${ENABLE_UNITS[@]}"; do
  printf '  %-26s %s\n' "${unit}" "$(systemctl is-active "${unit}" || true)"
done
