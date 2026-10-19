# ClientFlow 1.3.40 / sequence 1241 — source-stage

**Status: STAGED SOURCE IDENTITY ONLY — NOT approved — NOT published — NOT catalog-promoted.**

This commit is **not** an authorization for `in_place_update`, manual rollback or fleet rollout. Heidi1 stays on its physically accepted `clientflow-1.3.38-seq-1239`. This phase does not touch the installed client; no Linux reinstall is required or authorized. No installed ClientFlow files, approved TARs or Render release-store objects are modified by this stage.

## Canonical identity and source SHA

- Set `client/VERSION=1.3.40` and `client/release/release-input.json` `release_sequence=1241` (one sequence after the already cataloged 1240). Ubuntu `26.04` amd64, GNOME/Wayland and runtime Python `3.13.14` remain pinned.
- The exact **source SHA** is unknown until GitHub merges/records the new commit; derive it from that commit, never from a locally produced ZIP. Require exact-source CI before any immutable build.
- **Do not change** `backend/service1/clientflow_release_catalog.json` here. It remains `catalog_sequence=1240`, `latest_stable=1.3.38`, `default_install_version=1.3.38`. Its original 1.3.38 fresh-install-only release and the failed, immutable 1.3.39/1240 pilot metadata remain unchanged. The old `CLIENTFLOW_1240_PILOT_CLIENT_ID` flag must stay absent in production. The catalog has **no** 1.3.40 record, so source identity alone cannot authorize update or install.
- The 1.3.39/1240 deployment `703c5a33-192d-4a7b-b7d4-78a2f1413cab` remains terminal `recovery_failed`; do not rewrite history. No 1.3.39 bytes, SHA or approval reference are replaced.

## What the 1.3.40 candidate must carry from approved repository code

1. **Activation sandbox:** systemd update-controller is root with `ProtectHome=tmpfs` and a limited `BindPaths=/home/clientflow-kiosk` rather than `ProtectHome=yes`. The prior 1.3.38 controller cannot be fixed simply by updating the *target* release. `scripts/clientflow_1338_controller_bridge.sh` requires separate audited, explicit host authorization after confirming no in-flight deployments. Do not run it as part of this source-stage, and verify how its drop-in is retired after upgrading.
2. **Recovery and provenance:** exact approved release, existing transaction lock, immutable release-tree verification, bounded and credential-safe failure records, separate original activation and rollback causes, fail-closed `activation_intent`, health-before-commit, and 1.3.38 recovery semantics. A failed health gate must never be marked completed.
3. **Kiosk always-on:** GNOME idle timeout `uint32 0`, lock/idle activation disabled, sleep disabled, GNOME notification banners suppressed, popup/autostart overrides retained. Periodic policy verifies the *actual* session and runs every minute; optional lockdown disable must not reset the display/lock baseline.
4. **Runtime and experience:** Chrome/Wayland fullscreen and GUI auto-start, browser guard, clipboard and cookie behavior, content refresh, calendar/display-power cooperation, no unwanted system popups, inactivity stability, and reboot survival. Keep deliberate calendar-powered display-off distinct from accidental GNOME blanking.
5. **Control Room and Clientlist:** a historically `expired` Control Room reboot command must remain in history but not mask a verified new boot and online/normal status; retain `reboot_completed` provenance. This is an already deployed backend correction, not a reason to change the immutable 1.3.39 artifact.
6. **Operational boundaries:** status and GUI; authorized Terminal, Remote Desktop, Livestream, System and update features; no kiosk sudo; no new paid services/Neon or new PostgreSQL infrastructure; no silent bypass of DPoP/HTTPS, release approval or UI confirmation.

## Browser fullscreen telemetry — approved 2026-10-19, pre-build PR

- Physical Heidi1/Ubuntu 26.04/Wayland evidence: Chrome CDP `Browser.getWindowForTarget` reported `normal` when the window was not fullscreen, and `fullscreen` after the technician toggled F11; both were physically corroborated. `document.fullscreenElement` and window geometry must **not** be substituted for browser-level fullscreen.
- The 1.3.40 source extension uses *read-only* Chrome CDP over `127.0.0.1:9222` with a validated, loopback-only browser WebSocket. A bounded off-thread probe avoids blocking the Display control socket; no GNOME introspection permission change or GNOME extension is allowed.
- Display-runtime writes `browser_fullscreen=fullscreen|windowed|unknown` with an independent observation time to its existing group-readable status file. Status/Display agent already forwards that file; backend projects the status from the canonical Display row with a 120-second staleness bound, retaining `unknown` for old clients, missing/ambiguous pages, Chrome stopped, stale reports or intentional display off. No schema migration, new database query or new paid service.
- GUI, Control Room/clientlist and client details each show an explicit fullscreen indicator separate from the browser-running state. Changes in fullscreen must become visible via the existing status/realtime/poll transport without a refresh or Chrome restart; do not falsely infer fullscreen from the start flags alone.
- Extend the physical acceptance of the **new** release: verify browser normal -> windowed, F11 -> fullscreen, back to normal -> windowed, Chrome stop -> unknown, reboot and lockdown on/off, and verify the GUI plus both web views converge after agent reports. No fullscreen autopilot/window mutation in this feature.
- Runtime-input transport and reproducible build must use the **new source SHA after this PR**, not PR #295's prior SHA.

