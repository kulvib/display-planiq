# PlanIQ Display: approved ClientFlow release storage and retention

Current policy: **at most FOUR of the latest approved ClientFlow release TARs**
physically on the persistent Render release-store disk. Approved release
bundles count whether they are stable, pilot, or later found faulty in the
field. Catalog selectors, cached runtime files, local client releases and
historical audit records do not count as Render approved bundles.

Read `CLIENTFLOW_1340_FOUR_RELEASE_RETENTION_AND_ROLLBACK_TEST_PLAN.md` for
the current operator procedure and client rollback acceptance plan. This
supersedes the older three-release *planning target*; historical 1.3.35
release statements are intentionally not rewritten.

## Read-only inventory

Run from the backend **inside Render** as the `display_app` user (application
root is `/opt/display`):

```bash
gosu display_app env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/opt/display/backend:/opt/display \
  python3 /opt/display/scripts/audit_clientflow_release_retention.py \
  --artifact-dir /var/data/clientflow-release-artifacts/store
```

- Every matching TAR is validated for immutable approval, archive structure,
  whole-bundle hash, release ID, secure owner and file type. Any corruption,
  unexpected symbolic link or noncanonical release filename fails the audit.
- `approved_count`, `approved_limit`, `protected_latest`,
  `older_review_only`, `within_approved_limit` and `retention_ready` are
  machine-readable. **An audit's normal `PASS` means a safe inventory**, not
  necessarily that there are only four. Require `within_approved_limit=true`
  to conclude compliance.
- `--require-four` requires **exactly** four verified approved TARs. The
  legacy `--require-three` option is supported for older operational scripts,
  but now performs the same four-bundle acceptance gate.
- A publication that would exceed four is refused before temporary copying.
  Two concurrent publishers cannot both pass the count gate unnoticed because
  they serialize on a kernel directory `flock`.
- `scripts/prune_clientflow_release_retention.py` is read-only by default and
  may report the single oldest eligible release when four or five exist. Destructive
  cleanup requires explicit approval and independent dependency review.
  **Do not use either destructive flag without that approval.**
- Automatic deletion is **not enabled**. This deliberate fail-closed behavior
  prevents retention policy from deleting the only recovery path of an
  offline client. Future automatic release rotation requires a separately
  audited fleet dependency/pinning model.

## What is not authorized

This policy alone never enables release rollback, downgrade, automatic
updates, catalog promotion, client reboot or deletion of an artifact.
The 1.3.40 pilot remains a separate manually authorized client deployment.
If a needed older version would be removed, pause and investigate rather
than bypassing retention or anti-rollback protections.
