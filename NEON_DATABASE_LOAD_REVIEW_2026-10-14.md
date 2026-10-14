# PlanIQ Display – Neon load: verified hot paths and candidate patch

**Baseline authority:** fresh repository archive `display-planiq-main(20261014-055348).zip` and the attached 14 October 2026 Neon measurement. **All proposed code changes are unmerged and undeployed.** This note does not constitute a measured saving or an approved ClientFlow release.

## Measured workload and limits

`pg_stat_statements` was reset on 13 October at 09:43 CEST. Its ~21 h 55 min window in the report includes test/install activity, not a controlled one-client workload. Per-minute query rates are averages, not per-client rates. A later read-only query to Neon confirms that application SQL is executed as `neondb_owner`; background maintenance/telemetry SQL also appears under `cloud_admin` and must not be attributed to the application.

| Area | Reported statements | Observed rate | Root-cause assessment |
| --- | ---: | ---: | --- |
| `SELECT $1` by application role | 61,015 | 46.4/min | `pool_pre_ping=True` is explicitly configured in `backend/service1/db.py`; this can produce a ping on each pooled checkout. The fraction caused by health routes versus pool checkout has not been independently measured. Retain fail-fast stale-connection protection. |
| Livestream credential | 22,590 | 17.2/min | `require_agent_token()` previously selected credential and the full `Client` as separate SELECTs for **each** authenticated agent request, including the 15-second WebSocket wake rechecks. |
| Platform `client` | 23,461 | 17.8/min | Includes Livestream's full-client auth read and other callers; cannot uniquely attribute every call without request-tagged telemetry. |
| RD credential / client | 15,510 / 15,526 | 11.8/min each | Token verifier and 15-second control/files WebSocket rechecks each selected the credential and RD client separately. |
| Livestream status `UPDATE` | 9,157 | 7.0/min | In the repo, unchanged-status `QueueAgent` sends `POST /livestream-agent/clients/{id}/presence` but the Livestream router lacks that route. A deployed client following this path receives HTTP 404, enters degraded retry, and forces durable status writes. Production error-rate attribution still requires client/Render logs. |
| Updater replay INSERT | 4,616 | 3.5/min | Already uses token bootstrap consolidation, client+credential JOIN, once-per-token cleanup, and two mandatory replay JTIs per token. Timer runs every minute and update controller follows updater; the frequency is compatible with this existing contract. Not a proven defect. |

## Candidate changes (narrow, reversible, no schema migration)

1. Add authenticated `POST /api/livestream-agent/clients/{client_id}/presence` to the existing Livestream router. This satisfies the already-shipped QueueAgent idle protocol, preserving 15-second presence cadence and the status-write-on-change / 60-second checkpoint semantics. Every presence request still checks the current credential and platform-client lifecycle in PostgreSQL, with **no cached authorization**.
2. Replace the pair of credential and client SELECTs in `livestream_v2.require_agent_token` with one SQL JOIN, projecting only the client approval and deletion fields actually needed. Preserve token signature, audience, domain, scope, binding, credential revocation and token version checks.
3. Do the same in Remote Desktop credential login and access-token validation, plus the established control/files WebSocket's 15-second auth recheck. Preserve all original checks and the same recheck cadence, including client disabled, credential revoked, token-version mismatch, and password verification.
4. Add executable query-budget and negative security tests covering success, disabled/deleted client, revoked/version-bumped credential, invalid password and idle-presence rejection after revocation.

**Statement-model impact:** For the measured authorization requests represented by the Livestream credential and RD credential fingerprints, the relevant old two-SELECT pair becomes one SELECT. At an identical mix of requests, this *could* remove up to roughly 22,590 + 15,510 = **38,100 SELECT statements per comparable statistics window** (~29/min). This is an upper-bound model, not a measured production reduction: some calls can have different code paths. The new Livestream presence endpoint adds a credential SELECT for each 15-second idle heartbeat, replacing an HTTP 404 and forced durable status retries. Therefore do not simply subtract 38,100 to predict the total net SQL benefit.

## Why other changes are deferred

- **Database ping:** SQLAlchemy's `pool_pre_ping` prevents stale Neon connections from being reused. Removing it blindly would trade a counted read for possible failed requests. Need request-by-request checkout data or instrumentation before changing pool policy.
- **Updater:** DPoP JWT JTI replay INSERTs, expired-replay deletes and credential `last_used_at` are contract-relevant. Do not cache proofs or remove writes. Compare steady state to the existing 2 HTTP requests/minute/client model before additional tuning.
- **Livestream writer:** Status payload and timestamp still need durable checkpoints. Do not suppress changes, and do not extend heartbeat/realtime deadlines merely to save SQL.
- **Remote Desktop:** Never reduce revocation or browser session validity check cadence without security review. This patch only joins the existing reads.
- **Billing:** The report's `compute_time_seconds / 3600` is not a substitute for billing-relevant hourly `compute_unit_seconds`; Neon consumption history is still required to demonstrate CU-hour or financial impact.

## Validation gates

- Local static source contracts: 36 passed (three existing suites); Python compilation of all modified/new modules: passed.
- **Executable SQLModel query/security test requires GitHub CI**. This environment lacks SQLModel and cannot download it, so no successful execution of the new test or full suite is claimed.
- The repository README marks Livestream and RD runtime as **physically validated, frozen**. Before merge/deploy: GitHub CI green *and* documented physical regression on ClientFlow, covering idle Livestream > 2 minutes, starting/stopping Livestream, long-running wake channel, RD control/files reconnect and revocation, and 15-second live auth checks. Confirm absence of idle `/presence` 404 errors in client/Render logs.
- Before/after: timestamped `pg_stat_statements` samples by role/query fingerprint, request and checkout counts, error rates, RD/Livestream UX, 10-second Display contract, and Neon consumption-history hourly CU-seconds and transfer. Use comparable offline/online windows and do **not** reset production statistics for read-only measurement.

**No Neon/Render configuration changes, production data mutations, background jobs, extra services, migrations or ClientFlow release identity changes are included.**
