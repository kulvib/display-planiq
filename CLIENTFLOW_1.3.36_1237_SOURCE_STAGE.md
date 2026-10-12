# ClientFlow 1.3.36 / sequence 1237 – staged source candidate

Source basis: latest repository ZIP `display-planiq-main(7).zip`; no older repository files used.

Status: **source identity staged**; GitHub CI for this exact change pending; NOT built, NOT approved, NOT published, NOT catalog-promoted, and NOT physically accepted.

## Evidence and defect scope

Physical fresh install of immutable 1.3.35 / 1236 on Ubuntu 26.04.1 Viborg2 reached Chrome fullscreen and the local GUI, but failed final acceptance:

- `clientflow-kiosk-quicksettings-guard.service` failed with `setpriv: setresuid failed: Operation not permitted` in the systemd sandbox.
- Post-final-reboot Chrome acceptance rejected a live Chrome main process despite the correct executable and kiosk UID, because Chromium flattened process argument text into argv[0].

1.3.36 source includes the revised service capabilities, strict Chromium process-title handling, and regression tests. Green source-level CI is **not** physical acceptance.

## Release boundaries

- Keep `backend/service1/clientflow_release_catalog.json` at approved **1.3.35/1236** until exact-source CI, deterministic transport, independent reproducible release builds, explicit approval and immutable publication complete.
- 1.3.36/1237 is not available through the production fresh-install selector yet.
- Never replace or mutate the approved 1.3.35/1236 TAR or its Render store entry.
- No automatic upgrade/rollback or unauthorized in-place upgrade on Viborg2 or Ringkøbing1.
- The new approved candidate will still require **fresh physical installation** and independent acceptance testing before declaring success. Preserve 1.3.35 failure evidence.
- Runtime lock remains exactly Python 3.13.14 and its verified locked platform bytes; no dependency/runtime drift in this source-stage change.

## After exact-source green CI

Run the canonical `runtime-input-transport.yml` workflow for the exact green `main` SHA, then `release-build.yml` using the reported transport URL and outer SHA-256. Record independent build identity and candidate/installer SHA-256 before proceeding to explicit release approval. Promotion remains a separate gate after immutable store publication.
