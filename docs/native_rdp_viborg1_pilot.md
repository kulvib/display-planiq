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
GitHub Actions build 45178692053 passed the SDL3/Chromium/WebSocket proof,
integrated in separate staging commit 8b4939715566406763cb6f54a4398be82735c383:
sdl-freerdp.js (269234 bytes, sha256 c7d0a7e20a7b6473c5743892086b00dfb096807b8386adf992ab294867ad8112)
and sdl-freerdp.wasm (11086426 bytes, sha256
f5cfa907421b47c3ed6acdee329f5ebda7e9279c4a5972e02139dc8e2fe6f315).
The exact files are staged in unmerged draft PR #412. On 2026-11-23 the *frontend* was temporarily deployed from staging commit d5e5db2; the Render backend remained on main 9898ab5. This is not release approval. The iframe's credential fields are never
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
- Corrected SDL3/Chromium-verified JS/WASM artifact **staged in draft PR #412**; no Render deploy or Viborg1 release change.
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

## 63D-42 — Physical black-screen failure and next isolated fix (23 November 2026)

**Status: development candidate, NOT an approved Remote Desktop release.**
Do not merge PR #411 or #412, deploy a new backend/agent, or approve release
1249 until the new candidate is reviewed and the *physical* Viborg1 pilot
works. The physical client was restored after the failed pilot: original
1248 agent active, temporary systemd override removed, GNOME RDP disabled,
expired browser grant removed and rollback timer stopped.

### What the physical evidence actually proves

At 14:25:43.960 UTC GNOME logged an initial OTHER_ERROR, followed by
GRAPHICS at 14:25:44.050. At 14:28:06.369 the later READ_FAILURE and
TRANSPORT_ERROR appeared, then disconnect/write failures. A later
OTHER_ERROR/GRAPHICS pair appeared at 14:28:40.880/14:28:40.974.
The browser and agent WSS both connected for approximately 144 seconds,
but the browser remained black. The later transport close does **not**
prove that it caused the initial failure. Existing GNOME journals alone
do not distinguish missing client bytes, incomplete GNOME negotiation,
unavailable graphics codec or an SDL render issue.

Inspecting the **actual** pinned FreeRDP 3.33.1 generated Emscripten
SOCKFS shows that it sends typed-array binary WebSocket messages and
receives ArrayBuffer messages. It maps multiple WS frames to a TCP
byte-stream abstraction; this does not itself prove correct end-to-end
RDP behavior. A browser frame larger than 64 KiB was previously rejected
by the Render relay. The 63D-42 browser adapter now splits outgoing bytes
in order into 16 KiB frames, rejects text and has a 2 MiB max buffered
send cap. No compiled JS/WASM hash, FreeRDP options, TLS pin or
credential handling has changed.

### Content-blind boundary measurements

The following counters are integers only. Do not log or persist
RDP PDU data, TLS handshake content, WebSocket tickets, GNOME credentials,
session UUIDs, tunnel identifiers or binary payload samples.

| Boundary | Diagnostic / direction |
| --- | --- |
| FreeRDP iframe | Browser binary sent/received frame counts and bytes |
| Render WSS relay | native_rdp_flow browser_to_agent_frames/bytes and agent_to_browser_frames/bytes, first-byte elapsed times |
| Viborg1 GNOME agent | native_rdp_agent_flow wss_to_tcp and tcp_to_wss frames/bytes |
| GNOME journal | First real handshake/graphics error in exact timestamp order, without printing secrets |

The relay periodically logs aggregate counts (at most once per 10 seconds
while active plus once at close) with **client ID only**. The agent logs
equivalent aggregates at most once per 10 seconds and at close. Both
measure only successful forwarding calls, never merely an open WSS
handshake; there is no DB query per packet and no new Render service.

### Decision table for ONE physical rerun

1. Browser outgoing bytes = 0: investigate FreeRDP/SDL/SOCKFS startup
   before the backend, not GNOME graphics.
2. Browser outgoing bytes > 0, Render browser_to_agent = 0: inspect
   WebSocket send/receive, protocol rejection or relay backpressure.
3. Render browser_to_agent > 0, Viborg1 wss_to_tcp = 0:
   investigate Render-to-agent pipe and connection lifetime.
4. Viborg1 wss_to_tcp > 0, tcp_to_wss = 0: inspect GNOME's earliest
   RDP/TLS/credentials/transport journal event.
5. Viborg1 tcp_to_wss > 0, Render agent_to_browser = 0:
   investigate the return relay.
6. All directions > 0 including browser received bytes, but screen
   black: focus next on GNOME negotiated graphics capabilities,
   compiled FreeRDP decoder capabilities and SDL3 rendering. Do not
   declare success just because RDP bytes flow.

The iframe fails closed if no outgoing RDP bytes are sent within 12 s
after WSS open or GNOME returns no bytes within 20 s, and ends an
unconfirmed visible-screen pilot after 45 s. A physical operator can
explicitly confirm **visible** GNOME pixels only *after* bytes have flowed
in both directions. This manual confirmation prevents an open socket
from being mistaken for a working desktop; it does not replace physical
mouse, drag, scroll, keyboard or latency tests.

### Mandatory controls and acceptance

- New development branch fix/63d42-viborg1-binary-rdp-telemetry
  is based on staging PR #412, **not** the Render auto-deployed staging
  branch. It must remain draft until independently reviewed.
- Keep release 1248 and its rollback, TLS SHA-256 pin, short-lived ticket
  and existing session binding. No open/externally reachable TCP/UDP
  3389. Restore GNOME root-watchdog + nftables guard using the official,
  immutable six-minute physical procedure before another pilot.
