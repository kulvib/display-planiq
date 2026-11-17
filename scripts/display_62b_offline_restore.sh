#!/usr/bin/env bash
# 62B: operator-initiated restore proof against a fresh Docker PG18 container.
# Never connects to production, never writes to an existing database/volume.
set -Eeuo pipefail
export LC_ALL=C

if [[ "$#" -ne 2 || "$1" != '--verified-stage' ]]; then
  echo 'Usage: display_62b_offline_restore.sh --verified-stage /absolute/private/offline/backuppath' >&2
  exit 2
fi
stage="$2"
# Docker bind mount syntax is comma separated. Reject ambiguous/operator-controlled
# separators and traversal in the supplied stage path before passing to Docker.
if [[ ! "$stage" =~ ^/[a-zA-Z0-9_./-]+$ || "$stage" == *..* ]]; then
  echo "62B STOP: unsafe offline stage path" >&2
  exit 2
fi
if [[ "$stage" != /* || "$stage" == /var/data/clientflow-release-artifacts* || "$stage" == /opt/display* ]]; then
  echo '62B STOP: restore must use an offline, private, nonproduction stage' >&2
  exit 2
fi
if [[ ! -d "$stage" || -L "$stage" ]]; then
  echo '62B STOP: stage is missing or redirected' >&2
  exit 2
fi
if [[ -d /run/display-postgres && -d /var/data/clientflow-release-artifacts ]]; then
  echo '62B STOP: refuse to run isolated restore on active Display host' >&2
  exit 2
fi
if ! command -v docker >/dev/null; then
  echo '62B STOP: Docker not installed; no restore was attempted' >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
python3 "$root/scripts/display_62b_backup_evidence.py" --verify-stage "$stage" > /dev/null

# A fresh unnamed Docker volume is destroyed with --volumes on cleanup.
# --network none forbids requests to Render and external databases.
container="display-62b-offline-restore-${BASHPID}"
cleanup() { docker rm --force --volumes "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT HUP INT TERM
image='postgres:18.4@sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636'
if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo '62B STOP: pinned PostgreSQL image must be present before offline restore' >&2
  exit 2
fi
secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
docker run -d --name "$container" --network none \
  --mount "type=bind,src=$stage,dst=/62b-backup,readonly" \
  -e "POSTGRES_PASSWORD=$secret" "$image" >/dev/null
unset secret
for attempt in $(seq 1 60); do
  if docker exec -u postgres "$container" pg_isready -q -U postgres -d postgres; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo '62B STOP: throwaway Postgres did not become ready' >&2
    exit 2
  fi
  sleep 1
done
docker exec -u postgres "$container" createdb -U postgres display_restore_62b
# Never print database rows, secrets, SQL statements or restore output.
docker exec -u postgres "$container" pg_restore --exit-on-error --single-transaction \
  --no-owner --no-acl -U postgres -d display_restore_62b \
  /62b-backup/database.pgdump >/dev/null

# Verify migrated schema, singleton release authority and closed DB/fleet gates.
# The check compares the immutable, pre-existing stable identity only.
check="$(docker exec -u postgres "$container" psql -X -A -t -v ON_ERROR_STOP=1 \
  -U postgres -d display_restore_62b -c \
  "SELECT CASE WHEN (SELECT COUNT(*) FROM alembic_version) = 1
       AND EXISTS (SELECT 1 FROM clientflow_release_control
         WHERE id = 1 AND stable_release_id = 'clientflow-1.3.44-seq-1245'
           AND stable_bundle_sha256 = '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5'
           AND NOT fresh_install_open AND NOT fleet_open AND NOT cutover_enabled)
     THEN 'PASS' ELSE 'STOP' END" )"
if [[ "$check" != PASS ]]; then
  echo '62B STOP: restored policy or migrations do not match the protected baseline' >&2
  exit 2
fi
# This is a genuine sandbox SQL restore, but it does not certify offsite
# durability, signed release authorization, physical pilot or live cutover.
echo 'DISPLAY_62B_OFFLINE_RESTORE_PASS: isolated PostgreSQL 18; migration and closed release policy verified'
