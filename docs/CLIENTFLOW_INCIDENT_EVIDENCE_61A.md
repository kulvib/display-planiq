# PlanIQ Display · incident evidence and fleet report coverage (61A)

## Scope and base

Source: `display-planiq-main(20261024-154701).zip` (2026-10-24), containing merged migration `20261024_60a_incidents` and PR #318. This changes-only package is a **backward-compatible** follow-up to the existing 60A incident model and keeps the canonical migration chain, table/column/constraint fingerprints, schema, rollout state, release catalog, updater and signing trust untouched.

## False-negative closure: persistent systemd units

The `status` domain's existing, authenticated status payload has `services` from the **active release's** installed systemd unit definitions. An explicit `inactive` is an incident only for the reviewed always-on allowlist: Status, Display agent/runtime, System agent, Browser Guard, Calendar, Terminal, updater timer, system broker socket and administrator terminal broker socket. These are persistent units/timers/sockets rather than transient one-shot commands. Unknown/missing fields cannot be interpreted as failure or recovery. Optional Remote Desktop/Livestream components, short-lived one-shots, manually controlled kiosk Chrome state and socket-activated **services** are not classified as failures simply because they are `inactive`.

An explicitly reported `failed`, `error`, `missing` or `not-found` for a known listed unit is a fault, but **only** a subsequent explicit `active` observation resolves it. An unknown, unavailable, inactive or transitioning state cannot prove recovery.

`display` domain: browser `running` is recovery evidence for a recorded runtime fault. Normal programmatic `stopped`, internet-gated `waiting_internet`, `countdown` and transitional states are not new errors **and** cannot erase a preexisting fault. Kiosk-lockdown `drifted` now registers a critical incident; only verified `applied` or `disabled` proves recovery. Domain-specific System/NTP health evidence is unchanged except that firmware recovery requires an explicit success state.

A clock-skewed observation older than an active episode's last confirmed evidence is ignored for the entire domain; it must not backdate the incident's resolved time. A reboot alone remains merely a timeline event, never proof of recovery.

## Monitoring coverage without extra client/database load

An additional **superadmin-only** `GET /api/superadmin/operational-incidents/report-coverage` endpoint reads only approved, undeleted client counts and (domain, timestamp) projections from the already-persisted canonical status table. No raw JSON payload, URL, access token, secret, client name or identity is selected or returned, and the endpoint does not poll any client or write any database record. It reports `fresh` (up to 180 s old with bounded clock skew), `stale`, and `missing` per Status/Display/System domain. The UI uses the existing 60-second refresh interval of the admin incident view. This is intentionally **not** a claim that the incident reconciliation background loop is alive: a separate test with known evidence is required to prove actual transition persistence.

Missing reports are **not** treated as recovered incidents and do not create artificial incidents; they remain clearly visible as coverage gaps. A production incident scanner's own liveness is not proved by an empty incident table.

## Testing and acceptance boundaries

- New standalone pure-Python gate covers missing/failed/inactive expected and optional systemd units, explicit recovery, programmatic browser stop versus old runtime failure, kiosk drift, firmware/broker, 100-client domain coverage and 1242 signing lock.
- SQLModel-backed tests cover actual per-client incident transitions, idempotence, reboot/clock behavior and 100-client batched ingestion with no per-client SELECTs. They **must** pass in GitHub CI together with existing PostgreSQL migrations and schema integrity gates.
- Frontend source contract enforces protected coverage view and honest presentation of missing/stale reports. GitHub's full frontend suite/build and backend CI are mandatory.
- For Heidi1: safe, read-only validation of fresh reports, no false incident for intentional browser stop, and the new coverage chips; testing deliberate network outage, systemd stop/restart or signed rollback requires a physically attended client/reserve path.

## Explicit 1242 boundary

This package does **not** change `client/release/rollback-trust.json` (`enabled=false`, no public keys), `client/release/release-input.json` (1241), any private signing key, stable rollback exporter, Render settings or deploy, and does **not** claim release 1.3.41 is ready. The independently installed `planiq-rollback-outbox-export.timer` is **not expected** on pre-1242 Heidi1. Signed rollback promotion and reporting remain a separate physical pilot after operator-approved public-key pinning; build gates must continue fail-closed.
