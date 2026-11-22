# 63D-34 · Secure native RDP relay adapter (source disabled)

This phase adds a genuine, but **off-by-default**, browser↔backend↔agent
authenticated opaque-RDP relay inside the EXISTING PlanIQ Display Render
Docker service, with existing local PostgreSQL and no extra services.

## Grounded reference
Physical GNOME Desktop Sharing / FreeRDP on nonproduction Viborg1, 22 Nov 2026:
five real input ACKs and five observed X11 pixel changes, 120.7ms local
input→visible sampled pixel p50. This does not prove browser latency.
GH draft PR #404 preserved and copied on current main via draft PR #407.

## New code — no production activation

- `backend/service1/routers/native_rdp_pilot.py`: separate native browser
  and agent WSS lanes; optional HTTPS long-poll relay on existing
  /api in-process HTTP relay; **PILOT_ENABLED = False** hardcoded.
- Browser WSS requires existing superadmin websocket ticket and the
  **same authenticated, live Remote Desktop browser session and login binding**;
  both roles recheck authorization at most 15-second intervals while active.
- Agent authenticates using the EXISTING isolated Remote Desktop credential
  + 15-second version/revocation recheck, not a new general client key.
- One native session per client at a time; session-specific stream UUID and
  directional ACK/sequence/8-chunk credit windows; no packet replacement, no
  JPEG interleaving; six-minute maximum lifetime. Agent replacement or
  browser logout must revoke the native generation.
- Each native chunk <=16KiB and JSON envelope <=24K characters. No RDP
  credentials or RDP screen data are persisted or logged. Ordinary HTTPS
  fallback uses scoped ephemeral in-process relay and rechecks browser or
  agent authorization per request. Tickets are not included in URL.
- The existing old JPEG viewer and input/file channels stay **untouched**.

## HARD STOP before enabling

1. This branch has no trusted GNOME RDP startup supervisor on the kiosk.
   Do not call the old physical test scripts as always-on runtime.
2. There is no packaged browser-compatible RDP WASM decoder yet and
   therefore NO functional desktop picture in the native viewer. The agent
   runtime also does NOT open an authenticated loopback native connection.
3. IronRDP/WASM is a candidate, NOT accepted; pin provenance, license,
   vulnerability scan and GNOME50-compatible RDCleanPath/TLS handshake
   before bundling. Browser must see real pixels, not protocol mock frames.
4. Test HTTPS fallback under an actually WSS-blocked network, reload,
   key/button releases, revocation, queue overflow, and root watchdog
   rollback physically on Viborg1. No public 3389, no headless/remote-login.
5. No merge, no Render deployment, no ClientFlow package/release and no
   change to production database. Source-level HLS +1 media sequence
   correction still awaits a release after full native browser and HLS
   acceptance.

## Gate
Run GitHub CI (backend, frontend, Ubuntu 26.04, source integrity) and
Display single-node PostgreSQL smoke against the **exact** candidate SHA.
Synthetic negative tests intentionally have NO access to actual RDP,
screenshots, permissions or client hardware.
