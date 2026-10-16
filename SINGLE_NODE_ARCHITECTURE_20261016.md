# PlanIQ Display: one-server architecture, remove recurring Neon compute

## Decision

**Replace Neon with PostgreSQL 18 running locally beside the FastAPI server** in
one Render Starter Docker web service with a single encrypted persistent disk.
This keeps all existing SQLModel models, Alembic migrations, PostgreSQL row
locks, transactional security and DPoP/replay contracts intact. Switching to
SQLite would require reconstructing their concurrency and SQL catalog behavior.

## Components

```
Ubuntu kiosks (later: 1 persistent authenticated multiplexed control channel)
       |
       v
Render web service (Starter, one Docker instance)
  |- FastAPI/Uvicorn, 1 worker (display_app OS user)
  |- PostgreSQL 18 (postgres OS user; Unix socket /run/display-postgres)
  |- Render encrypted persistent disk (5 GB)
       |- postgres/data (700, postgres-owned, fsync/WAL defaults)
       |- store (approved immutable ClientFlow artifacts)
       v
Render static frontend, no additional paid database service
```

The Docker image builds Python with the existing hash-locked requirements; the
PostgreSQL binaries come from the official Postgres 18.4 image. The API cannot
accidentally use Neon even if an old `DATABASE_URL` secret is present: startup
overrides it with a local peer-authenticated Unix-socket URL. PostgreSQL does
not listen on TCP. The database runs as `postgres`, while the API and schema
migrations run as the unprivileged OS/PostgreSQL role `display_app`.

## Startup and deploy constraints

The new `render-single-node.yaml` is a **separate evaluation Blueprint**. The
current `render.yaml` remains unchanged to preserve the established CI and
avoid unexpectedly changing a live Render service. Deploy the new service as a
**replacement**, not a second permanently billed instance. Keep the existing
static frontend. Switching domains/clients is a separate controlled cutover.

A Render persistent disk is unavailable during pre-deploy, so the single-node
entrypoint must initialize PostgreSQL (only on an empty disk), start it and
run `backend/scripts/run_migrations.py` *at runtime before starting Uvicorn*.
When PGDATA already exists, missing/corrupt clusters do not get silently reset.
A virgin cluster permits empty-db migrations for that startup only. Subsequent
boots fail closed if an existing catalog does not match the repository's
schema contract. SQL data survives container restarts and code deploys.

Render disks prevent zero-downtime deployment and horizontal scaling; this
architecture intentionally targets one small instance and a moderate number
of clients. Both the backend and PostgreSQL may be briefly unavailable during
a deploy. Local socket connections do not incur Neon CU or Neon data egress.
The 5 GB disk is shared by release TARs and PostgreSQL data/WAL. Free capacity
must be monitored. Render's automatic disk snapshots are *not* an independent
point-in-time recovery strategy; create separately stored off-instance backups
before claiming production-grade durability. Avoid using the single-node
service as a highly available system.

## CI proof and status

Workflow `.github/workflows/single-node-smoke.yml` builds the full Docker image
and starts a disposable test container on an isolated, empty volume. It checks
`/health/db`, initializes the complete Alembic schema, rejects PostgreSQL TCP,
creates a canary in a separate schema, restarts the container and confirms that
the canary persists. The existing GitHub backend/migration/Ubuntu gates must
still remain green. The Docker smoke has NOT been executed locally because
Docker is unavailable in the working environment; GitHub Actions is the gate.

## Financial impact (estimate only)

- One Render Starter: USD 7/month.
- Existing disk 1 GB -> evaluation disk 5 GB: USD 1.25/month total disk.
- Neon compute: USD 0 for this service **after** database cutover and stopping
  Neon usage (the Neon project itself may still incur storage/subscription
  charges; review before deletion).
- Render egress: billed separately beyond workspace included allowance. For
  15 clients, bandwidth can dominate; consolidate agent communication next.

A 5 GB disk cannot later be shrunk in Render; do not enlarge an existing disk
without checking the intended configuration. Avoid accidentally paying for
both the old and new Starter services long-term.

## Next major architectural phase: multiplexed agent control plane

Today each kiosk has separate Status, Display, Livestream, System, Terminal,
Remote Desktop and Updater request loops. Move to **one long-lived authenticated
client control channel** per kiosk for heartbeat, status changes, commands,
reconnect and acknowledgements; keep media and active remote-desktop/terminal
data channels separate, opened only during a real session. One client identity
and stream-level domain authorization; short-lived credentials and checked
revocation remain mandatory. Store only durable transitions/commands/audit,
not every unchanged heartbeat. Retain bounded recovery polling if the channel
fails. This phase requires a new ClientFlow release + parallel compatibility
window and its own CI/failure-injection testing. Do not disable existing
security checks merely to achieve cheaper SQL counts.

## Testing order

1. Upload source changes and run existing CI and the new Docker smoke workflow.
2. Review smoke output `SINGLE_NODE_SMOKE_OK`; check process memory and disk.
3. Create a replacement Render Docker Starter service using
   `render-single-node.yaml`, copy existing secret environment values, keep
   the original service until the new one passes `/health/db` and API tests.
4. Since this is non-production, initialize fresh rather than migrating user
   data. If data must be retained, use `pg_dump`/`pg_restore` to transfer it;
   never implicitly reset the old database.
5. Cut over service URL and retire Neon once no other components depend on it.
6. Test 5 / 10 / 15 clients for 24 hours with measured CPU, RAM, disk, error
   rate, status freshness, session authorization and bandwidth. If 512 MB is
   insufficient, measure before choosing a more expensive Render plan.

**Not claimed:** a successful Docker build, successful Alembic migration on
PostgreSQL 18 inside the container, sustained 15-client capacity, or a proven
billing saving. Those are gates to run in CI and the replacement environment.
