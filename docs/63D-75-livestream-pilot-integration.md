# 63D-75 — combined continuous Livestream pilot

Baseline: main 9231d499fde054034610a8fb1e5bad29beeb5d9a, PR #422 merged with CI and single-node smoke green. Viborg1 media-format proof passed under GStreamer 1.28.2 (six independent fragments, ten decoded frames each, parallel one-second HLS). That proof did not test WSS/MSE.

## Candidate configuration and safety
- Temporary server-side pilot gate: CLIENTFLOW_LIVESTREAM_WSS_PILOT_CLIENT_ID, absent or invalid means routes are unregistered. Only an approved explicit pilot client can be enabled. Set to 3 only after the review gates, not a permanent per-fleet-client variable.
- Client opt-in: existing /etc/clientflow/livestream.json schema 1, continuous_wss true and segment_seconds 1. Preserve all other fields. No automatic overwrite of existing explicit two-second profiles; migration and signed packaging must be audited before permanent defaults.
- Existing authenticated human heartbeat advertises pilot availability and generation. Both existing desktop views use the shared controller. Mobile retains existing native/HLS lifecycle during the pilot.
- Publisher's connection stays idle without authenticated subscription demand. It sends no media until media:on; last subscriber leaving closes the publishing epoch and clears retained media. HLS independently remains available. No additional video encoding, no new database migration.
- Browser tickets expire in 30 seconds, are one-use and bound to client, generation, user session, viewer and exact Origin. No ticket in URLs. Admission, latest media limits and periodic rechecks remain separate from RDP.
- The WSS display only reports transport when actual playback progresses. Its local buffered-edge distance is not a comparable capture-to-screen delay; leave the delay indicator neutral until a valid measurement exists. Existing HLS delay presentation and user-approved layout are unchanged.
- HLS fallback on WSS failures and bounded WSS retry after an authenticated publisher-availability probe. One active player; visibility retains only latest independent fragment and resets to a fresh decoder point.

## Gates
- Actual isolated database authorization tests, ASGI transport tests, Node contracts, real Chromium MSE synthetic-video proof, full CI and single-node smoke. Synthetic video delivery proves browser decoding, not TLS socket operation or physical desktop capture.
- Review transport-level Uvicorn queue/message constraints without affecting RDP/terminal, package/config install defaults, runtime fault isolation and publisher token refresh. No changes to shared WebSocket server settings in this candidate.
- Before enabling test client: signed package/overlay verification, backend and frontend same approved commit, exact client identity, explicit opt-in, rollback procedure.
- Physical acceptance: simultaneous RDP, 5/20s tab switches, 5-minute uninterrupted visible playback, actual transport label, WSS forced failure and HLS fallback/recovery, resource and latency measurement, explicit stop, mobile rule. Release 1249 is not approved by CI alone.
