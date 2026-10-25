# PlanIQ Display · livestream and Remote Desktop hardening, phase 62A

## Base and safety boundary

Single source of truth: `display-planiq-main(20261025-104357).zip`, matching merged main PR #319 / `a03f94e1a461` (2026-10-25). This changes-only branch also incorporates the **unmerged** prior 15-second startup warning, Driftsfejl refresh chip, and Remote Desktop keyboard-initialization isolation. Nothing is changed in the live Heidi1 installation by merging source code: client changes require a separately verified, approved, immutable ClientFlow release and physical acceptance. No release catalog promotion, Ed25519 trust/key activation, database migration, credential rotation or change to auth scopes.

## Grounded diagnostics

On Heidi1, local Wayland session was active; Mutter/gnome-shell PipeWire node 63 and a downstream link to node 66 were `active` throughout the startup attempt. GStreamer created no HLS playlist or TS files, producer retried after 25s. Thus the PipeWire connection exists, but presence of encoded frames has **not** been proven. Full native resolution at 10 fps / 12,000 kbit/s was software-encoded with high observed CPU; this release bounds encoded preview output to **1280x720 with letterboxing**, retaining configured FPS, bitrate, and the established source/segment paths. An admin preview is not a native-resolution remote desktop. The x264 zerolatency mode and stream isolation remain in effect.

The standalone capture child now counts pipeline buffers at source (PipeWire), H.264 encoder output and MPEG-TS mux output using read-only GstPad probes. It prints bounded `clientflow_hls_progress` lines **only while waiting for the first segment**, a one-off `clientflow_hls_first_segment` and an exit summary. Counts contain neither images nor credentials; logs remain client-local. Producer's 25s protective readiness deadline remains unchanged: the UI's 15s warning is **not** a stream termination condition. Segment creation remains a precondition for marking streaming `running`.

Remote Desktop's log showed both authentication token HTTP 502 and WebSocket handshake HTTP 500 followed by a systemd process exit. `InvalidStatusCode` is a `WebSocketException` and was **not** caught by the earlier `ConnectionClosed`/`RuntimeError` handler. WebSocket protocol/handshake failures are now caught and use existing HTTPS fallback and bounded retry. Token-fetch errors are handled **separately**, to prevent an immediate duplicate token attempt through HTTPS fallback; all HTTP status codes and credential checks remain fail-closed. SQLAlchemy outages in the token endpoint map to a sanitized, retryable 503 (not a false invalid-credential 401) without logging secrets or query parameters. An upstream/proxy HTTP 502 is **not** proved fixed by that change; additional Render-side diagnosis may still be necessary.

## Acceptance gates

- Local unit/contract tests exercise aspect-preserving preview pipeline, stage progress, 500 handshake fallback, 502 token failure without duplicate fallback, 503 backend DB outage semantics, and RD capture without mandatory keyboard init.
- Existing frontend source tests cover immediate preview start, **15 seconds** to UI warning (no producer cancellation), and clickable **Opdater** chip.
- GitHub full CI + Ubuntu 26.04 client executable proof per change scope + single-node smoke are required; local PyGObject/GStreamer isn't available for a real device capture test. Tests may not be weakened.
- Separate Render deploy/smoke test, then physically attended Heidi1 pilot: first HLS segment and video within target latency, Remote Desktop control/files, 502/500 transient recovery, diagnostic counters, session isolation, CPU/bandwidth, screen aspect ratio, and no regression in kiosk or terminal access.
- Do not perform disruptive network, graphical-session or systemd changes on Heidi1 while connected only through its remote terminal.
