# Fase 63D-34 · Native GNOME RDP transport contract (NOT activated)

Date: 22 November 2026. This document accompanies draft PR #407, not a deployment/release.

## Physical baseline reused

- GNOME Remote Desktop on Viborg1 existing Wayland kiosk session, not Remote Login, physically tested in PR #404 with 5/5 GTK click-ACK and corresponding FreeRDP Xvfb pixel changes; local p50 120.7 ms, max 123.7 ms.
- PR #405 already merged: current Render Docker/PostgreSQL backend, frontend JPEG viewer telemetry, HTTPS fallback and HLS handling. Active physical release 1.3.47 / seq-1248 remains unchanged.
- Browser **must** display and control the GNOME desktop directly **inside PlanIQ Display**, never invoke an external administrator RDP application.

## Implemented in this stage

- Pure Python/JavaScript opaque binary RDP chunk validators, strict session UUID + connection-generation UUID binding, protocol version, canonical base64, 16 KiB per chunk, ordered sequence, at most eight unacknowledged chunks, no dropping/replacing/replaying data.
- Negative tests for forged sessions, stale generation after reconnect, malformed base64/oversize/extra fields, out-of-order/duplicate data, excessive queued packets, and incorrect acknowledgments.
- Framing uses JSON deliberately so the **existing** authenticated WSS and HTTPS fallback could carry it later. It is *not* yet connected to the production broker, GNOME, WebAssembly, or browser screen, and adds no new external endpoints, packages, background tasks, services or databases.
- This framing is not JPEG frame replacement and **must not** be run on the existing JPEG/control lane without an independent, bounded data lane and backpressure.

## Important security and architecture STOPs before wiring

1. A browser cannot decode plain GNOME RDP unaided. Select and prove a *specific* version-/source-pinned browser-capable RDP decoder (e.g. IronRDP/WASM), including its precise RDCleanPath/proxy handshake with GNOME 50.2. The upstream example is not production-ready by itself.
2. Browser cannot open a local TCP connection to Viborg1 behind NAT. Implement a client-initiated outbound 443 reverse relay with authenticated PlanIQ superadmin, tenant/client/session binding, short-lived revocable credentials, verified loopback-only GNOME server TLS identity, and no cleartext RDP credentials in URL or logs.
3. Preserve the physically accepted root firewall, watchdog, stopped-state after reboot, and complete rollback. An active GNOME RDP start requires an independently accepted **runtime supervisor**, not invoking the one-time physical pilot scripts as if they were persistent services.
4. Ensure true RDP byte stream semantics independent of individual WebSocket/HTTPS messages; **never** discard an RDP packet to keep video fresh. Enforce limits under slow receivers. Reconnect must create a fresh stream generation.
5. Native RDP and JPEG may coexist only as mutually exclusive, explicitly selected viewers while testing. Do not add idle RDP gateway processes or extra Render services.
6. The existing HLS media-sequence +1 source fix still requires an approved successor to 1248 and physical frontend confirmation; do not assert livestream or browser RDP solved by green protocol tests.

## Gate

CI backend Python, Node frontend, source SHA pin and single-node PostgreSQL smoke must pass on exact new commit. Then develop the authenticated reverse relay and browser decoder in the same draft PR, separately validate isolated protocol/handshake failures, and only afterward perform a guarded physical browser pilot on nonproduction Viborg1. No merge, Render deploy, ClientFlow release, or client system change at this stage.
