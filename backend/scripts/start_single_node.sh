#!/usr/bin/env bash
# Single-node Display: peer-auth Unix socket, no PostgreSQL TCP port, one app worker.
set -Eeuo pipefail

MOUNT=/var/data/clientflow-release-artifacts
PGDATA="$MOUNT/postgres/data"
SOCKET_DIR=/run/display-postgres
APP_USER=display_app
DATABASE_NAME=display
ARTIFACT_DIR="$MOUNT/store"
APP_PID=""
PG_STARTED=0

shutdown() {
  local code=$?
  trap - EXIT TERM INT
  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
    kill -TERM "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  if [[ "$PG_STARTED" -eq 1 ]]; then
    gosu postgres pg_ctl -D "$PGDATA" -m fast -w stop || true
  fi
  exit "$code"
}
trap shutdown EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

if [[ "$(id -u)" != 0 ]]; then
  echo 'single-node startup requires root to initialize volume ownership' >&2
  exit 1
fi
if [[ ! -d "$MOUNT" ]]; then
  echo "Persistent Render mount missing: $MOUNT" >&2
  exit 1
fi

install -d -m 0755 "$MOUNT/postgres"
install -d -m 0700 -o postgres -g postgres "$PGDATA"
install -d -m 0770 -o postgres -g display_app "$SOCKET_DIR"
install -d -m 0755 -o display_app -g display_app "$ARTIFACT_DIR"
install -d -m 0700 -o display_app -g display_app /tmp/display-hls

# No accidental connection to Neon, even when Render retains an old secret.
export DATABASE_URL="postgresql:///$DATABASE_NAME?host=$SOCKET_DIR"
export HLS_BASE_DIR=/tmp/display-hls
export PYTHONPATH=/opt/display/backend
export ENVIRONMENT="${ENVIRONMENT:-production}"

fresh_cluster=0
if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
  # Never reset an apparently existing/corrupt cluster silently.
  if [[ -n "$(ls -A "$PGDATA")" ]]; then
    echo 'PGDATA not empty and PG_VERSION missing; refusing destructive initialization' >&2
    exit 1
  fi
  gosu postgres initdb -D "$PGDATA" --encoding=UTF8 --locale=C.UTF-8 \
    --auth-local=peer --auth-host=scram-sha-256 --username=postgres >/dev/null
  fresh_cluster=1
fi

# No TCP listener: only postgres and display_app can access the socket.
gosu postgres pg_ctl -D "$PGDATA" -w -o \
  "-c listen_addresses='' -c unix_socket_directories=$SOCKET_DIR -c unix_socket_group=display_app -c unix_socket_permissions=0770 -c shared_buffers=32MB -c work_mem=2MB -c max_connections=32" \
  start
PG_STARTED=1

if [[ "$fresh_cluster" -eq 1 ]]; then
  gosu postgres psql -X -v ON_ERROR_STOP=1 -h "$SOCKET_DIR" -d postgres \
    -c 'CREATE ROLE display_app LOGIN'
  gosu postgres psql -X -v ON_ERROR_STOP=1 -h "$SOCKET_DIR" -d postgres \
    -c 'CREATE DATABASE display OWNER display_app'
  echo 'Initialized empty local PostgreSQL cluster'
  export MIGRATION_ALLOW_EMPTY_DATABASE=true
else
  # An existing cluster must never be silently treated as disposable.
  export MIGRATION_ALLOW_EMPTY_DATABASE=false
fi

cd /opt/display/backend
# Migrations require the persistent volume; Render preDeploy cannot see it.
gosu "$APP_USER" python scripts/run_migrations.py
unset MIGRATION_ALLOW_EMPTY_DATABASE

gosu "$APP_USER" python -m uvicorn service1.main:app \
  --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 --log-level info &
APP_PID=$!
wait "$APP_PID"
