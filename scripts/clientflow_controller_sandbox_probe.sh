#!/usr/bin/env bash
# Physical acceptance gate for ClientFlow's privileged updater namespace.
# Read-only: systemd-run creates a transient unit and setfacl uses --test.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo 'SANDBOX_PROBE=ROOT_REQUIRED' >&2
  exit 1
fi

if [[ ! -d /home/clientflow-kiosk ]]; then
  echo 'SANDBOX_PROBE=CANONICAL_KIOSK_HOME_MISSING' >&2
  exit 1
fi

systemd-run --wait --collect --pipe \
  --unit="clientflow-controller-home-probe-$$" \
  --property=ProtectHome=tmpfs \
  --property=BindPaths=/home/clientflow-kiosk \
  /usr/bin/python3 -c '
from pathlib import Path
import subprocess
import sys

home = Path("/home/clientflow-kiosk")
if not home.is_dir():
    sys.exit("KIOSK_HOME_NOT_ACCESSIBLE")
if Path("/home/cfadmin").exists():
    sys.exit("OTHER_USER_HOME_EXPOSED")
if list(Path("/root").iterdir()):
    sys.exit("ROOT_HOME_CONTENTS_EXPOSED")
result = subprocess.run(
    ["/usr/bin/setfacl", "--test", "-P", "-R", "-m",
     "u:clientflow-remote-desktop-agent:rwX", str(home)],
    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    text=True, timeout=120, check=False,
)
if result.returncode:
    sys.exit("KIOSK_ACL_DRY_RUN_FAILED")
print("CONTROLLER_HOME_NAMESPACE=PASS")
print("CONTROLLER_KIOSK_ACL_DRY_RUN=PASS")
print("UNRELATED_HOME_DIRECTORIES_HIDDEN=PASS")
'

echo 'CLIENTFLOW_CONTROLLER_SANDBOX_PROBE=PASS'
