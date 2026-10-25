# ClientFlow 1.3.41 / seq 1242 – read-only source-stage preflight (69A)

The 69A change combines two narrowly scoped frontend corrections with preparation for the **existing** fail-closed 1242 Ed25519 rollback trust gate. It does not publish, sign, activate, install or stage a release.

## Current baseline

- The current immutable release input remains `client/VERSION=1.3.40` and `release_sequence=1241`.
- `client/release/rollback-trust.json` currently has `enabled=false` and no pinned public keys.
- The central policy revision and minimum-safe sequence are defined by `backend/service1/clientflow_release_security_policy.json`. This document does not grant approval to alter them.
- The production `latest_stable` catalog must **not** be advanced as a side effect of source-stage preparation.

## Read-only source preflight

Run from the repository root:

```bash
python3 -I scripts/clientflow_1242_source_preflight.py
```

Exit 2 is **expected** on the current baseline. The JSON output lists three gates: exact release version, exact sequence and pinned Ed25519 **public** trust validated by the *same validator used in the release builder*. The check never reads or prints the private signer key or release tokens, writes no files, and never turns itself into a publication or activation approval. A successful exit 0 means only the **source inputs** meet these static checks.

## Required separate approvals before 1242 staging and publication

1. Approve the rollback issuer identity and central minimum-safe/revocation policy separately. Generate and safeguard the *private* Ed25519 key outside this repository, ZIPs, logs and frontend. Provision secrets only to the intended backend secret facility; do not copy the private key into ClientFlow or GitHub.
2. Verify that the public key pinned in the immutable trust file corresponds to the approved signer, including its canonical key ID and policy floors. The script cannot verify a backend secret it deliberately never accesses.
3. Prepare a **new** exact 1.3.41/1242 immutable source stage, rerun preflight, and pass all builder/Ubuntu/client-runtime/CI gates. Do not change the existing 1.3.40/1241 frozen bundle or its trust semantics.
4. Keep the stable catalog unchanged until a separate publication authorization. Ensure retained, approved rollback targets, durable outbox exporter and genuine installed-release state are verified.
5. Pilot with physical backup access (not the remote-only Heidi1 session). Verify first HLS segment and actual video, Remote Desktop WebSocket-to-HTTPS behavior, signed rollback/recovery, kiosk internet gate, and cold-reboot/offline behavior. Nothing here asserts those features are now physically accepted.

The frontend label `Brugeradministration` preserves the existing `section=access` deep link and the same backend authorizations; the refresh action still executes the existing `loadData` call, with Audit-log-consistent header placement.
