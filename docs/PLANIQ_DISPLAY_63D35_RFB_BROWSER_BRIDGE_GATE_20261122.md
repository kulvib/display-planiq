# Fase 63D-35 · Browser-side RFB over the accepted GNOME RDP pilot (source disabled)

Date: 2026-11-22. Candidate code only, layered on draft PR #407. No actual
Viborg1 configuration, Run workflow permissions, Render deploy or main merge.

## Why this design instead of direct IronRDP/WASM

- GNOME **Desktop Sharing of Viborg1's existing Wayland kiosk session** and
  authenticated FreeRDP rendering to a temporary Xvfb were physically accepted
  in Fase 63D-32 (5/5 actual clicks and visible pixels, p50 local 120.7 ms).
- Current upstream IronRDP browser WebAssembly mandates a real **binary
  WebSocket + RDCleanPath** proxy handshake with server cert handling. The
  existing safe PlanIQ HTTPS JSON fallback cannot be passed directly into
  IronRDP. A binary bridge would have to implement this protocol or maintain
  a reviewed WASM fork. Do not falsely call the old JSON relay interoperable.
- **Alternative pilot**: GNOME Desktop Sharing -> local approved FreeRDP/Xvfb
  -> tightly restricted on-demand x11vnc/RFB -> authenticated PlanIQ browser
  reverse tunnel over existing Render Docker -> noVNC directly inside the
  existing PlanIQ Display frontend.
- Ubuntu 26.04 ("resolute") has a distro x11vnc package in universe:
  https://packages.ubuntu.com/resolute/x11vnc
- noVNC upstream v1.7.0 RFB(target, urlOrChannel) accepts an **existing
  WebSocket-like raw channel**. Its Websock.attach() consumes binary
  ArrayBuffer messages, so we can adapt the existing JSON WSS + HTTPS fallback
  without a proprietary fork or changing authenticated PlanIQ login:
  https://github.com/novnc/noVNC/blob/master/docs/API.md
- noVNC core license is MPL-2.0; packaging and dependency audit are still
  required before copying/installing it.

## Implemented, SHA-256 pinned in this candidate

1. `frontend/src/pages/clientdetailspage/remotedesktop/nativeRfbSocket.mjs`:
   own-property-compatible noVNC raw channel for existing PlanIQ native
   WSS/HTTPS tunnel (not a separate administrator RDP application).
   Binary -> canonical 16KiB base64 JSON chunks. 8 outstanding ACKs,
   total 256KiB buffer; no silent input drop. Inbound ArrayBuffer only
   delivered after stream ownership and sequence checks, ACK issued after
   callback; wrong generation/duplicate/replay/bad ACK/queue overflow closes.
   Its transport input is deliberately *injected*, not connected automatically.
2. `client/runtime/clientflow_runtime/native_rfb_stream.py`: a fully
   bounded, ordered RFB byte forwarder over a **pre-connected** trusted
   reader/writer supplied by a future root-controlled supervisor. Does
   NOT open TCP, start x11vnc, alter GNOME, read secrets or spawn processes.
   Reverse ACK sequence, credit, timeout, EOF and cancellation close.
3. Negative tests in Node and Python with mock sockets, including binary
   round trip, 16KiB limits, overflow, replay, wrong sessions, close and
   stale generation. No test talks to the physical host.

**Important protocol naming:** Existing draft #407 transport messages are
`native_rdp_*` because their initial design was native-RDP WASM. This
pilot would carry **RFB bytes emitted by the local FreeRDP-derived
desktop**, not raw RDP bytes. Names must be made explicit and versioned
before enabling a live feature. This code is not an approved protocol
migration and cannot yet carry real desktop pixels.

## Mandatory STOP gates before physical pilot

- Need a **supervised, on-demand, restricted local x11vnc and Xvfb runtime**
  with dynamically scoped VNC credentials or protected Unix socket,
  isolated from all non-authorized local accounts. No public 3389/5900,
  no unprotected VNC endpoint even on localhost, no permanent new listener.
  Never reuse temporary credentials/Keyring material from root pilot scripts.
- Determine and test whether x11vnc security mode meets required standard;
  VNC legacy 8-character password / DES authentication **alone is not
  enough** for a long-lived solution. Require equivalent strong isolation,
  ephemeral credentials and minimal privileges.
- Package and audit an exact version+integrity hash of noVNC. No CDN.
  Add the web component only inside the PlanIQ Display Remote Desktop tab,
  behind explicit superadmin authorization and a source-level pilot flag.
- Must verify Fase 63D-29/30 watchdog and full cleanup on failed start,
  unplug, timeout, logout and reboot. Existing 1248 is nonproduction but
  root safety and no-port exposure still bind.
- Compare real browser mouse->visible pixel p50/p95 and visual stutter
  against the existing JPEG browser baseline. The extra FreeRDP->RFB
  encoding step may not be faster. If slower, terminate this pilot path.
- Demonstrate HTTPS fallback with WebSocket Upgrade blocked *physically*,
  keyboard key-up and mouse release after disconnect, correct HLS >=90s
  frontend playback and zero extra paid services.
- Browser pixel path, x11vnc, noVNC dependency and temporary credentials
  are **NOT yet installed/activated**, so these source tests are NOT
  end-to-end acceptance.

No changes to Render Docker/local PostgreSQL, kiosk system, PR #404
physical evidence, or existing JPEG frontend during this candidate.

## Security advisory gate added 22 November 2026

[Ubuntu CVE-2026-32853](https://ubuntu.com/security/CVE-2026-32853)
lists the `x11vnc` package for Ubuntu **26.04 LTS** as
**Needs evaluation**; its underlying `libvncserver` package is listed
as "Not affected", which does not clear the separate x11vnc status.
[USN-9089-1](https://ubuntu.com/security/notices/USN-9089-1)
published 12 November 2026 covered an earlier shared-memory issue
on Ubuntu 20.04 only. These are distinct findings.

STOP on x11vnc activation until the exact Ubuntu 26.04 package build
and relevant CVE/privilege/isolation status are independently checked,
and ephemeral per-session safe authentication/loopback restrictions
are physically accepted. Never install x11vnc solely because the
package is available in the archive.
