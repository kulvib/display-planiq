# PlanIQ Display · Fase 63D-17 · 1248 exact Viborg1 pilot staging

Status: **source-only PR / no physical deployment**. GitHub CI and review must pass; catalog promotion, database authorization, one-shot controller execution and physical acceptance each require separate operator decisions.

## Verified external inputs (21 November 2026)

- Host: Viborg1, hostname `viborg1-NUC14MNK-B2`, backend client ID **3**, Ubuntu 26.04 Wayland.
- User-observed local active symlink: `/opt/clientflow/releases/clientflow-1.3.46-seq-1247`.
- `clientflow-updater.timer` inactive/disabled, update controller inactive, status agent active. Local free disk approximately **419 GB** at the time of the operator inspection. These observations are not automatically refreshed by GitHub.
- Approved 1248 TAR `clientflow-1.3.47-seq-1248`: **223692800 bytes**, SHA-256 `9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff`.
- Source SHA `c0d5a092efe0c4e8638866ad98621481d6f5d0e8`, candidate SHA `f82400140eb49efecf697b099cb86c94cecfb3f29dfe069b4d96ecb3b611173b`, installer SHA `750bb2e09501fb1a1750b8f3eff65975bf383a43a8a0fcc0eb3469389112f7b0`.
- Approval `CF-1.3.47-1248-20261121-c0d5a092-f8240014`, approval Actions run `44898553899`, archive tag `clientflow-1.3.47-1248-approved-transport`.
- Operator's Render postflight: `RELEASE_STORE_POSTFLIGHT=PASS`, `approved_count=4`, `invalid_artifacts=[]`, free **643964928 bytes**. Only temporary storage exception; three-release selector cap remains unchanged. No automatic deletion.
- The installed 1247 controller lacks the signed 63D-13 coordinator fix; do **not** use its ordinary service start or enable the updater timer to install 1248.

## Source changes in this phase

1. Source-pinned immutable 1248 lock, distinct from 1247; anti-rebuild gate rejects a second 1248 build from any new commit.
2. New **non-active** `clientflow_release_catalog_1248_pilot.stage.json`: exactly [1245 stable, 1247 update-only source, 1248 update-only target]. 1246 is removed only from the *future selectable catalog*, not from Render storage. Latest stable/default still `1.3.44`; only one installable version; no rollback/downgrade or fleet.
3. New stage validator pins the **entire SHA-256 of the staged catalog** and verifies exact historical 1245 and 1247 records against the previously approved 1247 stage. Runtime validator/readiness/admin gate can recognize this stage only if separately promoted in a future commit.
4. New `/api/clientflow/release-pilot-1248/authorize` backend route follows the locked, audited 1247 one-shot pattern, bound to ID 3, exact `1.3.46→1.3.47`, fresh cryptographic Status and unique Update identities, superadmin password reauth, `lock_system_client`, locked release policy revision, no previous 1248 order or recovery failure, verified signed Render bytes, exact stage-only active catalog and one DB transaction. **Live catalog remains 1247**, so the new route is currently fail-closed and cannot create a 1248 deployment.
5. `phase63d17_viborg1_readonly_preflight.py` verifies *local* host, identity, symlink, signed 1247 installed state, service gating and disk. It never starts/stops services, reads secrets into output, authorizes a DB deployment or runs an updater. A passing local preflight is not sufficient physical authorization.
6. Existing physical 1245/1246/1247 signed artifacts, runtime, Render environment, DB schema, active catalog, WebRTC/HLS code and user sessions are not modified by this source PR.

## Required next phase before physical execution

1. Merge only after green full CI and independent review. Confirm a green Render deploy and unchanged active catalog 1247; **do not promote 1248 in the same unnoticed deploy**.
2. Independently check Render DB for current client ID 3, fresh Status 1.3.46, unique active Update credential, zero active/stale deployments, no recovery_failed without acknowledgment; inspect policy revision, fleet holds and immutable artifacts.
3. Independently review and PIN the actual **installed signed 1247** update controller/transaction code hashes. Confirm 1247 sealed controller's exact coordination deficiency against the permanent 63D-13 code. This repo cannot guess their physical hashes from the latest main.
4. Only after separate review create the immutable 1248 catalog promotion and an **operator-reviewed systemd credential-bound one-shot execution** derived from the 63D-14 pattern. It must use the original authenticated backend deployment protocol, exact deployment UUID, locked updater coordination and original rollback/health journal handling. No direct `activate_release`, no editable signed runtime, no automatic timer.
5. After physical and backend preflight both pass, authorize exactly one 1247→1248 DB deployment with explicit superadmin reauthentication, then execute via the separately reviewed one-shot controller under its original `LoadCredential` and `INVOCATION_ID`. No retries after ambiguous failure.
6. Verify local `/opt/clientflow/active`, signed manifest, transaction state and cleared `activation_intent`; require terminal backend `succeeded` with matching authenticated status/events. Do not call a partial stage or service start an installation success.
7. Physical acceptance: livestream first `source_buffers > 0`, new `encoded_buffers`/`muxed_buffers`, real manifest + multiple fresh HLS segments and image in browser; Remote Desktop current frames, mouse move/down/up/drag, keyboard, end-to-end median/p95 and WebSocket/HTTPS fallback; restart/reconnect, reboot, memory/CPU, network and DB call counts. A zero-frame observation or no HLS progress is a STOP, not a reason to loosen security or reinstall.
8. Separate explicit retention/dependency review before returning stored artifacts from four to three. Never delete 1245–1247 as part of this pilot.

## Go / no-go

Source CI green is only **source staging**; Render storage PASS is only **artifact storage**; physical read-only preflight PASS is only **host observation**. None alone permits deployment, rollback, catalog promotion or release retention cleanup. All installed clients and service/timer settings remain unchanged at PR merge until the next individually authorized step.
