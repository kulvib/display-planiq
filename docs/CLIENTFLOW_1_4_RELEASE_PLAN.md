# ClientFlow 1.4.0 (1250): permanent standardrelease

Status: development candidate; not an approved or published release. Active catalog, signed artifacts, Viborg1 pilot and existing authorization gates remain unchanged until controlled transition.

## Acceptance scope

- Permanent native Remote Desktop (WSS primary, authenticated HTTPS fallback) and Livestream HLS; physical Ubuntu reboot verification. No 20-minute installation timer; retain 10-minute idle session policy.
- Native RDP admission foundation: canonical root entrypoint requires root-owned identity, committed installed release, matching manifest/ready provenance and no active installation. Explicit superadmin release-eligibility inspection uses signed standard catalog, physical acceptance, canonical Status and exact completed deployment/enrollment evidence. This does not open fleet transport. Historical pinned pilot helpers and Viborg1 transport scope remain unchanged until generic lifecycle, proof, agent and browser integration is verified.
- Post-boot recovery for subsequent compatible releases: bind the failed boot and original deployment to the retained installation lock; restore only the locally verified predecessor; report rollback only after its health commit. A failed or uncertain restoration retains the lock and recovery notice. The first legacy-to-1250 transition still needs separate physical acceptance.
- Generation-bound HLS storage and manifest references; test resolution switches, visible/hidden tabs, concurrent RD/stream, bounded media retention and 100-client resource budgets.
- Release administration: one standard release, automatic authoritative status, bulk/single client control, signed and authorized rollback, automatic audit text for ordinary updates, explicit reason for rollback.
- Control Room and local GUI: shared update status for ClientFlow, Ubuntu and firmware, real update availability/freshness, cross-plane serialization, verified maintenance/reboot/recovery.
- Admin review of Organisation, Brugeradministration, Audit-log, Driftsfejl, Installation, ClientFlow Releases, Livestreams and Vedligeholdelse. Keep established working layout; align controls and status semantics.
- Documentation consolidation and dependency-reviewed file cleanup.

## Publication order

1. Complete code and test acceptance before building 1250.
2. Build and approve immutable signed package. Keep 1248 available during transition and verify storage capacity.
3. Retire only known temporary test layers on Viborg1 through verified preparation; do not execute pilot helpers from the ordinary updater.
4. Use authorized deployment and verify post-boot health, Remote Desktop, Livestream, update controls and local GUI. CI is not physical proof.
5. Promote 1.4.0 as sole stable/default release. Remove older selectable versions and packages only after verifying no client, pending deployment, or recovery dependency needs them. Preserve audit metadata, signatures and Git history.
6. Establish one current standard centrally; future local rollback may retain the immediately previous approved version, subject to security and explicit operator approval. At the 1.4.0 baseline retire 1.3 packages only after physical acceptance and dependency audit.

A deleted package cannot be selected as a rollback target. Never bypass signature, revoked-version, compatibility, authorization, maintenance or recovery gates.

- Canonical privileged GNOME helper sources are independently pinned under `client/native-rdp-root/`; historical `scripts/` are not modified or repackaged. The installed identity is rechecked in lifecycle, proof, renewal, and credential sealing. Client ID is authenticated as AES-GCM additional data in the browser. The agent and server fleet gate remain closed pending their coordinated integration and physical acceptance.

- Native RDP fleet integration: authenticated managed requests and existing periodic tunnel checks consume canonical release evidence; the read-only UI capability never issues a grant. Positive transport admission expires after 30 seconds, with refresh at bounded authentication checkpoints. The artifact verification cache is keyed to published file identity, not merely version. The legacy physical pilot remains a compatibility exception until cutover and its final retirement. Frontend native mode and automatic login no longer depend on individual pilot build flags. Global HTTPS selection remains unchanged for physical transport validation.

- Administration source review: all eight admin sections retain the shared refresh button. Release status remains event-driven; Control Room observes the same release wake channel with visible-only bounded reconciliation and abortable client-scoped reads. Livestream inventory refreshes upon returning to the tab, keeps existing generation-aware playback/latency UI, and cancels outstanding inventory reads on exit. Operational incidents distinguish failed reads from empty results. Maintenance read failure invalidates the displayed authority and blocks further mutations until refreshed. Visual/physical acceptance and final pre-publication audit remain required.

