# ClientFlow 1.3.42/1243 — catalog promotion, NOT physical rollout

## Recorded approvals and publication

The exact ClientFlow 1.3.42/1243 release was approved for an attended Viborg2-only recovery pilot with approval reference `CF-1.3.42-1243-VIBORG2-PILOT-20261107`. Approved bundle SHA-256: `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`; size: **223610880 bytes**; source commit: `b870cf8c3fa90286c6b4dccaae593eb8a0d57565`; candidate SHA-256 `4e52cbfbaa844c2d835e5b57f625b5a64cb98346c428ee410aead02b7c67c88a`; installer SHA-256 `e23fefccb4c126fee82a807ce0ffe22ddc5051aa8b6b53ca1907161622e126f3`.

The approved TAR is held in GitHub Releases under `clientflow-1.3.42-1243-approved-transport` and has been separately downloaded, hash-verified and published to the Render immutable release-store: `APPROVED_DOWNLOAD_VERIFIED=PASS`, `RELEASE_STORE_POSTFLIGHT=PASS`, `CLIENTFLOW_1243_TRANSITION=VERIFIED_FIVE_TEMPORARY`, `CLIENTFLOW_1243_PUBLICATION_COMMAND=COMPLETE`. This is publication evidence, **not** evidence of working installation or rollback. This metadata-only catalog change does not rebuild, reapprove, republish or mutate the original TAR.

## Backend pilot policy — defaults unchanged

- Catalog sequence advances to `1243` and adds **only** `clientflow-1.3.42-seq-1243`, `status=supported`, `installable=false`, `update_allowed=true`, `install_modes=[in_place_update]`, and `min_current_version=max_current_version=1.3.38`.
- `latest_stable=1.3.38` and `default_install_version=1.3.38` remain unchanged. The previously enabled operational maintenance hold `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` must remain active during transition. An active enrollment token bound to 1.3.38 is not automatically revoked or rebound.
- The already tested `CLIENTFLOW_1243_PILOT_CLIENT_ID` guard remains **disabled by default**. Any later operator enablement requires **exactly** `2`, no 1241/1242 pilot flags, a live-attended Viborg2 baseline of exactly 1.3.38, recorded recovery acknowledgement, a superadmin, and the existing pre-/post-lock checks of release ID, candidate SHA, bundle SHA/size, approval reference and source commit. Heidi1 (ID 1), other devices, unknown source versions, repair, downgrade, implicit latest/fleet rollout and manual rollback are denied.
- Client `client/release/rollback-trust.json` remains keyless and disabled; a stored TAR is not a remote rollback authorization. The historic failed 1.3.41 deployment and anti-rollback evidence must remain intact.
- The Render store temporarily contains five approved bundles (1.3.38–1.3.42). **The permanent retention limit remains three**. Do not prune 1.3.38 or 1.3.39 until fresh-install/recovery dependencies are explicitly resolved, the physical pilot is accepted, and the correct store cleanup is independently approved. GitHub Releases retain historical approved TARs; every restored copy must be SHA-256 checked.

## CI and operations gates

1. Merge only after full GitHub CI, including the exact catalog, pilot-guard, artifact-integrity, source-preflight and SHA256SUMS tests, is green; after Render redeploy require green smoke test.
2. Keep all pilot flags **empty** during the code deploy. Keep `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1`. Check catalog/Render release digest, active deployments, expired/unused enrollment-token binding, and that clients 1 and 2 did not change.
3. **No physical deployment is authorized in this branch.** Separately, physically verify Viborg2's local 1.3.38 active symlink and recovery payload, systemd bridge and services, `activation_intent=None`, updater timer deliberately stopped, and independent recovery acknowledgement. Only after that gate may the narrowly scoped flag `CLIENTFLOW_1243_PILOT_CLIENT_ID=2` be enabled and a single attended update ordered.
4. Require tested kiosk/Wayland, status, calendar, livestream, Remote Desktop and controlled reboot after the pilot; test deliberately injected automatic rollback **only in an isolated recoverable environment**. A failure must stop the pilot and preserve history rather than trigger retries.
5. Only after positive physical acceptance and removal of old fresh-install dependencies, complete a separate catalog/default-install migration and controlled cleanup from five to the exact latest three releases.

No database migrations, Render environment changes, release-artifact deletions or new client update orders are made by this source change.