## Release gates — separate and sequential

1. **Source-stage PR and GitHub CI:** stage only the version/sequence, current identity tests, historical catalog-bound assertions and SHA256SUMS. CI must remain strict; do not modify approved catalog policy. Review the entire changes-only diff.
2. **Exact-source and runtime-input:** record the exact 40-character Git source SHA; verify source-frozen CI, runtime-input transport matching the pinned lock and architecture/runtime dependencies.
3. **Build and on-host gate:** two independent **reproducible**, byte-identical release builds; Ubuntu 26.04/amd64 executable/runtime smoke gate; record source, candidate, embedded installer and final bundle SHA-256, size and immutable approval reference. Preserve a backup and disk-space margin for local PostgreSQL and the release store.
4. **Explicit approval and immutable publication:** use the normal GitHub-approved transport and Render persistent store with independent reread. No overwrite/rebuild of 1.3.38 or 1.3.39; publication and catalog promotion are separate changes requiring explicit sign-off.
5. **Promotion and authorization:** add *only the approved* 1.3.40 identity in a reviewed later catalog PR. Explicit `in_place_update` source range, exact artifact/provenance, per-client authorization, status/boot/version gates and no automatic fleet rollout. Keep remote rollback blocked unless separately approved and physically validated. The anti-rollback rule must respect Heidi1's `highest_release_sequence=1240`.
6. **Legacy controller bridge:** after physical readiness and a verified idle deployment queue, inspect the 1.3.38 `ProtectHome=yes` unit, verify the bridge preconditions and do a separate dry-run, explicitly authorize the limited host drop-in and independently probe its effective systemd sandbox. Preserve its forensic backup. Prove the transition and eventual drop-in cleanup; no opportunistic direct `systemctl` workaround.
7. **One physical update pilot:** only then deploy 1.3.38 -> 1.3.40 to Heidi1 with Control Room approval, immutable SHA, staged/activation/health/recovery journaling and the original local configuration, organization, credentials and client id unchanged. No Linux reinstall (no Linux reinstall), manual symlink edits or JSON-state surgery.
8. **Post-update acceptance:** status Online/normal in Control Room *and* Clientlist; Chrome/Wayland fullscreen, GUI, calendar-driven display on/off; at least 8 minutes of real idle with Mutter `i 0`, GNOME `idle-delay=uint32 0` and lock disabled; restart survival and popups blocked; optional lockdown **on and off** must preserve the always-on baseline. Verify Browser Guard, clipboard/cookies, Terminal, Remote Desktop and Livestream in real use, not just unit tests.
9. **Failure injection:** test unsuccessful activation/recovery, power loss and network loss in isolated stateful/unit tests before any destructive physical pilot. Preserve and report the original and recovery errors; never declare a command/deployment `succeeded` when it was `expired`/`recovery_failed`.

## Evidence and limitations from Heidi1

- The approved manual recovery restored `1.3.38` after the failed 1.3.39 activation. Local services, backend presence and physical Chrome/GUI were accepted; GitHub PR #294 corrected stale `rebooting`/`error` status in both UIs.
- On 2026-10-19, Heidi1 displayed GNOME defaults `idle-delay=uint32 300` and `lock-enabled=true`; an 8-minute physical measurement recorded Mutter switching from `i 0` to `i 3` while calendar power remained `on`. After explicitly restoring the kiosk baseline, 8-minute physical testing and reboot checks passed on **old 1.3.38**. The exact actor that reset GNOME's values was not proven.
- The 1.3.40 kiosk/lockdown and controller fixes are **not yet physically tested as that release**. No blanket popup-free claim for arbitrary third-party webpages; test actual sites and OS dialogs.

**Next gate:** Merge source-stage with full GitHub CI, then obtain a new exact-main ZIP and **stop** for separate runtime-input and build approval. Do not auto-activate `1.3.40`, publish any TAR, mutate the production catalog or run the 1.3.38 bridge in this phase.
