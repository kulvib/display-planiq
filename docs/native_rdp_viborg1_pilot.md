# PlanIQ Display — Native GNOME RDP browser pilot on Viborg1

**Status: draft implementation only. Not approved for deployment or as a
replacement for JPEG Remote Desktop. No physical browser test has passed.**

## Architecture (one coherent feature, not PR #407's RFB experiment)

PlanIQ Display superadmin session and one-time browser ticket
  -> authorized existing Remote Desktop control session
  -> second, session-bound *binary* WebSocket
  -> existing Render Docker / PostgreSQL backend (relay only; no database per PDU)
  -> agent-initiated WSS 443
  -> fixed 127.0.0.1:3389 on the Ubuntu client
  -> GNOME 50.2 **Desktop Sharing of existing Wayland kiosk session**.

The browser uses a disposable same-origin iframe running the official SDL3
FreeRDP 3.33.1 Emscripten build. WebAssembly output is intentionally NOT
pretended to exist in the repository: the source-pinned GitHub workflow builds
and publishes a reviewable artifact. The iframe's credential fields are never
posted to the PlanIQ API. TLS trust is NOT pinned in the current pilot
("/cert:ignore") and therefore MUST be strengthened before production.

The browser's original JPEG/WebSocket + HTTPS-long-poll transport is retained
as the functional fallback when RDP's WebSocket Upgrade is blocked. This is
not the same as sending native RDP PDUs over HTTP fallback; implementing that
would require a carefully tested Emscripten socket transport adapter.
The client never opens an inbound tunnel and Render never exposes RDP.

## Source and platform pins

- PlanIQ starting main: 523f970e6f0ada41aa559fd5f07e5e8ea1609896
- GNOME RDP physically proven **only via loopback FreeRDP** on Viborg1: real
  pixel change, mouse input, 120.7 ms median local input-to-pixel. Browser
  metrics are unknown.
- FreeRDP 3.33.1 source commit:
  65bcca1913a28cbdd7eb913599f692bd2b707991
- Emscripten official upstream scripts/emscripten.sh, emsdk 6.0.12,
  pthreads and ASYNCIFY; WSS-to-TCP socket bridge, COOP/COEP required.
- The upstream build deliberately disables FFmpeg and OpenH264. Full GNOME
  EGFX/AVC capability is **not proven**. If GNOME cannot negotiate a codec
  supported by this build, stop and choose the PipeWire/modern-video pathway;
  never claim compatibility based on desktop FreeRDP results.

## Safe launch sequence: do not skip gates

1. Confirm only physical **Viborg1**, hostname viborg1-NUC14MNK-B2,
   identity client ID 3, Wayland GNOME 50.2, non-production.
2. Review and activate the previously physically accepted GNOME Desktop
   Sharing + persistent nftables firewall/boot-watchdog pilot from #404/#407.
   The guard must be installed BEFORE any GNOME listener is enabled.
   Check both TCP and UDP 3389 are blocked on non-loopback interfaces, and
   verify that GNOME Desktop Sharing is not Remote Login.
3. Only AFTER verifying the guard is active and its watchdog survives an
   agent restart, create the boot-ephemeral root-owned **read-only** approval
   marker: /run/clientflow/native-rdp-approved.
   The exact ASCII contents must be hostname + ":" + client ID + newline,
   e.g. "viborg1-NUC14MNK-B2:3\n", owner root:root, mode 0644.
   This file contains NO secret. Its ownership and restricted write
   permissions matter; mode 0600 would prevent the unprivileged agent from
   reading it. Never mark approved merely because RDP starts.
4. Confirm GNOME's temporary RDP username/password and TLS are initialized
   in the kiosk's session without leaving credentials in argv, logs or env.
5. Run FreeRDP WASM build workflow; inspect artifact manifest SHA256;
   copy verified sdl-freerdp.js/.wasm and any worker/runtime assets under
   frontend/public/native-rdp. Do not obtain a mutable CDN build at runtime.
6. Verify Render static frontend /remote-desktop/* and /native-rdp/*
   response headers, in a **new page navigation**: COOP same-origin,
   COEP require-corp, isolated iframe, X-Frame-Options SAMEORIGIN and
   expected CSP. Fail closed if crossOriginIsolated is false.
7. Deploy the exact backend draft + agent bundle to the approved test
   environment, without changing Render Docker database or Neon.
8. Enable VITE_NATIVE_RDP_PILOT=true on the test frontend for client ID 3,
   then use PlanIQ Display -> Viborg1 -> Remote Desktop -> GNOME RDP pilot.
   Confirm screenshot, pointer down/up, drag/scroll, keyboard press and
   release, fullscreen, forced reconnect and fallback. A green CI or local
   loopback test is not this acceptance gate.

## Security/lifecycle and performance acceptance

- All browser native RDP WSS connections require a fresh PlanIQ one-time
  ticket AND an existing active Remote Desktop session with matching user,
  login-session binding, token version and client ID.
- One tunnel per client, max 128 active across the single Render instance;
  a unique generation/tunnel ID prevents stale connections from being reused.
- Agent WSS requires its own renewable credential, exact session/tunnel ID.
  A revocation/session/expiry check happens at most per 15 s interval on
  active bytes; never issue PostgreSQL reads on individual RDP packets.
- The binary tunnel is ordered and backpressured; never drop or coalesce
  arbitrary RDP PDUs. Native tunnel loss releases local socket and closes
  both ends. The existing file and input planes remain intact.
- Prove RDP listener never reachable from Ethernet/WiFi, that GNOME sharing
  shuts down before firewall guard removal, and that no marker survives
  reboot. Remove marker FIRST during cleanup.
- Compare browser actual user-to-visible-change p50/p95 (not just network
  ping) with local 120.7 ms baseline; record observed FPS, jitter, scrolling,
  key repeats and 30-minute reconnection/idle behavior.
- Test HTTPS fallback via an environment where WebSocket Upgrade is blocked;
  it must show the original JPEG desktop, even if slower than native mode.
- Test 100 **connected idle clients** separately from 100 active RDP viewers;
  memory/CPU/bandwidth envelopes for 100 active streams are not yet proven.
- Before production: replace /cert:ignore with validated/pinned GNOME RDP
  TLS fingerprints; integrate a recent step-up gate for native input; build
  signed/reproducible artifact provenance, review browser codec compatibility,
  and implement a clean seamless native reconnect strategy.

## Rollback

Disable VITE_NATIVE_RDP_PILOT on frontend. Remove root marker on Viborg1;
close GNOME sharing and revoke temporary GNOME RDP credentials; retain nft
firewall until all sockets are closed. Keep JPEG browser streaming and the
existing control/files channels. Do not merge PR #407 or deploy from draft.
