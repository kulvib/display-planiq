# ClientFlow 1.3.38 / sequence 1239 — fresh-install-only catalog promotion

## Verified immutable release authority (before catalog change)

- Exact source commit: `abbd8d673a350b6beca5d9e58ddb02fa2edd1c08`; canonical GitHub CI successful on this commit.
- Runtime-input transport: `runtime-inputs-1239-abbd8d673a350b6beca5d9e58ddb02fa2edd1c08-transport`, SHA-256 `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`.
- Independent reproducible build: GitHub Actions run [38744376052](https://github.com/kulvib/display-planiq/actions/runs/38744376052), with two byte-identical builds, Ubuntu 26.04 executable/install checks and GitHub provenance attestation.
- Candidate bundle SHA-256: `d4d091c2865437582ce5ad7c0edb437ca37626bd75fd02b17f64442e8b0e5f86`.
- Embedded installer SHA-256: `2ee4ad5fb87d3ba420742c74e2956f816258e9991b95865dd67c3400c6642f75`.
- Explicit Ubuntu 26.04 approval: [GitHub Actions run 38746557492](https://github.com/kulvib/display-planiq/actions/runs/38746557492).
- Immutable approval reference: `clientflow-1.3.38-seq-1239/abbd8d673a350b6beca5d9e58ddb02fa2edd1c08/d4d091c2865437582ce5ad7c0edb437ca37626bd75fd02b17f64442e8b0e5f86`.
- Approved GitHub transport pre-release tag: `clientflow-1.3.38-1239-approved-transport`; artifact: `clientflow-approved-1.3.38-1239.tar`.
- Approved bundle SHA-256: `02c3d4261eabdac4b9967a3aad4419453f61ca483ef4eb34dacf284d3af16a11`; size **223498240 bytes**.
- Render approved store object: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.38-seq-1239.tar`.
- Render operator output verified exact source, TAR size, SHA-256 and the canonical publication gate: `RELEASE_STORE_POSTFLIGHT=PASS`, `IMMUTABLE_STORE=PASS`, `CLIENTFLOW_1_3_38_PUBLICATION=COMPLETE`. The independent re-read matched the exact approved bytes. The publication audit retained 1.3.37/1238 and 1.3.36/1237; `RELEASE_AUTOMATIC_DELETION=NO`, `RELEASE_ROLLBACK_ENABLED=NO`.

Publication evidence is recorded from the operator's Render Shell transcript on 2026-10-15. The catalog policy is not an independent authority for the bundle's cryptographic identity. The immutable approved bytes must never be replaced or rebuilt for this promotion.

## Fresh-install-only catalog selection

- `catalog_sequence=1239`, `latest_stable=default_install_version=1.3.38`.
- Exactly one selected catalog release: `clientflow-1.3.38-seq-1239`.
- `retention_policy.max_installable_versions=1`; `install_modes=["fresh_install"]`.
- `update_allowed=false`, `rollback_allowed=false`, no `min_current_version`; **No in-place update** or downgrade from any existing client installation is authorized.
- Ubuntu Desktop 26.04 LTS / amd64 / GNOME Wayland with platform preflight, controlled reboot, and embedded Python 3.13.14.
- The prior 1.3.37/1238 catalog selector is removed from current selection; its immutable approved bundle and historical approvals remain untouched. This promotion never deletes older binaries.

## Physical acceptance remains pending

The new GUI copy behavior, context-aware copy icons, kiosk mouse-cursor auto-hide, calendar ON-boundary reboot throttling, post-boot browser restoration and Control Room reboot-indicator states still require physical validation on an authorized **fresh-installed** Ubuntu 26.04 client. A green CI run, backend/frontend smoke test, Ubuntu executable gate, or immutable publication **does not constitute physical acceptance**. The existing Viborg1 1.3.37 installation must remain unchanged because no in-place update path has been authorized.

## Deployment and acceptance gate

1. Apply this separate catalog promotion through a reviewed GitHub branch. Require green CI for the merged `main` SHA.
2. Redeploy the backend with the promoted catalog and require production smoke PASS. No additional Render/Neon capacity, schema migration, or frontend UI changes are required by this selector update.
3. Reverify the runtime catalog selects only 1.3.38/1239 for fresh install; update and rollback remain blocked; re-read the approved Render TAR and match the exact SHA-256/size above.
4. Do not delete 1.3.37/1238 or 1.3.36/1237 binaries, and audit any still-in-progress clients before considering retention changes.
5. Carry out the standard USB/01/02/approval/post-final-reboot acceptance on a separately authorized clean test host. Test the real GTK4 clipboard, copy icon visibility, Wayland cursor hiding, calendar-driven vs manual wake, boot-ID proof, kiosk/browser recovery, lockdown, livestream, remote desktop, terminal, power countdown and display wake.
6. If physical acceptance fails, record that failure. Repair requires a new exact source/build/release identity; do not mutate this approved package, weaken checks or authorize an in-place update.

No automatic update, no rollback and no storage deletion are authorized by this promotion.
