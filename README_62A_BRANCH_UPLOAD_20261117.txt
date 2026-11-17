PlanIQ Display · Phase 62A · NON-DESTRUCTIVE batch
===================================================

Source of truth: display-planiq-main(20261117-103549).zip
Source main: d280417040dc662b9d9b0d1f901d73d66563174f
Suggested branch: feature/display-62a-storage-readonly-release-preview-ux-20261117

Upload the files contained in this ZIP on a new branch from this exact main,
retaining their repository-relative paths. Do NOT upload a replacement whole
repository; do NOT deploy this patch to physical clients.

Changes in one batch:
1. ClientFlow Releases: shared Opdater button in the top-right header position.
2. New read-only /api/clientflow/release-administration/preview verifies each
   selected client's canonical active Status-agent version and policy revision.
3. /drafts repeats the same verification, so a stale browser cannot bypass it.
4. Read-only local PGDATA/release-store/SHA256 migration preflight. Never a
   backup, restoration, live migration, deployment or sign-off.
5. HTTP, frontend, source and filesystem negative regression tests.
6. Operator runbook with non-destructive backup/restore prerequisites.

Safety gates: no new deployment/rollback or physical acceptance endpoint;
current stable bundle 1.3.44/1245 unchanged; source candidate remains unsigned
1.3.45/1246; no migrations, environment variables or Render disk mutations.

Test scope on local working copy:
- New standard-library & source policy tests 8/8 PASS
- Node frontend release UX tests 4/4 PASS
- Broad script tests 796 PASS, excluding environment-dependent tests and
  separately verified branding 3/3 PASS
- CI's backend HTTP tests cannot run here without sqlmodel; GitHub CI required.

Before merge: all required GitHub CI jobs must pass (no weakened tests).
After merge / Render only: GET release administration returns stable 1.3.44;
Viborg1 v1.3.43 remains visible; select it, preview server validation must
succeed without creating deployment; do not authorize release/rollback.
A separate operator-approved phase is needed for actual database/artifact
backup, independent restoration, hosting topology change, pilot and rollout.
