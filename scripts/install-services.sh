#!/bin/bash
# Installs/updates the ai-radio overlay's systemd units into
# /etc/systemd/system and reloads systemd. One-time per box (and after any
# edit to a unit under systemd/). The other units (writ-panel, writ-stream)
# predate this repo and live only in /etc; only units this overlay owns are
# tracked here.
set -euo pipefail
cd "$(dirname "$0")/.."

for unit in systemd/*.service; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
  echo "installed: /etc/systemd/system/$(basename "$unit")"
done

systemctl daemon-reload
echo "systemctl daemon-reload done"