- Pre-publication RDP safety review: watchdog shutdown uses independently verified root-owned recovery state with the original kiosk UID, not current enrollment. Identity loss/change and malformed deadlines trigger shutdown, never new admission. Orphaned root grants and proofs are removed only when bound to the stopped session, before removing the independent network guard. Unknown ownership retains protection. The physical recovery boundary still requires Viborg1 acceptance.

- Native RDP central admission: the previous ID-only transport exception is removed. Every identity uses the same bounded, fail-closed authorization cache. Legacy 1248 compatibility requires fresh canonical Status, approved client/credential, the exact closed historical policy and the existing physical test host; it cannot authorize an unmanaged 1250 session. Before fleet cutover, the exact approved 1250 artifact and completed deployment evidence allow managed physical testing only on Viborg1 without circular physical-acceptance dependency. After cutover, Viborg1 follows the same standard policy as all other clients. No fleet/fresh-install hold is opened by this code. Capacity tests cover 128 admissions and 20,000 pure transport checks across 100 clients; real network/Render load remains to be measured.

- HLS retention and resource boundary: retain the current and incoming playlist references plus a 30-second recent-media grace window; prune only known older media under the existing client row lock. Reject missing manifest dependencies and cap each client at 96 recognized media/playlist files and 128 MiB. Keep a 256 MiB filesystem free-space reserve. Eight concurrent uploads and a 64 MiB combined reserved request-body budget are bounded per single ASGI worker (transient serialization copies can add memory). The producer keeps the current and one previous local generation. These are conservative safety ceilings for the reviewed 1-second/12 Mbps default, not evidence that every maximum custom capture setting or 100 simultaneous streams fits the Render service. HLS remains canonical; optional WSS video pilot stays closed by default. The release builder already verifies exact Livestream wheel sources and immutable native RDP pins; physical validation must measure actual latency, concurrent RD/HLS and reboot recovery.

## Immutable approved 1250 handoff (2026-11-26)

- Source: `6d7e16c4cf6857c50cdd6d88899ef988e2e739a5`; reproducible build #56/run 45866882082; approval #37/run 45867523387; archive #8/run 45867793737.
- Approved archive: `clientflow-1.4.0-1250-approved-transport`; TAR SHA-256 `cf4a3077975b9740ef7d1e34a58731a83f2f4b1e43f4ab0f2fad54772e35b446`; size 223897600 bytes; reference `ClientFlow-1.4.0-1250-PR428-build56`.
- Separate source-reviewed metadata pin `fc851982c39de0b7f92b9274f822b70bf61ca014bcbd88e62d7570a08d58f334` enables only the pre-cutover pilot policy when all existing gates and exact Render artifact verification pass. Catalog, fleet/fresh-install holds and rollback policy are unchanged. This is not a new client build or physical acceptance.
- Inspect actual Render store count, verified artifact identities and free space before publication. Keep the existing three-release cap and 64 MiB free-space reserve. If publication would exceed the cap, stop for a separate dependency-reviewed storage decision; never delete active or recovery dependencies to make space. Do not rebuild 1250 from the follow-up policy commit.

### Audited temporary storage transition

The operator's 2026-11-26 read-only Render store audit confirmed exact approved 1245/1246/1247/1248 bytes, zero invalid artifacts and 640745472 available bytes on the shared 2077073408-byte filesystem. The approved 1250 bundle requires 223897600 bytes plus the existing 64 MiB free-space reserve. Use the explicit `--authorize-1250-baseline-storage-only` publisher flag only for this exact four-to-five inventory (or identical five-file retry). The normal three-release cap remains unchanged. This temporary storage-only exception does not open any runtime admission, delete artifacts, or change the catalog. After physical acceptance and dependency verification, reconcile to the single new 1250 baseline; retain required local recovery bytes and immutable historical metadata. Future automatic retirement requires a separate reviewed implementation and acceptance, not this flag.
