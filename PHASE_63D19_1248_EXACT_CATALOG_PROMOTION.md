# PlanIQ Display · 63D-19 · Promotion of exact approved 1248 pilot catalog

**Source-only change. Separately reviewed PR. NOT an installation authorization.**

Following the 63D-18 source-only merge, this change makes the previously SHA256-pinned `clientflow_release_catalog_1248_pilot.stage.json` the exact active `clientflow_release_catalog.json`. Both files are byte-identical. It does **not** sign, build, publish, stage, deploy, install or activate a TAR, and does **not** start any service.

## Release and security invariants

- Selectable catalog is **[1245 stable, 1247 supported/update-only source, 1248 supported/update-only target]**, with exactly 3 entries and 1 fresh-installable stable release.
- `latest_stable` and `default_install_version` remain `1.3.44` (1245); fresh install remains suspended in the existing Render environment.
- 1248 (1.3.47, `clientflow-1.3.47-seq-1248`) is only `in_place_update`, from exactly 1.3.46/1247 on the separately authorized client ID 3. No rollback, downgrade or fleet grant.
- 1246 (1.3.45) is no longer **selectable**, but its original signed artifact remains physically stored on Render. No storage mutation or retention action is part of this PR. The approved temporary four-TAR exception is unchanged.
- The 1248 artifact is pinned to SHA256 `9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff`, size `223692800`, approval `CF-1.3.47-1248-20261121-c0d5a092-f8240014`, original source `c0d5a092efe0c4e8638866ad98621481d6f5d0e8`.
- The SHA-locked 1246/1247 historical stages and original approvals remain untouched; canonical load, source audit and operator readiness have an exact 1248 validator. Any altered notes, historical record, extra release or widened install mode is rejected.
- The `/api/clientflow/release-pilot-1248/authorize` route from 63D-17 may become eligible **only through a later explicit, authenticated superadmin single-client database transaction**. Catalog promotion alone never authorizes a deployment.
- `clientflow-updater.timer` must remain disabled/inactive, and `clientflow-updater.service` and `clientflow-update-controller.service` must not be started without separate 63D-18 physical authorization and reviewed systemd override. The original updater has `OnSuccess=clientflow-update-controller.service`.
- The separate physical 63D-18 runner still requires a new canonical deployment UUID, root-private staging, correct `INVOCATION_ID` and `CREDENTIALS_DIRECTORY`, signed 1247 controller hashes, exact 1248-fixed transaction hash, backend credential binding, and local recovery checks.

## Before merge

Review full PR diff, new negative tests, original SHA256SUMS (all entries), GitHub CI and PostgreSQL smoke. Verify the `main` commit and running Render backend before and after deploying. Confirm the expected 4-store exception, unique active Update credential for Viborg1 and no pending deployment in read-only SQL.

## After merge

1. Verify Render backend live commit and active catalog 1248; verify 1245 stable/default and 1248-only update target. Validate all four stored release identities with no automatic deletion.
2. Independently prepare and inspect the **runtime-only root-owned systemd drop-in**, keeping all original LoadCredential and security hardening untouched. Do not enable timer.
3. Perform a fresh local --check, backend read-only and recovery-access check.
4. Obtain **separate operator consent** for a single new 1248 DB authorization and the physical client service start; verify authenticated backend deployment UUID before executing any one-shot operation.
5. Confirm final physical state and measure HLS, Remote Desktop, mouse/keyboard, latency, reconnect, boot and recovery before considering later fleet or retention.

**No merge in this PR is a substitute for physical acceptance or authorizes deletion of 1245–1247.**
