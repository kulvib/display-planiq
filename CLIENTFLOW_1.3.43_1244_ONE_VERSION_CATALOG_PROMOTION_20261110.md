# ClientFlow 1.3.43 / 1244 — catalog promotion, one-version reset

**Scope:** GitHub branch for a *catalog-only* runtime selector promotion after the operator's successful 1244 Render publication. No release artifact rebuilding, publication, deletion, enrollment, client update, restart, reactivation or live Render command is included in this source change. The canonical approved 1244 TAR is immutable and remains bound to its original 7ead8cf source, not the catalog-change commit.

## Verified prerequisite evidence

- Source of truth for code: fresh repo ZIP `display-planiq-main(20261110-184925).zip`, main SHA `c0186fcbabb5252aa0e292633d1ffd4dd638a966`; user reported green GitHub CI and Render smoke.
- Independent reproducible 1244 build, Ubuntu 26.04 executable candidate gate, manual release approval and immutable GitHub archive completed. Approval run `42667579175`. Approved GitHub release tag `clientflow-1.3.43-1244-approved-transport`.
- Approved release `clientflow-1.3.43-seq-1244`, TAR SHA-256 `d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b`, size `223610880`, original source commit `7ead8cf250b7d9b7c0d1bff5b70f574e76c11f41`, approval `CF-1.3.43-1244-20261109-7ead8cf-2243141d`.
- Operator's Render Shell publication log confirms `APPROVED_BUNDLE_INTEGRITY=PASS`, `CLIENTFLOW_1244_PUBLICATION_PREFLIGHT=READ_ONLY_PASS`, `RELEASE_STORE_POSTFLIGHT=PASS`, `CLIENTFLOW_1244_RESET_ADMISSION=VERIFIED_SIX_TEMPORARY`; no automatic deletion; rollback disabled. This operational evidence is user-supplied and **not** replicated by a local container reading Render's disk.
- Prior user-confirmed DB read found Heidi1 and Viborg2 `approved/ready`, `client_version` unknown, no active enrollment tokens and no unfinished deployments; user separately confirmed **both test clients have been wiped**. Before any destructive cleanup, reread dependencies and require a separate operator attestation.

## Source change — only one current selectable version

- `catalog_sequence=1244`, `latest_stable=default_install_version=1.3.43`.
- `releases` contains **only** 1.3.43 / sequence 1244; `stable=true` as status, `installable=true`, `install_modes=[fresh_install]`, `update_allowed=false`, `rollback_allowed=false`, Ubuntu Desktop LTS >= 26.04, amd64, GNOME/Wayland, platform preflight and reboot requirement retained.
- `retention_policy.max_selectable_versions=3`, `max_installable_versions=1`, `keep_blocked_metadata=false`. Thus one version is selectable today, but future versions may progress up to a maximum three newest approved selectable versions in subsequent independently reviewed catalog changes. This is **not** a license to select old 1.3.38–1.3.42 again.
- Full historic 1243 catalog stored as an exact pinned historical **test fixture**; historic pilot and prior source-stage assertions still execute against that exact fixture, rather than silently editing or disabling old safety tests.
- A new read-only post-deploy gate checks 1244-only default, disabled manual updates and rollback, six exact published approved bundles (including strict SHA + size), fresh-install suspension and absent pilot flags. It cannot delete or deploy.

## Ordered operational gates (stop on any failure)

1. **Merge catalog-only PR only after full GitHub CI green**; Render must deploy the exact new main commit and smoke must be green. Keep `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1`, all legacy pilot env flags absent, and no outstanding activation or deployments.
2. **Post-deploy read-only gate**, in Render Shell as `display_app`:

   ```bash
   cd /opt/display
   gosu display_app env PYTHONPATH=/opt/display/backend:/opt/display \
     python3 scripts/preflight_clientflow_1244_catalog_promotion.py \
     --artifact-dir /var/data/clientflow-release-artifacts/store
   ```

   Require `CLIENTFLOW_1244_CATALOG_PREFLIGHT=READ_ONLY_PASS`. This is expected while six bundles exist and does **not** authorize removal.
3. **Next separate read-only cleanup plan**: `python3 scripts/prune_clientflow_release_retention.py --artifact-dir /var/data/clientflow-release-artifacts/store` as `display_app`. The only allowed first candidate is `clientflow-1.3.38-seq-1239` with exact verified SHA. No deletes or confirmations in this phase.
4. **Separate operator sign-off** only after independently verified zero live/offline recovery, deployment, enrollment and retained-client dependencies. The two test clients have been wiped according to the user, but recheck live database and external recovery records before irreversible actions. Validate GitHub offsite recovery archives by exact SHA and size; a GitHub tag alone does not prove independent immutability.
5. When explicitly authorized in a subsequent step, prune **one oldest** immutable store bundle per operation with both existing `--confirm-prune` and `--confirm-no-dependencies` flags and the exact current plan's ID+SHA, re-auditing after **each** removal. Order: 1239 → 1240 → 1241 → 1242 → 1243. Stop when only 1244 remains. Never remove 1244 or bypass the pinned-catalog check. No automatic cleanup.
6. Re-verify `RELEASE_RETENTION_READY=YES`, one approved bundle, source/approval/SHA, correct default and 1244-only Control Room selector. Keep fresh install suspended until separately approved maintenance exit and supervised Ubuntu 26.04 clean-install acceptance on Viborg2, then Heidi1, before general rollout.

**STOP:** Do not use 1244 source-stage preflight after promotion to authorize publication. It correctly rejects the no-longer-staged state; its tests use a frozen 1243-only pre-promotion fixture. Reproducibility for 1244 remains anchored to original approved immutable bytes, never rebuilt from the catalog-promotion commit.
