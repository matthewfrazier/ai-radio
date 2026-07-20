#!/usr/bin/env bash
# One-shot migration of the station's INTERNAL infrastructure names from "writ"
# to "home": the /opt/writ-fm working dir -> /opt/home-fm, and the writ-* systemd
# units -> home-*. Branding (HOME-FM) is already done in the code; this is the
# invisible plumbing, so there is no user- or listener-facing change here.
#
# DESTRUCTIVE + brief downtime: the station drops to the static loop for the
# ~30-60s cutover. Run as root in a maintenance window:
#     sudo bash /opt/writ-fm/scripts/migrate-writ-to-home.sh
#
# Scope: THIS box only. The mac/ operator subsystem (its WRIT_* env-var contract)
# and archival docs are deliberately left untouched. Only the specific infra
# tokens below are rewritten -- never a bare s/writ/home/, which would corrupt
# identifiers like write_state / written / writer.
#
# After it succeeds, commit the result:
#     git -C /opt/home-fm add -A && git -C /opt/home-fm commit -m "rename infra writ->home"
set -euo pipefail

OLD=/opt/writ-fm
NEW=/opt/home-fm
SD=/etc/systemd/system

# Run from a throwaway copy so moving $OLD can't pull this script out from under
# bash mid-execution.
if [ "${MIGRATE_REEXEC:-}" != 1 ]; then
  [ -f "$0" ] || { echo "run me as a file, not via a pipe"; exit 1; }
  tmp=$(mktemp /tmp/migrate-home.XXXXXX.sh)
  cp "$0" "$tmp"
  MIGRATE_REEXEC=1 exec bash "$tmp" "$@"
fi

[ "$(id -u)" = 0 ] || { echo "must run as root"; exit 1; }
[ -d "$OLD" ] || { echo "no $OLD -- already migrated?"; exit 1; }
[ -e "$NEW" ] && { echo "$NEW already exists; aborting to avoid clobber"; exit 1; }

# The targeted token rewrites, shared by the tree pass and the unit pass.
sed_tokens() {
  sed -i \
    -e 's#/opt/writ-fm#/opt/home-fm#g' \
    -e 's#writ-block-player#home-block-player#g' \
    -e 's#writ-block-cleanup#home-block-cleanup#g' \
    -e 's#writ-panel#home-panel#g' \
    -e 's#writ-stream#home-stream#g' \
    -e 's#writstub#homestub#g' \
    -e 's#WRIT-FM#HOME-FM#g' \
    "$@"
}

echo "==> stopping + disabling writ-* units"
systemctl stop writ-block-player.service 2>/dev/null || true
systemctl stop writ-stream.service writ-panel.service writ-block-cleanup.timer 2>/dev/null || true
systemctl disable writ-panel.service writ-stream.service writ-block-cleanup.timer 2>/dev/null || true

# Only THIS station's code/scripts/units -- an explicit allowlist. README.md,
# docs/, config/stations.yaml and the `writ` CLI belong to the multi-station mac
# framework (its WRIT_* / writ-fm contract) and are deliberately left alone;
# PLAN.md and other *.md are archival. This is why we don't sweep all tracked
# files.
echo "==> rewriting infra tokens in station code/scripts/units"
while IFS= read -r f; do
  case "$f" in mac/*) continue;; esac
  p="$OLD/$f"
  [ -f "$p" ] || continue
  sed_tokens "$p"
done < <(git -C "$OLD" ls-files '*.py' 'scripts/*.sh' 'systemd/*' 'stream.sh' 'stream.sh.stub')

echo "==> renaming tracked systemd unit files in the repo"
while IFS= read -r u; do
  case "$u" in systemd/writ-*) ;; *) continue;; esac
  nu=${u/writ-/home-}
  git -C "$OLD" mv "$u" "$nu" 2>/dev/null || mv "$OLD/$u" "$OLD/$nu"
done < <(git -C "$OLD" ls-files systemd)

echo "==> moving $OLD -> $NEW"
mv "$OLD" "$NEW"

echo "==> installing home-* units from the live writ-* units, removing the old"
for u in "$SD"/writ-*.service "$SD"/writ-*.timer; do
  [ -e "$u" ] || continue
  nb=$(basename "$u"); nb=${nb/writ-/home-}
  cp "$u" "$SD/$nb"
  sed_tokens "$SD/$nb"
  rm -f "$u"
done

systemctl daemon-reload

echo "==> enabling + starting home-* units"
systemctl enable home-panel.service home-stream.service home-block-cleanup.timer
systemctl start home-panel.service home-stream.service home-block-cleanup.timer
# home-block-player has no [Install] by design -- the panel starts it on demand
# and reconciles the queue on boot, so we don't start it here.

echo "==> verifying"
sleep 2
systemctl is-active home-panel.service home-stream.service || true
curl -fsS -o /dev/null -w "panel /now -> %{http_code}\n" http://127.0.0.1:8080/now || echo "panel not responding yet"

cat <<'DONE'

==> migration complete.
    - If the Cast venv (/opt/home-fm/.venv-cast) misbehaves, recreate it: moving
      a venv can strand console-script shebangs (the interpreter itself relocates
      fine). The main flows call `.venv-cast/bin/python cast_ctl.py` directly.
    - Commit the rename:
        git -C /opt/home-fm add -A && git -C /opt/home-fm commit -m "rename infra writ->home"
    - The old writ-* units are removed; `systemctl status home-panel home-stream`
      should show the new names.
DONE
