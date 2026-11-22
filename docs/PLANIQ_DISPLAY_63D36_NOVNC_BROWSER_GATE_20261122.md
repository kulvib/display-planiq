# PlanIQ Display · 63D-36 · Locked noVNC browser viewer gate

Date: 2026-11-22. Draft PR #407; source-disabled, no rollout.

## Delivered (source only)

1. Dependency: npm `@novnc/novnc@1.7.0`, MPL-2.0,
   registry tarball version and **SHA512 integrity** in both
   `frontend/package.json` and `frontend/package-lock.json`.
   Independently cross-checked against existing public npm lockfiles.
   `npm ci` must independently validate the actual tarball on CI.
   **No third-party CDN at runtime.** Dynamic import keeps it out of
   the main UI entry and does not add services or a database.
2. `frontend/src/api/api.js`: session-bound native browser WSS URL;
   HTTPS-long-poll open/send/poll/close through the existing authenticated
   `apiFetch` (same session-refresh/error logic as the legacy viewer).
   HTTPS fallback obtains a **fresh, single-use remote_desktop WS ticket**
   instead of replaying an already consumed WSS ticket.
3. `NativeRfbViewer.jsx`: the real React noVNC RFB(target, rawChannel)
   component inside the existing PlanIQ Display page. Uses the bounded
   `nativeRfbSocket.mjs` from Fase 63D-35, WebSocket→HTTPS fallback,
   explicit client/session, no public port or separate desktop app.
   Lazy import, teardown on lost session/unmount, keyboard/mouse/canvas
   confined to the viewer. No credentials in URLs or browser storage.
4. `RemoteDesktop.jsx` mounts this viewer only behind
   `NATIVE_RFB_PILOT_ENABLED = false` **hardcoded source flag**;
   existing production JPEG controls and file transfer remain intact.
   Backend independent source flag `PILOT_ENABLED = False` also remains.
5. Source/lock/negative tests ensure pinned package and login+teardown
   contracts remain. No actual GNOME RDP/x11vnc startup or broker.
6. This code does not alter Render Docker (embedded PostgreSQL),
   existing client release 1248, external ports, budget or main.

## Important unresolved physical and security gates

- noVNC RFB receives **RFB bytes**, not native RDP; the planned extra
  GNOME Desktop Sharing → approved FreeRDP/Xvfb → protected x11vnc/RFB
  hop is not yet installed. The existing root RDP pilot cannot become
  a persistent unattended service as-is.
- **x11vnc security STOP**: Ubuntu 26.04 package CVE-2026-32853 status
  was Needs evaluation when checked. Package must not be installed until
  exact build+library CVE, secure isolated socket and ephemeral auth
  reviewed. Legacy eight-character VNC-password is insufficient.
- Binary flow control must be tested with an actual RFB producer, as
  well as physical browser keyboard, mouse release, frame p50/p95, proxy
  timeout, WebSocket blocked→HTTPS and fail-closed cleanup.
- The old JPEG runtime must be stopped when switching to native
  (otherwise double capture, double keyboard and bandwidth costs).
  The source flags above must **not** be casually flipped.
- Live HLS upload / manifests / playback ≥90s also remain a
  separate physical release gate. Last physical ClientFlow is 1248.
- Verify noVNC package vulnerability scanning and JS chunk budget
  in CI on the **exact SHA** before this draft advances.

## Acceptance

GitHub full CI and Display single-node PostgreSQL smoke PASS on the
same exact commit are necessary, not sufficient. Do not merge/deploy
or enable any flags until the physical, isolated, measured and
root-rollback-reviewed browser pilot is accepted.
