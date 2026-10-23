# ClientFlow signed manual rollback — staged implementation and operations

## Status and critical safety boundary

**Source implementation only. NOT approved for deployment, key provisioning, or release publication.**

The server-issued one-use manual rollback permit is bound to a single client's update identity, one source and one immediately previous target release, source and target sequence, target immutable bundle SHA-256, canonical release approval, an operator's reason hash, a signed security-floor revision, and a five-minute validity window. Only an Ed25519 public key **embedded in the immutable already-active SOURCE release** can verify it. No public key or private key is accepted from a user-supplied permit or request. Both signature and all bindings are checked before changing runtime or symlinks.

New API endpoints:
- `POST /api/clients/{client_id}/clientflow-rollback-permits`: authenticated, non-impersonated superadmin, re-enter password, evidence of verified client releases, policy check and durable `issued` record.
- `POST /api/clientflow-rollback-permits/{permit_id}/revoke`: superadmin revocation/audit.
- `POST /api/clientflow-update/rollback-permits/{permit_id}/events`: existing update-credential DPoP and authenticated canonical Status prerequisite for `succeeded`. The backend does **not** claim a successful physical rollback until this report.

**Release-build preflight:** Beginning with release sequence 1242, the canonical
candidate builder refuses to package a release unless its checked-in
`client/release/rollback-trust.json` is enabled, has 1–3 correctly pinned Ed25519
public keys, and pins security floors no lower than the repository's current
backend release-security policy. This is a build-time fail-closed check; it
does **not** provision the signer, prove access to its private key, enable the
feature in Render, or establish automatic rollback-result reporting. A newly
approved signed-release pilot must separately verify the deployed signing
key ID against the immutable bundle before permitting actual rollback.

The backend feature is **OFF** by default. Never set `CLIENTFLOW_SIGNED_ROLLBACK_ENABLED=true` or configure signing key in production until a newly built and accepted ClientFlow source release with a matching pinned public key is installed. The checked-in `client/release/rollback-trust.json` is **disabled with no keys**. Existing installed 1.3.40 and earlier immutable bundles remain unchanged and follow their existing *local* manual rollback contract. For new source releases with sequence 1242 or higher, missing or disabled rollback-trust is a blocking error: no fallback to unsigned root rollback is permitted. No central policy can retroactively make those older local binaries verify signed permits.

The local root command for a future trust-enabled release uses `clientflow-release-transaction rollback --release-id ... --expected-release-approval-reference ... --reason ... --permit-file /root/<root-only-permit>.json`. The permit file must be a regular, root-owned, mode 0600 file, and the signing key cannot be overridden on the command line. Operator must verify release, SHA, reason and expiry before triggering rollback.

An explicit later reporting command `clientflow-release-transaction report-rollback --permit-id <id>` reports a completed rollback through the update credential and DPoP. **Reporting is not automatic yet.** An interrupted connection leaves the backend record pending; only an authorized retry can reconcile it. Never edit the database to fabricate success.

Offline safety: a pre-issued permit may be used while disconnected **only during its short validity** and with verified host NTP synchronization. Expired/invalid tokens fail closed for new rollback attempts. A previously durable activation intent for the *same* signed permit can resume after expiry; this cannot create a new authorization. Backend revocation cannot instantly reach offline clients: the maximum remaining permit lifetime is bounded to five minutes. For a new release with signed-rollback trust enabled, no permit means no manual root rollback; automatic failed-activation recovery retains its separately audited path.

## Future enablement sequence — requires separate explicit approvals

1. Run full GitHub CI including tests, PostgreSQL migrations and exact schema fingerprint. The code in this branch is never a reason to skip any CI gate.
2. Conduct threat review of offline grace, permission expiry, admin reauthentication, replay durability, crash recovery, key rotation and revocation race.
3. Generate a **separate** Ed25519 signing key in an approved secure vault. Never place its private material in GitHub or release bundles. Review and pin its public key and policy minimum in `rollback-trust.json` for a *new* immutable ClientFlow release; approve, hash and publish through canonical release workflow.
4. Pilot on a dedicated, freshly installed test client that supports signed rollback verification (source seq >=1242); do not make Heidi1 1.3.40 a signing pilot without an explicitly approved release upgrade.
5. Only after physical acceptance, configure the backend feature flag and key securely, with operational ability to disable issuing new permits. Verify the key ID against the embedded client public key.
6. Validate issuance, revocation, signer rotation, offline clock, expired permit, client mismatch, incorrect target SHA, wrong reason, signature tampering, replay, power loss before/after activation intent, and report after reconnect.
7. Decide whether to make reporting automatic through a separately tested journaled worker before fleet rollout. Manual reporting is the only implemented reporting mechanism in this source phase.

## Residual limitations and explicit gates

- **This is an implementation candidate, not production acceptance.** No hosted PostgreSQL/SQLModel integration or Render deployment has been exercised here. Full migrations and HTTP gates are mandatory.
- Issuance depends on retained, backend-verifiable release provenance and catalog entries; if either was pruned, it intentionally fails closed.
- Already installed older bundles do not retroactively enforce central rollback revocation.
- Backend can revoke an *unconsumed* permit online, but cannot retract one already in use on an offline host within its validity window.
- No automatic authenticated result reporter exists yet. An outstanding event is not treated as success.
