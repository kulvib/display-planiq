# 68N-B1 – versioned recovery, closed 1251 / revision 3

Baseline: main 2b6c811abea18aed4235792f45ffdae4bbfe8b7d; 68L physical functional acceptance, 68M-C database rebind and three final frontend checks reported PASS by the operator. Independent failed-update recovery and real off-host restore remain open.

## Deliverable

- Reviewed recovery profile `closed-1251-r3` pins the exact immutable standard catalog, archive inventory, approval, migration head and PostgreSQL 18 image. Preserve old profile entries and pinned inputs when a later release is reviewed; no arbitrary version, DB revision or hash is accepted from a backup.
- Reuse the private 62B stage format, with exact 1248/1250/1251 bytes, SHA/size, strict JSON and private files. Legacy 62B/62D/62E scripts and tests remain historical.
- Explicit operator-only capture on the local Render host, separate private staging device, capacity checks and closed DB/control before and after. No database writes; no claim of cross-store atomicity.
- Local Docker-only isolated restore, pinned preloaded image, no network/ports/production volume, new disposable database and cleanup. Restored migration head, singleton closed release binding and no active deployment must match. This does not start the restored API, reissue credentials, establish a client connection or prove independent recovery.
- No runtime service, cron, migration, release build, new DB, signer or enrollment changes.

## Safe operator sequence (not authorized to execute yet)

1. Choose a separate encrypted destination and responsible custodian. Define retention, recovery key escrow, access controls and a second independent copy. Keep the existing Render persistent disk and three archives. Never upload dumps, credentials or plaintext archives to GitHub, CI, ChatGPT or public links.
2. On the Render host, after approval, inspect the profile with `python scripts/display_recovery_68n.py --inspect-profile`. The capture command is `python scripts/display_recovery_68n.py --capture-to /absolute/private/staging --confirm-private-staging`. This is plaintext temporary staging on a distinct device, NOT encryption or offsite proof. Use an approved private encrypted staging device or approved secure encrypted transfer; do not capture until destination, space and transfer are agreed. Never copy live PGDATA. Avoid concurrent release/deployment operations. A separate verified snapshot/restore is mandatory.
3. Transfer over a secured authenticated channel to the separately controlled encrypted destination. Compare the source and destination stage manifest SHA256 via a separate trusted channel and run `python scripts/display_recovery_68n.py --verify-stage /absolute/private/stage`. Keep source material until receiving-side verification succeeds; clean temporary plaintext according to the agreed handling policy. SHA256 detects corruption against a trusted digest, not a malicious rewrite of both data and manifest.
4. On a separate trusted Docker machine with the pinned image already present, run `python scripts/display_recovery_68n.py --offline-restore /absolute/private/stage`. Never on the live backend; no hosted DB restore. Only sanitized success/stop and elapsed time leave the recovery environment. Validate full API and physical reconnect separately.
5. Record a separately reviewed recovery attestation with timestamp, RPO/RTO measurements, verified data coverage and independent reviewer. A byte proof or synthetic CI is not production acceptance.

## Recovery dependencies not included in the DB dump

Maintain a separate encrypted secret vault/escrow with operator-controlled recovery access. Inventory the actual deployed settings by name only (no value export in this PR): application JWT signing/encryption keys, passkey RP/origin configuration, any data encryption keys, Render account/organization recovery access and domain/DNS controls, deployment configuration and approved artifact provenance. Record exact application source commit and deployment configuration per backup outside the live disk. No private rollback signing key is necessary for the current disabled trust model. PostgreSQL dump intentionally excludes role ownership and ACLs; reproduce the approved local role/socket startup contract, then independently verify permissions and restored API against an isolated environment before cutover. Retain the protected backup and keys separately; never place recovery secrets in the repo or report.

No external storage, encryption software, backup schedule or separate restore host is selected yet. This PR implements the versioned staging and restore core and an operator contract; it does not provision encrypted storage or claim production backup/restore. Do not remove historical backups or run a real capture without separate explicit approval.
