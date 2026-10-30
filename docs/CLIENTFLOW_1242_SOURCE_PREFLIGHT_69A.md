# ClientFlow 1.3.41 / seq 1242 – read-only source-stage preflight (69A)

The 69A change combines two narrowly scoped frontend corrections with preparation for the fail-closed 1242 manual rollback safety-mode gate. It does not publish, sign, activate, install or stage a release.

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

Exit 2 is **expected** on the current baseline. The JSON output lists three gates: exact release version, exact sequence and validated manual rollback safety mode. The source may explicitly disable manual rollback (`enabled=false`, `keys=[]`); this mode still refuses any unsigned manual rollback at runtime for sequence 1242+. Alternatively an independently approved signed mode may use pinned Ed25519 public keys. Both choices use the *same validator as the release builder*. The check never reads or prints the private signer key or release tokens, writes no files, and never turns itself into a publication or activation approval. A successful exit 0 means only the **source inputs** meet these static checks.

## Required separate approvals before 1242 staging and publication

1. Preserve the existing keyless GitHub release workflow. The approved default for 1.3.41 is **manual rollback disabled** with no signing key, and existing central minimum-safe/revocation policy unchanged. Do not add backend secrets or enable a signer.
2. Signed manual rollback is a **separate optional later project** that requires a trusted signer, reviewed key ID, policy, security tests and physical pilot. The ordinary release never requires a private key.
3. Prepare a **new** exact 1.3.41/1242 immutable source stage, rerun preflight, and pass all builder/Ubuntu/client-runtime/CI gates. Do not change the existing 1.3.40/1241 frozen bundle or its trust semantics.
4. Keep the stable catalog unchanged until a separate publication authorization. Ensure retained, approved rollback targets, durable outbox exporter and genuine installed-release state are verified.
5. Pilot with physical backup access (not the remote-only Heidi1 session). Verify first HLS segment and actual video, Remote Desktop WebSocket-to-HTTPS behavior, explicit rejection of manual rollback from 1242 and automatic failed-activation recovery, kiosk internet gate, and cold-reboot/offline behavior. Nothing here asserts those features are now physically accepted.

The frontend label `Brugeradministration` preserves the existing `section=access` deep link and the same backend authorizations; the refresh action still executes the existing `loadData` call, with Audit-log-consistent header placement.
