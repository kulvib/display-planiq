# ClientFlow 1.3.37 / sequence 1238 — source identity stage

Status: **STAGED SOURCE IDENTITY ONLY** — NOT approved, NOT published, NOT catalog-promoted.

- Source version: `client/VERSION` = `1.3.37`; anti-rollback sequence `client/release/release-input.json` = `1238`.
- Last approved production catalog remains **1.3.36 / 1237**, **fresh-install-only** with in-place updates and rollback blocked.
- No release artifact, immutable hash, Git source SHA, approval reference, or runtime transport is claimed here.
- The source identity must pass complete GitHub CI at the exact new commit before running `runtime-input-transport.yml` and `release-build.yml`.
- Immutable artifact approval and Render publication require their independent workflows and checks. Do not change catalog early.
- The physically installed Viborg4 client is currently on 1.3.36; **do not attempt an in-place update** to 1.3.37 until the upgrade path is physically validated and explicitly authorized.

## Scope to verify before approval

- Client GUI: visible SVG logo, copy buttons on the physical GTK4/Wayland session, GUI not closable/minimizable.
- Control Room: full action matrix for browser and display, permissions, busy/in-flight conflicts and reboot/shutdown, on the actual test client.
- Browser countdown: dvale, startup, expiry and backend reconciliation in Control Room and client list.
- Mobile: portrait/landscape and timed Start/Stop; desktop must remain unchanged.
- Security: existing 1.3.36 fresh-install and post-final-reboot acceptance regressions remain mandatory.

Source-stage is deliberately not a release promotion or a claim of physical acceptance of these changes.
