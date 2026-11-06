#!/usr/bin/env bash
# One-time, explicit bridge for an already-installed 1.3.38 controller.
# Safe by default: WITHOUT --apply --confirm-clientflow-1338 it does not write.
# Never run this during an active or pending backend deployment.
set -euo pipefail

UNIT='clientflow-update-controller.service'
FRAGMENT='/etc/systemd/system/clientflow-update-controller.service'
DROPIN_DIR='/etc/systemd/system/clientflow-update-controller.service.d'
DROPIN="$DROPIN_DIR/90-clientflow-home-bridge.conf"
EXPECTED='clientflow-1.3.38-seq-1239'

# A production controller may already be running with an older sandbox policy.
# Never change the unit underneath that process: perform this attended,
# one-time host preflight only while the stable updater timer is stopped.
case "$#:${1:-}:${2:-}:${3:-}" in
  '0:::') MODE=check ;;
  '1:--check::') MODE=check ;;
  '3:--apply:--confirm-clientflow-1338:--confirm-backend-idle') MODE=apply ;;
  *)
    echo 'Usage: script [--check] OR --apply --confirm-clientflow-1338 --confirm-backend-idle' >&2
    exit 2 ;;
esac

if [[ ${EUID} -ne 0 ]]; then
  echo 'CONTROLLER_BRIDGE=ROOT_REQUIRED' >&2
  exit 1
fi

# Verification is intentionally independent of the updater-controller; it may
# be disabled during a previous failed transaction.
/usr/bin/python3 - <<'PY'
import json
import os
from pathlib import Path

state = json.loads(Path('/var/lib/clientflow/release/state.json').read_text())
expected = 'clientflow-1.3.38-seq-1239'
assert state.get('schema_version') == 2
assert state.get('active_release_id') == expected
assert state.get('activation_intent') is None
assert state.get('previous_release_id') is None
# The anti-rollback high-water mark is intentionally NOT reset: a failed newer
# version remains in immutable local history after a verified recovery.
assert int(state.get('highest_release_sequence', 0)) >= 1239
assert os.readlink('/opt/clientflow/active') == 'releases/' + expected
assert Path('/opt/clientflow/active').is_dir()
print('BRIDGE_ACTIVE_1338_STATE=PASS')
PY

[[ $(systemctl is-active clientflow-updater.timer) == inactive ]] || {
  echo 'BRIDGE_UPDATER_TIMER_MUST_BE_STOPPED' >&2; exit 1;
}
[[ $(systemctl show "$UNIT" -p NeedDaemonReload --value) == no ]] || {
  echo 'BRIDGE_SYSTEMD_REQUIRES_RELOAD_BEFORE_PREFLIGHT' >&2; exit 1;
}
[[ $(systemctl is-active "$UNIT") == inactive ]] || {
  echo 'BRIDGE_CONTROLLER_MUST_BE_IDLE' >&2; exit 1;
}
[[ $(systemctl is-active clientflow.target) == active ]] || {
  echo 'BRIDGE_TARGET_NOT_ACTIVE' >&2; exit 1;
}
[[ $(systemctl is-enabled clientflow.target) == enabled ]] || {
  echo 'BRIDGE_TARGET_NOT_ENABLED' >&2; exit 1;
}
[[ ! -L "$FRAGMENT" && -f "$FRAGMENT" ]] || {
  echo 'BRIDGE_UNIT_FRAGMENT_INVALID' >&2; exit 1;
}
[[ $(systemctl show "$UNIT" -p FragmentPath --value) == "$FRAGMENT" ]] || {
  echo 'BRIDGE_UNIT_FRAGMENT_MISMATCH' >&2; exit 1;
}
grep -Fxq 'User=root' "$FRAGMENT"
grep -Fxq 'ProtectHome=yes' "$FRAGMENT"
[[ $(systemctl show "$UNIT" -p ProtectHome --value) == yes ]] || {
  echo 'BRIDGE_LOADED_POLICY_MISMATCH' >&2; exit 1;
}
[[ -z $(systemctl show "$UNIT" -p BindPaths --value) ]] || {
  echo 'BRIDGE_LOADED_BIND_MISMATCH' >&2; exit 1;
}
# The on-disk unit must still match the immutable active release. Never bridge
# a locally modified or partially replaced definition.
/usr/bin/python3 - <<'PYUNIT'
from pathlib import Path
fragment = Path('/etc/systemd/system/clientflow-update-controller.service')
source = Path('/opt/clientflow/active/client-runtime/systemd/clientflow-update-controller.service')
assert fragment.is_file() and not fragment.is_symlink()
assert source.is_file() and not source.is_symlink()
assert fragment.read_bytes() == source.read_bytes(), 'CONTROLLER_DEFINITION_DRIFT'
print('BRIDGE_IMMUTABLE_SOURCE_MATCH=PASS')
PYUNIT
if grep -Eq '^(BindPaths|BindReadOnlyPaths)=' "$FRAGMENT"; then
  echo 'BRIDGE_UNEXPECTED_EXISTING_HOME_BINDS' >&2
  exit 1
fi
if [[ -e "$DROPIN_DIR" || -L "$DROPIN_DIR" ]] || \
   [[ -n $(systemctl show "$UNIT" -p DropInPaths --value) ]]; then
  echo 'BRIDGE_EXISTING_DROPIN_REQUIRES_MANUAL_REVIEW' >&2
  exit 1
fi

echo 'BRIDGE_PRECONDITIONS=PASS'
if [[ $MODE == check ]]; then
  echo 'BRIDGE_DRY_RUN_ONLY=PASS'
  echo 'To change this host: sudo bash script --apply --confirm-clientflow-1338 --confirm-backend-idle'
  exit 0
fi

# Do not modify the verified release, symlink, or release state.
install -d -o root -g root -m 0755 "$DROPIN_DIR"
TMP=$(mktemp "$DROPIN_DIR/.bridge.XXXXXXXX")
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'EOF'
[Service]
# One-time bridge until the new release embeds this policy itself.
ProtectHome=tmpfs
# Clear any bind from the future target unit, then apply exactly one.
BindPaths=
BindPaths=/home/clientflow-kiosk
EOF
chmod 0644 "$TMP"
chown root:root "$TMP"
# Publish without clobbering a concurrently created drop-in. The hard link
# fails with EEXIST, unlike mv -n which can silently succeed without replacing.
ln -- "$TMP" "$DROPIN"
rm -f "$TMP"
systemctl daemon-reload

if [[ $(systemctl show "$UNIT" -p ProtectHome --value) != tmpfs ]] || \
   [[ $(systemctl show "$UNIT" -p NeedDaemonReload --value) != no ]] || \
   [[ $(systemctl show "$UNIT" -p BindPaths --value) != /home/clientflow-kiosk:/home/clientflow-kiosk:rbind ]]; then
  echo 'BRIDGE_EFFECTIVE_SYSTEMD_CONFIGURATION_INVALID' >&2
  exit 1
fi
[[ $(systemctl show "$UNIT" -p DropInPaths --value) == "$DROPIN" ]] || {
  echo 'BRIDGE_UNEXPECTED_LOADED_DROPIN' >&2; exit 1;
}
systemd-analyze verify "$FRAGMENT"
echo 'CLIENTFLOW_1338_CONTROLLER_BRIDGE=PASS'
echo 'Pilot release must still pass all normal backend gates and physical sandbox probe.'
