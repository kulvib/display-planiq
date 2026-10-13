# ClientFlow 1.3.36 / sequence 1237 — fresh-install-only catalog promotion

## Verified immutable release authority

- Exact source commit: `fb5daee53457e2f2145f42404f3595fd1df02627` (GitHub CI green)
- Runtime transport: `runtime-inputs-1237-fb5daee53457e2f2145f42404f3595fd1df02627-transport`; SHA-256 `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- Independent candidate builds: GitHub Actions release-build run `38355732875`, two byte-identical builds; Ubuntu 26.04 executable candidate gate successful
- Unapproved candidate SHA-256: `7b7d7bae6e796bd0887bc132bfc234273daf73fd6cb784b5cf98d6f98214b219`
- Embedded fresh installer SHA-256: `4dbf1b7149f5c3426a4de8a6e302f41e1d8261470bfb1c50badd046ff9e0f33f`
- Explicit approval: GitHub Actions run `38356768448`, approval reference: `clientflow-1.3.36-seq-1237/fb5daee53457e2f2145f42404f3595fd1df02627/7b7d7bae6e796bd0887bc132bfc234273daf73fd6cb784b5cf98d6f98214b219`
- GitHub approved-transport prerelease: `clientflow-1.3.36-1237-approved-transport`, asset `clientflow-approved.tar`
- Approved immutable bundle: **223498240 bytes**; SHA-256 `3d44274f79d0df899963edef4c93ada153f31d77d62692dbf3bb6a1c9799c856`
- Render published object: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.36-seq-1237.tar`
- Independent Render reread result: `RELEASE_STORE_POSTFLIGHT=PASS`; subsequent read-only audit: `RELEASE_STORE_AUDIT=PASS`; four valid bundles remained with 108515328 bytes free (operator evidence)

The already-approved bundle is not rebuilt or modified by this catalog promotion. Cryptographic provenance remains in the verified immutable artifact, not duplicated as ad-hoc catalog authority.

## Canonical fresh-install-only policy

- `catalog_sequence=1237`, `latest_stable=default_install_version=1.3.36`.
- Exactly one catalog entry: `clientflow-1.3.36-seq-1237`, `install_modes=["fresh_install"]`.
- `update_allowed=false`, `rollback_allowed=false`, `max_installable_versions=1`.
- No automatic 1.3.35 → 1.3.36 update, and no rollback authorization.
- Ubuntu Desktop 26.04 LTS amd64, GNOME/Wayland, platform preflight and controlled reboot required.
- Embedded runtime Python remains 3.13.14; legacy catalog releases are removed from installation selection but their historical source evidence remains.

## Important: physical acceptance is PENDING

The earlier 1.3.35 physical test on Viborg2 did **not** pass quick-settings guard or Chrome post-final-reboot acceptance. The fixes in 1.3.36 passed automated reproducible/Ubuntu 26.04 gates, **not** physical approval. A clean, authorized fresh installation and physical verification are required. Do not report 1.3.36 as physically accepted based on catalog promotion or a successful deployment alone.

## Production deployment gate

1. Merge this catalog promotion only after new GitHub CI is green for its exact source commit.
2. Deploy the new backend commit to Render; require successful production smoke before new installations.
3. Reconfirm catalog 1237 is the sole fresh-install target and that the exact immutable Render bundle matches `3d44274f79d0df899963edef4c93ada153f31d77d62692dbf3bb6a1c9799c856`, **223498240 bytes**, source `fb5daee53457e2f2145f42404f3595fd1df02627`, and approval `clientflow-1.3.36-seq-1237/fb5daee53457e2f2145f42404f3595fd1df02627/7b7d7bae6e796bd0887bc132bfc234273daf73fd6cb784b5cf98d6f98214b219`.
4. Check for outstanding pending/manual-approval or in-progress fresh installations against earlier release IDs before retiring older storage objects. Keep historical GitHub releases; never delete current installer dependencies.
5. A validated reinstallation of Viborg2 requires a fresh host; do not simulate an in-place upgrade from 1.3.35. Test quick-settings guard, canonical Chrome acceptance and post-final-reboot status first.

Any deletion of old Render artifacts is a separate explicit, one-time operator action; it is **not** performed by this promotion. Three-release retention configuration and rollback authority remain unchanged.
