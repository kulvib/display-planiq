# ClientFlow 1.4.0 (1250): permanent standardrelease

Status: development candidate; not an approved or published release. Active catalog, signed artifacts, Viborg1 pilot and existing authorization gates remain unchanged until controlled transition.

## Acceptance scope

- Permanent native Remote Desktop (WSS primary, authenticated HTTPS fallback) and Livestream HLS; physical Ubuntu reboot verification. No 20-minute installation timer; retain 10-minute idle session policy.
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
