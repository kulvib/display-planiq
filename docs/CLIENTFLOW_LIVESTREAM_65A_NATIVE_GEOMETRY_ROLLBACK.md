# PlanIQ Display – phase 65A: remove unproven HLS geometry override

## Source authority and verified merges

Single source of truth: `display-planiq-main(20261025-142755).zip`, matching merged PR #320 commit `8928ab435c43ded6b6fcac1bd93f1cd7ecda1932`. PR #319 and #320 are merged. **63A dynamic geometry and previously suggested 64A rollback are not in this main ZIP** and must not be stacked or uploaded.

## Evidence and scope

Heidi1 is still running installed ClientFlow 1.3.40. Its observed HLS failure occurred before source PR #320 and therefore is **not attributed** to the new 1280×720 preview caps. The local process created a GNOME/Mutter PipeWire node, a downstream active link, but **no local index.m3u8 and no HLS segments**, repeatedly timing out after 25 seconds. The backend's read-only `/api/hls-cap/{client_id}/health` returns `Manifest ikke fundet` when its server-side manifest is absent. This is a symptom, not a WebSocket error: Livestream carries HLS media over HTTPS.

PR #320 added a fixed 1280×720 letterboxed output without device acceptance, changing portrait/ultrawide preview format. Phase 65A **removes only** the unverified width/height cap and `videoscale` dependency; it retains all 62A safe read-only buffer progress probes on pipewiresrc/x264enc/mpegtsmux, 15-second UI warning, Opdater chip, and Remote Desktop WSS/HTTPS transport improvements. No external protocol, codec, HLS manifest path, token/role scope, segment generation, session state, database schema or release authorization is changed.

## Not yet fixed / required gates

- This *does not fix* the pre-existing HLS startup failure on Heidi1. The new source/encoded/muxed frame counters in PR #320 have **not been physically tested on Heidi1**. Determine whether capture buffers reach GStreamer before claiming a fix. Do not weaken the producer's 25-second startup safeguard or force new stream protocols.
- Remote Desktop's client HTTP 502 during token fetch and WSS HTTP 500 can be transient/proxy/backend issues; PR #320 improves fallback and isolated SQLAlchemy 503 but does not prove the upstream fault resolved. Read-only Render error trace and physical pilot still required.
- Tests validate GStreamer pipeline string and Python runtime behavior without a real Ubuntu 26.04 Wayland screen; CI, source freeze, release rebuild, signature provisioning and explicitly authorized physical acceptance are separate gates.
- Do not operate on live Heidi1, reboot/stop systemd or modify networking while remote terminal is the only available access. No production or published ClientFlow release changes in this branch.
