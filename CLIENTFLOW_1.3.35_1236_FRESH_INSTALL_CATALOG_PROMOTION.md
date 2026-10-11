# ClientFlow 1.3.35 / sequence 1236 — fresh-install-only catalog promotion

## Release authority (already verified before this source change)

- Source commit: `78878ee0b5cfc26bc07c519efe0a909e7443c9c3` (CI and production smoke green)
- Runtime-input transport: GitHub pre-release `runtime-inputs-1236-78878ee0b5cfc26bc07c519efe0a909e7443c9c3-transport`, SHA-256 `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- Independent candidate builds: reproducible and byte-identical; Ubuntu 26.04 executable candidate gate green
- Candidate SHA-256: `1a0b0b75be174cb33f752bf72435dfe84b41509c6bb80d63b689fa4d1a1841df`
- Installer SHA-256: `9f1c731cff07f8da13c6cc4af723c15c56f359ddbc644afe937fa2f46bc14df7`
- Explicit GitHub approval run: `38155658923`
- Approval reference: `clientflow-1.3.35-seq-1236/78878ee0b5cfc26bc07c519efe0a909e7443c9c3/1a0b0b75be174cb33f752bf72435dfe84b41509c6bb80d63b689fa4d1a1841df`
- Transport pre-release: `clientflow-1.3.35-1236-approved-transport`, asset `clientflow-approved.tar`
- Approved artifact: **223498240 bytes**; SHA-256 `94abdce02578a09d067397e7a2d9a9d86a0c20e696eb734a79ade8a483c713d4`
- Immutable Render artifact: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.35-seq-1236.tar`
- Independent Render re-read: `IMMUTABLE_STORE_REREAD_VERIFIED=PASS`, 317 MB available after publication (operator report).

The approved release is not rebuilt or modified by catalog promotion. The selector deliberately does not duplicate cryptographic metadata, which is verified against the immutable server-side artifact at resolution/download time.

## Canonical fresh-install policy

- `catalog_sequence = 1236`, `latest_stable = default_install_version = 1.3.35`
- Only `clientflow-1.3.35-seq-1236` retained as selectable release
- `install_modes = ["fresh_install"]`, `update_allowed = false`, `rollback_allowed = false`
- No automatic 1.3.34 → 1.3.35 in-place update and no rollback authority
- Ubuntu Desktop 26.04 LTS, amd64, GNOME/Wayland, platform preflight and reboot mandatory
- Embedded Python 3.13.14 unchanged
- Historical 1.3.34 catalog/evidence files remain untouched

## Important limitation: physical acceptance is PENDING

The source remedies quick-settings-guard privilege switching and strict Chrome executable acceptance but neither CI nor reproducible-build tests establish physical acceptance. Ringkøbing1 is still on 1.3.34, with an observed `quick-guard` drift; do **not** assert that device is fixed. Verify new 1.3.35 through canonical fresh Ubuntu 26.04 installation with post-reboot handoff, Chrome, kiosk guard, Wayland, kiosk user separation, GNOME lockdown, agent status and 10-second display contracts.

## Publication gate

1. Merge the catalog-only promotion and require green GitHub CI on the **new promotion commit**.
2. Let backend Render deploy the new commit, then run production smoke; frontend deployment is only needed if configured automatically.
3. Read the live catalog with the backend resolver and verify the selected 1.3.35 artifact's *release ID, exact SHA-256, byte count, approval reference and source commit* against immutable Render store. No changes to Neon are needed.
4. Manufacture one canonical fresh installer and complete physical acceptance before marking client security or 24/7 readiness as verified.
