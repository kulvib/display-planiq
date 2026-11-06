#!/usr/bin/env bash
# Read-only physical-client evidence for a superadmin's manual recovery ACK.
# Never mutate release state, reboot, reload systemd, or restart any service.
set -euo pipefail

[[ ${EUID} == 0 ]] || { echo 'RECOVERY_ATTESTATION=ROOT_REQUIRED' >&2; exit 1; }

/usr/bin/python3 - <<'PY'
import json
import os
from pathlib import Path

state = json.loads(Path('/var/lib/clientflow/release/state.json').read_text())
active = state.get('active_release_id')
assert isinstance(active, str) and active.startswith('clientflow-')
assert state.get('activation_intent') is None, 'unresolved activation intent'
assert state.get('previous_release_id') is None, 'unresolved previous release'
assert os.readlink('/opt/clientflow/active') == 'releases/' + active, 'active symlink mismatch'
assert Path('/opt/clientflow/active/VERSION').is_file()
assert active in state.get('installed', {}), 'active release not installed'

history = state.get('history', [])
failures = [i for i, event in enumerate(history)
            if isinstance(event, dict) and event.get('event') == 'automatic_rollback_failed']
assert failures, 'no recorded failed automatic rollback'
last_failure = history[failures[-1]]
completed = [event for event in history[failures[-1] + 1:]
             if isinstance(event, dict)
             and event.get('event') == 'automatic_rollback_completed'
             and event.get('failed_release_id') == last_failure.get('release_id')
             and event.get('restored_release_id') == active]
assert completed, 'no matching completed recovery'

print('ACTIVE_RELEASE=' + active)
print('LAST_FAILED_RELEASE=' + str(last_failure['release_id']))
print('RECOVERY_HISTORY=PASS')
PY

[[ $(systemctl show clientflow-update-controller.service -p NeedDaemonReload --value) == no ]] || {
  echo 'RECOVERY_ATTESTATION=SYSTEMD_RELOAD_REQUIRED' >&2; exit 1;
}
for unit in clientflow.target clientflow-status-agent.service clientflow-display-runtime.service \
            clientflow-browser-guard.service clientflow-remote-desktop-agent.service; do
  [[ $(systemctl is-active "$unit") == active ]] || {
    echo "RECOVERY_ATTESTATION=INACTIVE_UNIT $unit" >&2; exit 1;
  }
done

echo 'RECOVERY_ATTESTATION=PASS'
echo 'This output supports, but never automatically performs, the superadmin acknowledgement.'
