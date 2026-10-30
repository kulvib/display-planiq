# ClientFlow 1.3.41 / 1242 — source-stage 72A

**STAGED SOURCE IDENTITY ONLY — NOT approved, NOT published, NOT catalog-promoted, NOT installed.**

The canonical source version is now `client/VERSION=1.3.41` with release-input sequence `1242` on Ubuntu 26.04/amd64, using the existing locked Python 3.13.14 and canonical GitHub CI/reproducible-build/approval workflows. The immutable 1.3.40/1241 artifacts and their approval/source SHA are *not* modified. This commit is not a release candidate artifact or a publication authorization; a new exact 40-character source SHA is assigned only after the branch merges to GitHub main and CI passes on that exact commit.

## No premature release access

The backend production catalog remains **unchanged** with `catalog_sequence=1241`, `latest_stable=default_install_version=1.3.38`, and two existing records: published fresh-install-only 1.3.38/1239 and the explicitly scoped existing 1.3.40/1241 pilot. There is **no** 1.3.41/1242 catalog record. The 1242 source sequence is exactly one greater than the current catalog sequence because it is only staged source; catalog promotion, new deployment permissions, default fresh-install target changes and fleet rollout are all forbidden until a separate explicit publication and pilot decision. Existing `CLIENTFLOW_1241_PILOT_CLIENT_ID` authorization cannot authorize 1242.

The existing centralized release policy stays at revision 1 and minimum safe sequence 1239; the revocation list is unchanged. `client/release/rollback-trust.json` remains exactly `{ "schema_version": 1, "enabled": false, "keys": [] }`: source 1242 has **manual rollback disabled**, including unsigned root/permit fallback, but the independent automatic failed-activation recovery mechanism remains in place. No Ed25519 private key, new Render secret or changed backend signer is required for ordinary GitHub releases. Earlier installed 1.3.40/1241 remains unchanged.

## Proof and next gates

Before any release approval, publication, catalog promotion or activation:

1. Run `python3 -I scripts/clientflow_1242_source_preflight.py` on merged canonical source; `source_stage_ready=true` means static source preparation **only** and `publish_authorized=false`, `activation_authorized=false` must remain false.
2. Require exact-source GitHub CI (backend/frontend/migrations and Ubuntu 26.04 client-host executable proof), complete integrity manifest, locked runtime inputs, independent reproducible byte-identical builds and fresh installer verification. Keep the normal manual GitHub approval of exact source SHA, candidate SHA-256, installer SHA-256 and immutable artifact size.
3. For any later publication, audit immutable Render store/retention and postflight with exact bytes and provenance; only then prepare a separately approved catalog promotion. A successful source-stage CI alone grants **no** deployment, fresh-install, rollback or rollout authority.
4. Perform physical pilot on a spare Ubuntu 26.04 client with local recovery access, **not remote-only Heidi1**: verified networking gate (Ethernet/WiFi), Chrome/Wayland GUI, local/remote status, actual first HLS segment and playable Livestream, Remote Desktop authentication and WebSocket/HTTPS fallback, systemd stable rollback report exporter, explicit denial of manual rollback from 1242, automatic failed-activation recovery, cold reboot, offline status, calendar, Control Room and Clientlist. Existing source-level Livestream counters are not a physical fix; do not claim those two outstanding streaming issues resolved without buffer and video evidence.
5. Do not weaken tests, authentication, backend security, minimum-safe policy, client trust, or transaction/rollback protection. **Do not auto-activate** 1.3.41; no new 1242 release has been built or published in this source-stage.
