# PlanIQ Display · 63D-34 · Verified GNOME RDP baseline handoff

Date: 2026-11-22. Scope: source and test import **only**, no runtime installation, network service, database migration, release approval, merge or deployment.

## Physical facts — already accepted, not to be retested as a prerequisite

- Original pilot: draft PR #404, pinned source `77105ae39127c623b51855b49fd8cbb0e9b11c9e`, Viborg1 (`CLIENT_ID=3`), Ubuntu 26.04.1 / GNOME 50.2, active ClientFlow 1.3.47 / seq-1248.
- GNOME **Desktop Sharing of the existing Wayland kiosk session**, not system Remote Login. Authenticated loopback FreeRDP / Xvfb only, bounded pilot and root-owned firewall watchdog.
- Real GTK remote-click acknowledgements: **5/5**. Corresponding independently observed FreeRDP X11 red/green pixel transitions: **5/5**.
- Local input-to-GTK callback p50 **1.4 ms**, max **2.3 ms**; local input-to-FreeRDP visible sampled pixel p50 **120.7 ms**, max **123.7 ms**.
- Clean after pilot: temporary Keyring alias/TLS/credentials removed; RDP disabled, nft firewall and watchdog cleaned, no RDP listener; physical final preflight **PASS** and `SYSTEM_CLEAN=True`.
- All cited local numbers are **single-host loopback**, not browser/Render/HTTPS and not an end-to-end web result.

## Integration baseline from the current main

- PR #405 was already merged and deployed to existing Render Docker single-node PostgreSQL backend and static frontend at `523f970e6f0ada41aa559fd5f07e5e8ea1609896`; browser transport timing and HLS-label fixes are retained.
- Current frontend/browser path still uses JPEG over WebSocket or bounded HTTPS long-poll fallback; the GNOME RDP pilot is **not** yet a browser media transport.
- Render backend must remain Docker with local PostgreSQL; **no Neon**, separate paid backend, Redis, externally reachable RDP/guacd or additional billing.
- `client/runtime/clientflow_runtime/livestream_uploader.py` in main includes the known `hlssink` +1 media-sequence normalization for future staged 1.3.48 / seq-1249; this was not installed on the physical 1248 kiosk.

## What this branch changes

Copy exactly the 19 validated, unmodified code/test/documentation blobs from PR #404 into the current main-based branch. Append their 17 source SHA256 pins to the **current** main manifest, without restoring stale SHA pins for old frontend code.
Do not cherry-pick all 142 commits of the diverged pilot or overwrite changes from PR #405. Existing pilot, root watchdog and SSH/credential isolation contracts remain as they were physically accepted.
All added scripts are operator-invoked only; there is **no** automated activation in this import, no new systemd unit installation and no changes to ClientFlow release packages.

## Remaining gate: real browser transport, not local RDP again

1. Select or implement a **reviewed, supportable RDP-to-browser translator**. Raw RDP cannot be decoded by an ordinary browser and a local FreeRDP loopback client does not by itself solve this step.
2. Authenticate through PlanIQ superadmin, preserve client ID/org binding, active login/ticket/session revocation and explicit read-only/media versus input permissions.
3. Use client-initiated outbound approved HTTPS/TCP 443 to existing Render; retain functional HTTPS fallback where WebSocket Upgrade is unavailable, with no secret-bearing URLs/logs or open RDP/guacd port.
4. Prove bounded frame queues, ordering of clicks/key up, timeout, reconnect, exit/kill/reboot fail-closed, operator stop, and source/ABI/library security. No unvalidated extra dependencies on Viborg1.
5. After new code CI + single-node PostgreSQL smoke succeed on the exact merge head, run controlled **browser input-to-pixel p50/p95** on the already approved nonproduction Viborg1, then independent HLS upload/manifest/frontend smoke for release 1249 or safe successor.
6. Only then consider merge, release candidate, reproducible SHA-bounded approval, Render publication and client rollout with rollback.

## Existing status of the abandoned JPEG experiment

`pilot/63d34-hls-rd-media-lane` contains an incomplete, **untested** separate JPEG socket experiment with unresolved imports; it is excluded from this branch and must not be merged or deployed as the GNOME RDP bridge.

References: PR #403 (hardware/firewall feasibility), PR #404 (physical GNOME RDP acceptance), PR #405 (merged browser telemetry), issue #406 (integration and accept gate).
