# ClientFlow 1.3.39 / sequence 1240 — source-stage and update/rollback acceptance

Status: **STAGED SOURCE IDENTITY ONLY** — **NOT approved**, **NOT published**, **NOT catalog-promoted**. This source-stage is not an update authorization and does not change the approved ClientFlow 1.3.38 / 1239 bundle or any installed Heidi1 runtime.

## Exact boundary

- Candidate source identity is `client/VERSION=1.3.39` and `client/release/release-input.json` `release_sequence=1240`.
- Python `3.13.14`, Ubuntu `26.04` amd64, GNOME/Wayland remain pinned. The source SHA is not known until GitHub creates the exact commit.
- The production catalog stays at `catalog_sequence=1239`, `latest_stable=1.3.38`, `default_install_version=1.3.38`, **fresh-install-only**. No user is allowed to select 1.3.39 until exact-source CI, reproducible candidate, manual approval, immutable publication and independent store verification all pass.
- Existing 1.3.38 approval reference, digest and artifact are immutable and must be preserved. No overwrite, in-place artifact mutation, re-signing or bypass of backend publication.
- Source-stage CI MUST prove the new source identity is exactly one sequence beyond the catalog while preventing `resolve_release('1.3.39')`, `resolve_release('1.3.38')` and all implicit `latest`/`stable` update requests from becoming authorized.

## Changes contained in candidate source

- GTK4 Wayland clipboard copy uses `clipboard.set(value)`, while the visible label remains authoritative and readback is checked. It must be physically paste-tested.
- Browser Guard suppresses known cookie/CMP overlays before first paint, preserves native webpage JS and URLs, retains browser profile during ordinary restarts and deliberately does not auto-accept optional cookies.
- CDP dialogs are handled without auto-confirming site actions. A website with an unknown consent implementation may require an explicit site compatibility policy; never claim arbitrary third-party content and universal popup-free display are simultaneously proven by static tests.
- Content freshness requires physical tests of updated HTML/CSS/JS/data, HTTP caching, service workers and retries, rather than wiping the browser profile.

## Separate authorization and compatibility gates before a physical upgrade

1. **Installed baseline:** On Heidi1, record ClientFlow 1.3.38 release ID/sequence, active and previous symlink, immutable 1.3.38 provenance, update credential validity, client/organization ID, config, Chrome/GUI and healthy services. Verify all healthy services with no Linux reinstall.
2. **Candidate transport:** Run entire GitHub CI for the exact source SHA, immutable runtime input transport, two byte-identical release candidate builds, on-host Ubuntu 26.04 candidate verification and explicit manual approval. Record source SHA, candidate SHA, installer SHA, approved SHA, size and approval reference.
3. **Publication:** Publish the exact approved 1.3.39 artifact on the *existing* Render persistent disk before separately promoting the release catalog. Verify file ownership, SHA, size and immutable no-replace publication. Never replace 1.3.38 bytes.
4. **Update authorization:** A **separate reviewed catalog-promotion change** must explicitly allow 1.3.39 `in_place_update` from **1.3.38** only after its update-compatibility chain is verified. Set `min_current_version=1.3.38` (and preferably an exact `max_current_version=1.3.38` for this pilot), ensure the verified approved bundle itself contains `in_place_update`, and keep all downgrade confirmations fail-closed. Until that change, the UI should reject in-place update orders.
5. **Functional acceptance:** Upgrade Heidi1 1.3.38 → 1.3.39 via the Control Room. Check the durable request/deployment phases, verified artifact, activation, restart, health, same client ID/credentials/org/config and all browser/GUI, Display, Livestream, Terminal, Remote Desktop and update-service functions. Confirm a changed webpage loads fresh content without visible cookie popups.
6. **Automatic recovery:** First test failed activation, reboot mid-activation, unreachable backend, invalid artifact and bad manifest in isolated stateful tests. Only after automated recovery and 1.3.38 health revalidation pass may failure injection be attempted on a disposable physical pilot. Fail closed for unknown recovery state.
7. **Manual rollback:** `rollback_release()` can reactivate a **locally installed and still healthy** former release using the *original* approved release reference, followed by systemd health checks. This is distinct from backend-controlled re-deployment. The current backend `resolve_release` rejects `1.3.38` for remote deployment because it is fresh-install-only; therefore do **NOT** claim Control Room rollback to 1.3.38 is possible until a separately audited/authorized rollback route and retention policy are implemented and physically tested.
8. **Repeatability:** Test 1.3.38 → 1.3.39 after rollback, idempotency, power loss, lost network, and malicious/different artifacts with same release ID. No unauthorized sequence reset.

## Hard blockers to remove only with proof

- The present production `retention_policy.max_installable_versions=1` cannot serve as a reversible multi-release catalog. Define retained, independently verified rollback artifacts and policy before promising remote rollback; never silently expand release selection.
- A fresh-install-only 1.3.38 release is **not** automatically an approved downgrade target. Automatic local rollback of an unsuccessful new activation requires the existing verified 1.3.38 local release tree; remote rollback has additional server authorization and historical artifact preconditions.
- The actual Chrome/Wayland first-paint, CMP, media, iframe and clipboard tests cannot be considered passed just because GitHub CI is green.
- Disk is currently 2 GB; before publishing a second ~223 MB artifact, verify `df -h`, database size, free-space safety margin and backup plan. A live local PostgreSQL database must not be jeopardized by artifact retention.
- Current deployment must preserve the new single-node PostgreSQL architecture; no additional Neon project, paid service or independent database dependency.

**Next gate:** source-stage GitHub CI green, then explicit runtime-input, build, approval and publication phases. The catalog and Heidi1 remain unchanged until the independently authorized steps above are completed.
