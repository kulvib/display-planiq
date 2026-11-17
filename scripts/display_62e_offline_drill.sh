#!/usr/bin/env bash
# 62E: manual ONLY. Self-contained byte verification -> real isolated PG18 restore.
# A success is NOT an offsite guarantee, publisher signature or migration approval.
set -Eeuo pipefail
export LC_ALL=C
if [[ "$#" -ne 2 || "$1" != '--verified-bundle' ]]; then
  echo 'Usage: display_62e_offline_drill.sh --verified-bundle /absolute/private/offline/bundle' >&2
  exit 2
fi
bundle="$2"
if [[ ! "$bundle" =~ ^/[a-zA-Z0-9_./-]+$ || "$bundle" == *..* ]]; then
  echo '62E STOP: unsafe offline bundle path' >&2
  exit 2
fi
if [[ "$bundle" == /var/data/clientflow-release-artifacts* || "$bundle" == /opt/display* ]]; then
  echo '62E STOP: active Display paths cannot be restored' >&2
  exit 2
fi
if [[ -d /run/display-postgres && -d /var/data/clientflow-release-artifacts ]]; then
  echo '62E STOP: refuse to run on active Display host' >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
python3 "$root/scripts/display_62e_offline_bundle.py" --verify-bundle "$bundle" >/dev/null
bash "$root/scripts/display_62b_offline_restore.sh" --verified-stage "$bundle/stage" >/dev/null
printf '%s\n' 'DISPLAY_62E_OFFLINE_DRILL_PASS: verified self-contained release history and isolated PostgreSQL 18 restore; NO migration authorization'
