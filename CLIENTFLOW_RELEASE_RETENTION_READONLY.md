# PlanIQ Display: approved ClientFlow release storage audit (read-only)

This is the **first** gate toward keeping the three latest approved releases
on Render. It inventories only, and **does not** change installability, permit
updates/rollback, automatically delete any package, or modify the production
release catalog. `1.3.35 / 1236` stays the only selectable fresh-install target
until an independent promotion is approved.

The current `render.yaml` configures a **1-GB persistent disk** at
`/var/data/clientflow-release-artifacts`. On an authorized backend *runtime*
Render shell, from `/opt/render/project/src`:

```bash
PYTHONPATH=backend python3 scripts/audit_clientflow_release_retention.py \
  --artifact-dir /var/data/clientflow-release-artifacts/store
```

This needs no `sudo`, DB access, extra service, or package mutation. It hashes
and structurally validates each published `clientflow-<version>-seq-<n>.tar`,
checks immutable approval metadata and the named identity, and reports:

- `protected_latest`: up to three highest approved release sequences;
- `older_review_only`: older approved packages (never removed by this tool);
- `invalid_artifacts`: invalid/unapproved/symlink packages cause a **failed** audit;
- `disk_available_bytes` and `max_new_bundle_bytes_with_reserve` on the *mounted*
  filesystem, assuming publication requires a temporary copy of the new artifact;
- `retention_ready` true **only** if three verified approvals are already stored.

Use `--require-three` only after three approved packages have actually been
published. Before that, `RELEASE_RETENTION_READY=NO` is expected, rather than
an indication that additional approvals exist. An approved GitHub release
file is **not** counted unless actually present on the persistent Render disk.

## No rollback or deletion yet

Do not delete older packages merely because they appear in `older_review_only`.
First establish how active deployments reference them and verify rollback
compatibility for live client configuration and database schema. A future
release must implement explicit operator approval, compatibility gates,
anti-downgrade authorization, release provenance, and audit history before any
rollback is enabled. The production catalog remains **fresh-install-only**.

A 1-GB disk may not have enough free space to retain three bundles **and**
copy a fourth on publication; inspect the live free bytes before approving
an additional package. Neither this script nor `render.yaml` raises paid disk
capacity. The normal immutable publication command is the only supported
way to add an approved bundle; this audit is not a publication mechanism.
