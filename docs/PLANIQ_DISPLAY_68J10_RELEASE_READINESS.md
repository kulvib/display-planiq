# 68J-10 – accessibility and release readiness

Reviewed baseline: main `1a4615e144e9e0a29a9505d12c57f700908b4c8e`, merged PR 443. PR CI [46021976756](https://github.com/kulvib/display-planiq/actions/runs/46021976756) and single-node smoke [46021976882](https://github.com/kulvib/display-planiq/actions/runs/46021976882) completed successfully. Both Render services were live on that commit. Separate main CI was not returned by the connector.

## Changes and evidence

- Shared MUI keyboard focus indicator and native link/select focus styling. Explicit accessible names for Control Room back, copy, client removal/purge, diagnostics refresh, and user/audit search clearing. Existing visible labels, event handlers, roles, button sizes and layouts remain unchanged. No change to Remote Desktop/Terminal keyboard capture or Livestream media logic.
- Source regression tests prevent loss of these names and focus styles. They are not a browser accessibility conformance audit. Desktop 68J-7 acceptance is 7 PASS, 0 FAIL, mobile untested; focused keyboard/mobile and physical checks remain required.
- The central theme was absent from the existing checksum manifest; add its verified new content hash. Other modified tracked files matched their previous manifest entries.
- Read-only Render request log check starting at backend deploy completion 2026-11-27 15:27:35 UTC (16:27:35 Copenhagen): one HTTP 502 on System presence, no HTTP 500 in the returned window; no further pages. This short observation is not a reliability SLA, root-cause proof or proof that all connections are healthy.
- Maintainability: do not split working media/router modules solely on line count. Characterize contracts before extraction. No speculative refactoring in this tranche.

## Recovery boundary

The 62B and 62E scripts and documents are historical, hash-pinned evidence, not a current general-purpose recovery procedure. 62E pins release sequences 1243/1244/1245. Do not edit historical pins, run a live dump or declare the current release history covered by these old proofs. Single-node CI restores synthetic data only. Current production recovery needs a separately reviewed current artifact inventory, secure encrypted independent destination, retention policy and isolated restore. Production dump/credential material must never enter GitHub, CI artifacts, chat or ordinary logs. No new paid service is implied. Actual backup/restore and measured recovery time remain open, not release approval evidence.

## Next release gates

1. Green CI on this PR and merged source. Frontend deployment and targeted operator keyboard/mobile plus physical 68J-9 regression (online, kiosk, control commands, browser resync, simultaneous RD/Livestream, Terminal/files). Do not require another full repeat of already accepted desktop visual checks.
2. Freeze exact main and verify current canonical CI. Prepare runtime-input transport using verified current source/inputs; then canonical unsigned candidate build and provenance/reproducibility proof. Never use a previous source SHA or guessed artifact digest.
3. Separately implement artifact-bound authorization for 1251 and explicit recovery policy, preserving approved 1250 baseline and existing fleet/fresh-install holds. No install or promotion before this gate.
4. Physical install/acceptance of candidate on Viborg1 only: systemd diagnostics, Ubuntu/firmware, kiosk reboot, media recovery, ten Livestream starts, concurrent media and Terminal/files. Verify actual release identity and safe recovery. No release publication before acceptance.

This tranche changes frontend presentation and documentation/tests only. No runtime, backend, database schema, Render configuration, catalog, credential or release authorization change. Remaining full endpoint authorization audit, fleet/media load, production backup and complete accessibility review are tracked rather than falsely declared complete.