- Check actual deployment commits of frontend and backend, and that
  the temporary physical agent contains the new forwarder code before
  claiming that all four boundary counters are instrumented. A frontend
  deploy alone does not activate backend/agent counters.
- Require CI (including negative security/byte-preservation tests),
  Docker/PostgreSQL smoke and an observed actual GNOME image with mouse
  click/drag/scroll, keyboard and measured input-to-visible-pixel
  latency. JPEG fallback must work. No release 1249 on green CI alone.

## 63D-43 — RDP bytes reach browser but no image (physical evidence 2026-11-23)

The second physical Viborg1 run PASSed all firewall, six-minute GNOME timer,
root-only browser grant and temporary-agent integrity gates. The browser
reported **53,565 bytes / 858 WS frames to GNOME** and **4,325,501 bytes /
1,220 WS frames from GNOME**, but the desktop remained visually black. This
proves bidirectional delivery into the browser, **not** successful RDP graphics,
authentication, decoded pixels, or mouse/keyboard control.

The pinned FreeRDP SDL3 browser build delegates window creation to SDL3's
Emscripten video driver. Upstream SDL3's Emscripten CreateWindow defaults to
CSS selector `#canvas` unless an explicit SDL hint/window property overrides
it. The pinned FreeRDP SDL3 window creation does not specify such an override.
Our iframe originally used `<canvas id="desktop">` and the viewer bound
`Module.canvas` to that element; this mismatches the SDL3 selector and can
prevent drawing while WSS continues flowing. The fix changes the iframe to
`<canvas id="canvas">`, updates the `Module.canvas` binding and adds a
fail-closed selector guard and a Node regression test against the verified
compiled Emscripten JS. The compiled JS/WASM artifacts are left byte-for-byte
unchanged, as are the TLS pin, short-lived ticket, relay and agent.

This is a source-supported **root-cause hypothesis**, not a physically proven
fix. Only rerun physical Viborg1 after reviewing and passing CI and redeploying
the matching frontend source commit; confirm actual GNOME pixels, mouse and
keyboard before merging or cutting release 1249. Do not repeat the six-minute
pilot until its preceding cleanup state is verified.
  
## 63D-44 — Physical GNOME image succeeds; viewport sizing remains incorrect

A new 2026-11-23 Viborg1 physical screenshot shows **actual GNOME desktop
pixels** rendered by the pinned FreeRDP 3.33.1 SDL3 WASM client via the existing
secure binary tunnel (11,567 B / 146 frames to GNOME and 715,795 B /
193 frames from GNOME at capture). This supersedes the earlier black-screen
result for video rendering only. Mouse/keyboard input and latency are **not**
yet independently accepted.

The image was approximately 520x390 and pinned in the upper-left of a much
larger iframe. Root cause in the frontend: 63D-43 changed the canvas element ID
from `desktop` to `canvas` to fix the missing SDL3 target, but the HTML CSS
continued to style `#desktop`; there was no responsive fit or centering for
the actual `#canvas`.

63D-44 adds an independent source-only viewport fitter. It observes only the
canvas backing-resolution attributes and the iframe's viewport, computes one
uniform scale (min(width ratio, height ratio)), centers the result and preserves
aspect ratio on browser resizing. SDL3's Emscripten pointer event path scales
CSS target coordinates into its SDL window coordinates; this must be verified
physically for mouse/drag/scroll after deployment. The fitter writes **only
CSS custom presentation properties**; it never changes canvas bitmap
resolution, RDP PDUs, TLS pinning, authenticated WSS transport, or FreeRDP
WASM artifacts. It ignores SDL3's transient 1x1 initialization framebuffer.

Acceptance: maximize remote pixels within the iframe without aspect distortion,
correct pointer alignment across scaled canvas, keyboard, 6-minute watchdog,
and measured latency. RDP-native dynamic resolution and higher sharpness would
be a later separate change, not assumed or faked by this CSS-only fix.
Keep all related PRs draft and release 1249 blocked until physical acceptance.


## 63D-45 — Slow physical mouse despite visible GNOME desktop

The 63D-44 physical pilot now renders real GNOME desktop pixels, but the
operator reports **very slow mouse behavior**. This remains a BLOCKER for
release 1249. The original root cause is not yet established and the image,
keyboard, pointer responsiveness and end-to-end latency are separate acceptance
checks.

The browser diagnostic adapter was previously calling its progress callback
on **every incoming/outgoing WebSocket binary packet** even though the UI
limited status rendering to once every three seconds. 63D-45 coalesces that
reporting to at most one callback per second while still counting **every byte
and frame** exactly. Mouse packets and browser/agent/server protocol payloads
are never dropped, modified or reordered.

The same-origin disposable iframe passively observes pointermove event
arrival delay (performance.now minus DOM event.timeStamp), maximum browser
WebSocket bufferedAmount and maximum one-second timer slip. These four
integer fields are sent to the parent at the existing bounded status cadence,
with no coordinates, keys, credential fields, session IDs, RDP payloads or
packet samples. They are explicitly **NOT input-to-visible-frame latency**.
No persistent storage, database or additional Render infrastructure is used.

Interpretation for ONE bounded physical check:
- High browser event delay / timer slip => investigate browser main-thread
  contention and SDL3 framebuffer updates.
- High WebSocket bufferedAmount => investigate outbound queue and network
  backpressure.
- Small values on both do NOT prove the mouse is fast: latency may still be
  server/remote-cursor rendering or downstream RDP processing.

Do not introduce speculative `-mouse-motion`, codec changes or parallel
RDP input channels until actual behavior is measured. FreeRDP/SDL3 upstream
also reports input lag in graphics-heavy sessions, so changing a network flag
without evidence is not an accepted fix. Keep PR draft, retain immutable
release 1248, six-minute GNOME firewall/watchdog and ten-minute agent rollback.
