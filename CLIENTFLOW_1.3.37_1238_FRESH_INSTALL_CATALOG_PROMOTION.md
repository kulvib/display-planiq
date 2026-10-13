# ClientFlow 1.3.37 / sequence 1238 — fresh-install-only catalog promotion

## Exact immutable authority (verified before catalog change)

- Source commit: `93ba1777be84c1d4206fcf9cabd3dc1e3666ec5e` (green exact-source CI).
- Transport: `runtime-inputs-1238-93ba1777be84c1d4206fcf9cabd3dc1e3666ec5e-transport`, platform TAR SHA-256 `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`.
- Release build: GitHub Actions run `38382877226`, two independent byte-identical outputs plus Ubuntu 26.04 executable gate and provenance attestation.
- Unapproved candidate SHA-256: `495dd2813c9575c2b5e4cb6c2cb21b721fdcd4c5f2465e5ce7ed9f434b8d1241`.
- Embedded fresh-installer SHA-256: `e68c2702a047a01549bca29b4305c808b450f68fe9bcc6d2e5a0777d99bad655`.
- Explicit approval: GitHub Actions run `38383617898` (#25), immutable reference: `clientflow-1.3.37-seq-1238/93ba1777be84c1d4206fcf9cabd3dc1e3666ec5e/495dd2813c9575c2b5e4cb6c2cb21b721fdcd4c5f2465e5ce7ed9f434b8d1241`.
- GitHub approved-transport prerelease: `clientflow-1.3.37-1238-approved-transport`, artifact `clientflow-approved-1.3.37-1238.tar`.
- Approved immutable bundle SHA-256: `911d59c45159fe41b85c96366c1d0bd84762cb81a042519d2b177da86339adfe`; size **223498240 bytes**.
- Render published object: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.37-seq-1238.tar`.
- Render publication output: `RELEASE_STORE_POSTFLIGHT=PASS`; subsequent operator read-only independent re-read: `RELEASE_STORE_INDEPENDENT_AUDIT=PASS`, both this bundle and `clientflow-1.3.36-seq-1237.tar` independently SHA-256 verified. At audit time, **532 MB** were available and neither release had been deleted.

The bundle is never rebuilt, altered or re-approved by this catalog promotion. Approved source and content identity are authenticated by the immutable stored artifact; the catalog remains a policy selector, not a second source of cryptographic authority.

## Canonical fresh-install-only policy

- `catalog_sequence=1238`; `latest_stable=default_install_version=1.3.37`.
- Exactly one selectable release: `clientflow-1.3.37-seq-1238`; `install_modes=["fresh_install"]`, `max_installable_versions=1`.
- `update_allowed=false` and `rollback_allowed=false`; no automatic update from 1.3.36 to 1.3.37 and no rollback.
- Ubuntu Desktop 26.04 LTS/amd64, GNOME/Wayland; platform preflight and controlled reboot required; embedded Python 3.13.14.
- Historical release approvals, sources and GitHub prereleases are retained. Old catalog records are not selectable; the old Render bundle remains intact. Never delete store artifacts as part of a catalog promotion.

## Physical acceptance is **PENDING**

The previous 1.3.36 USB installation and post-final reboot acceptance were physically tested on Viborg4. Changes introduced after it—including ClientFlow GUI copy buttons, vector branding and kiosk-minimize protection—have not been physically validated in an authorized 1.3.37 installation. Successful CI, release approval, immutable storage and frontend smoke tests do **not** imply physical acceptance of ClientFlow 1.3.37. Do not claim the version physically approved before a new clean USB/operator flow and post-final reboot evidence.

## Production deployment gate

1. Merge the catalog change only after GitHub CI is green for the exact new merge SHA.
2. Deploy the new backend to Render and run production smoke; frontend desktop must remain unchanged.
3. Independently verify the catalog selects only 1.3.37/1238 for fresh install, update and rollback remain disabled, and the immutable Render file remains SHA-256 `911d59c45159fe41b85c96366c1d0bd84762cb81a042519d2b177da86339adfe` with size 223498240 bytes and the exact approval reference above.
4. Check outstanding in-progress or pending clients bound to prior releases before any optional, separately approved storage cleanup. Do not delete existing 1.3.36 bytes during this promotion.
5. Perform a new authorized fresh installation on a prepared test host. Validate GUI copy behavior, visible SVG branding, kiosk window protection, quick-settings guard, Chrome fullscreen and final reboot acceptance. In-place update from 1.3.36 is **not** authorized or implied by this work.

No automatic update, no rollback, no release artifact deletion, and no additional paid infrastructure are authorized by this change.
