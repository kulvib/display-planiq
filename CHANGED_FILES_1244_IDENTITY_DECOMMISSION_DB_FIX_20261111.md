# PlanIQ Display – 1244 identity decommission: PostgreSQL ProgrammingError repair
Date: 2026-11-11
Source of truth: display-planiq-main(20261111-172501).zip (GitHub main 1ddc68bebe8e6fd5546939bf90226f7c03d286ae)

## Root cause (source-verified)
The one-shot decommission tried to update `client_command.end_reason`, a column absent
from both the SQLModel runtime table and the reviewed adopted PostgreSQL schema.
Its SQLite test fixture incorrectly added `end_reason`, hiding the failure.

## Correction
- Use `client_command.error_code='client_decommissioned'` for cancelled queued/claimed commands.
- Correct fake integration schema to match production (error_code instead of end_reason).
- Add a fail-closed, read-only schema check for every column used in the decommission write path,
  invoked by default preflight and inside the write transaction before any mutation.
- Add tests for the real model/production column contract, rollback upon missing required
  runtime columns, and recording cancellation reason in error_code.
- The approved ClientFlow 1.3.43/1244 release archive and catalog are unchanged.
- No database migrations, API change, environment change, installer changes or reboot.

## Validation carried out locally
48 relevant operator/transition/catalog/source tests PASS (lightweight local pytest),
with SQLite datetime-adapter warnings. GitHub CI, Render deployment and production
postflight are NOT yet re-run for this fix.

## Safety / operation sequence
1. Do NOT rerun destructive decommission against the current deployed commit.
2. While the existing commit is live, repeat the old READ-ONLY preflight to verify
   `already_decommissioned=false` and same active authority counts. Rollback is expected
   because the script uses `engine.begin()`; the readback must confirm it.
3. Review and merge these three source changes only through normal GitHub CI.
4. Confirm production Render deployment commit == new main, smoke test green,
   CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1, and physically wiped clients remain offline.
5. Rerun the NEW read-only preflight. It checks all write columns before authorizing
   another irreversible execution.
6. Perform the explicitly approved decommission only after review, then require
   PASS + independent postflight showing zero remaining active authority.
7. Do not resume installs until a separate authorization.

## Files changed
- backend/service1/clientflow_1244_identity_decommission.py
- scripts/decommission_clientflow_1244_old_identities.py
- scripts/tests/test_clientflow_1244_old_identity_decommission.py
