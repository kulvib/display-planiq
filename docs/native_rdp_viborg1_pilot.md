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
FreeRDP 3.33.1 Emscripten build. The compiled JavaScript and WASM runtime ARE
NOW source-pinned in frontend/public/native-rdp with their complete provenance:
GitHub Actions build 45066909031 passed and independently SHA256-verified
sdl-freerdp.js (269234 bytes, sha256 609715445d2dc9f637f386572566b10fa8b3b9f0736f483a1d6a5ed423ee8cb5)
and sdl-freerdp.wasm (11089855 bytes, sha256
808752fe85bb1d65964d19f4b5d40cf990d1708c437ff0e40ec92f5994d7cf90).
The exact compiled files were integrated into PR #408, not deployed. The iframe's credential fields are never
posted to the PlanIQ API. A trusted GNOME TLS SHA256 fingerprint is required
before the WASM client can connect; /cert:ignore is explicitly forbidden.

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
3. Only AFTER checking the actual nftables guard, systemd root watchdog,
   active GNOME Desktop Sharing, boot ID, six-minute expiration and a fixed
   RDP port, run the **new fail-closed companion**
   `sudo python3 scripts/clientflow_native_rdp_browser_pilot.py arm`
   on Viborg1. The source must be taken from the immutable reviewed commit
   and run from the same local directory as the accepted 63D-29/30 scripts.
   This creates a boot-ephemeral root-owned mode 0644, **JSON expiration-bound**
   approval marker at /run/clientflow/native-rdp-approved; no secret stored.
   A 0600 file is not readable by the non-root ClientFlow agent.
   `arm` prints only the PUBLIC TLS certificate SHA-256 fingerprint, never
   login credentials; the GNOME temporary login is held in the existing
   root-only `/run/clientflow-rdp-63d30/credentials` file.
   To stop, `sudo python3 scripts/clientflow_native_rdp_browser_pilot.py disarm`
   **first**, then use the independently accepted 63D-30 `stop` action.
   Do not remove the firewall before GNOME has shut down.
4. Confirm GNOME's temporary RDP username/password and TLS are initialized
   in the kiosk's session without leaving credentials in argv, logs or env.
5. Verify the already committed, source-pinned FreeRDP WASM runtime against
   `node frontend/scripts/checkNativeRdpWasm.mjs`; the build script always
   verifies exact binary hashes, not just filenames. No CDN is used.
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
- Before production: enforce and test step-up for native input; complete signed
  artifact provenance, review browser codec compatibility, verify certificate
  fingerprint collection/rotation and implement seamless native reconnect.

## Rollback

Disable VITE_NATIVE_RDP_PILOT on frontend. Remove root marker on Viborg1;
close GNOME sharing and revoke temporary GNOME RDP credentials; retain nft
firewall until all sockets are closed. Keep JPEG browser streaming and the
existing control/files channels. Do not merge PR #407 or deploy from draft.

## Security hardening after initial draft

- Native RDP endpoints are hard-gated server-side to Viborg1 client ID 3,
  not only gated in the React UI.
- A trusted **SHA-256 certificate fingerprint is mandatory**. The browser
  passes `/cert:fingerprint:sha256:<colon-separated-hex>` to the official
  FreeRDP client and never `/cert:ignore`. Collect the fingerprint from the
  local GNOME RDP certificate through an independently trusted administrative
  session, not from the intercepted connection being established.
- The isolated iframe's scoped CSP includes `wasm-unsafe-eval`, required for
  instantiating the reviewed WebAssembly module without allowing general JS eval.
- The Emscripten POSIX socket adapter uses `Module.websocket.url` and
  `Module.websocket.subprotocol`, which are documented socket-proxy settings.
  The browser requests the ticket with the normal PlanIQ WebSocket subprotocol;
  the backend relays bytes unchanged to the fixed loopback target.

## Audited local pilot source incorporated

The physically tested, standalone operator-invoked firewall/watchdog,
GNOME Desktop Sharing and preflight scripts from the accepted 63D-34 pilot
are imported as UNMODIFIED files into this draft. They are not installed
into ClientFlow releases automatically and are not executed by CI. The
6-minute timeout in the old 63D-30 physical runner remains a fail-closed
safety feature; extending it requires its own operator-reviewed approval.

## Verified artifact integration and current gates (2026-11-22)

- Official FreeRDP 3.33.1 WASM build **PASS**, including upstream Node tests.
- Source-pinned JS/WASM artifact **verified and committed into PR #408**.
- The write-permitted artifact integration workflow was temporary and removed
  after the reviewed files were committed. Normal branch CI remains read-only.
- Frontend now fails its build on missing or modified FreeRDP assets if the
  pilot is enabled; if assets exist, it hashes them even while disabled.
- Existing Render Docker/PostgreSQL smoke and GitHub CI are independently
  required at the final branch head before any staging or merge.
- GNOME 50.2 RDP negotiations, SDL canvas display, browser mouse/key events,
  30-minute recovery and actual browser-to-pixel p50/p95 remain **UNTESTED**.
- The older 6-minute GNOME source runner is an independent physical safety
  gate. It must not be silently extended and is not the 30-minute performance
  test environment; stabilize the first screenshot before longer sessions.

## Critical six-minute pilot revocation protection

The new unprivileged agent now validates the root-owned approval JSON against
both the GNOME pilot's wall and monotonic six-minute expiration AND the
current machine boot ID. It rejects a symlink, wrong UID/permissions, hostname
or client ID, altered expiry, reboot and every expired marker. The RDP data
pump revalidates the grant before each packet in both directions AND every
second even when idle, forcibly closing the local TCP and outbound WSS sockets
on expiry. No route is accepted for any client other than Viborg1 ID 3.

The old 63D-30 systemd watchdog independently disables GNOME RDP and restores
the original settings on expiry; its earlier physically tested code is
unchanged. A stale marker left under /run cannot revive the tunnel after
the watchdog shuts down the GNOME pilot. Do NOT extend the physical timer
during this first end-to-end test or silently change other firewall rules.

**No real physical test or remote mouse movement is claimed here.** The
reviewed source must first be deployed to the correct client and Render
backend, then operator-run on the actual Viborg1 machine. The server,
agent, frontend, GNOME Desktop Sharing, nftables kernel state and remaining
six-minute timer must all be accepted before displaying a remote frame.

## Render anti-framing headers and runtime validation

Render static sites can apply overlapping wildcard and path-specific response
headers. The wildcard X-Frame-Options `DENY` and CSP
`frame-ancestors 'none'` would block the intentionally embedded same-origin
FreeRDP iframe EVEN IF the narrower `/native-rdp/*` header says SAMEORIGIN.
The wildcard now consistently uses `X-Frame-Options: SAMEORIGIN` and
`frame-ancestors 'self'`: external framing remains prohibited. The
`/remote-desktop/*` page retains the stricter `frame-ancestors 'none'`,
while `/native-rdp/*` is permitted to be embedded only by the same origin.

Before starting the physical GNOME pilot, inspect **deployed** HTTP response
headers for both `/remote-desktop/3` (SPA rewrite) and
`/native-rdp/viewer.html`: COOP `same-origin`, COEP `require-corp`,
X-Frame-Options `SAMEORIGIN` on the iframe, and no restrictive
`frame-ancestors 'none'` on the iframe response. Check that
`window.crossOriginIsolated === true` in both browser contexts.
Changes to `render.yaml` do not themselves prove the live Render service's
headers were updated; Render Dashboard/Blueprint rules must match deployment.
