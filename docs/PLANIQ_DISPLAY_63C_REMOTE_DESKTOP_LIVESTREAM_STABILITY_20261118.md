# PlanIQ Display · 63C · Remote Desktop + Livestream stability/performance

Basis: fresh `main` archive `display-planiq-main(20261118-093113).zip`.
This is a **source patch**, not a ClientFlow release or verified production fix.

## Evidence behind this change

Viborg1 ClientFlow 1.3.43: 720 captures, 90 frames sent, mean capture 19.632 ms, mean input-to-forwarded-frame 985.642 ms, 59,534,346 JPEG bytes (approx. 661 KB per sent frame). Browser and agent both used HTTPS long-polling after unstable WebSockets. Render CPU/RAM were low. Separately, both GNOME Mutter/PipeWire consumers intermittently received no frames, with Livestream zero-buffer retries. These are different failure modes until proven otherwise.

## Scoped changes

- Remote Desktop browser HTTPS relay now coalesces **only adjacent pending** mouse moves (matching dragging state), never in-flight input, click/up/down, key, text, file commands or stream controls. Failed send still closes transport.
- Backend relay with `scope.kind=rd_browser` removes superseded **outgoing screenshot frames** before queuing the newest screenshot. Lifecycle, errors, input and file messages are preserved FIFO. Bounded queue, byte budget, auth and session scope remain unchanged. Terminal, agent and other relays are not modified.
- Native geometry and coordinates remain authoritative. WSS JPEG quality stays 85. HTTPS fallback JPEG quality changes to 65 to reduce payload size only on the slower transport. Do not assume the compression improvement without measuring it on Viborg1.
- Scroll on the RD image is registered as a native `wheel` listener with `passive:false`, avoiding the React passive listener `preventDefault()` warning.
- The RD agent writes content-free `relay_send_ms_last/avg/max` with the existing 5-second telemetry write cadence. This measures client send completion (including HTTP relay request in fallback), **not browser paint/input round-trip**.
- **No Mutter/PipeWire, GStreamer, Livestream producer, service, credential, deployment or host configuration changes.** Livestream retains isolated capture and bounded retry behavior. Changing shared screen-capture architecture without reproducible isolation evidence would be premature.

## Required gate before merge

1. GitHub CI: full Python and frontend suites, dependency/security audit, checksum tests all green.
2. Confirm WSS and HTTPS behavior. Under artificially slow sends, rapid mouse moves are coalesced, but click, release, drag transition and key order are unchanged.
3. Confirm the browser receives fresh frames after simulated backlog, without old frames delaying control events. Confirm agent and Terminal relays unchanged.
4. Keep Livestream running on the same client while using Remote Desktop. Run separate RD-only, Livestream-only and simultaneous tests for at least 10 minutes, including stop/start and one network interruption.
5. Confirm no lingering capture no-frame loops and no new HTTP 401/403/404/5xx / HLS segment errors. Check complete client and Render logs.
6. Compare baseline (mean input-to-forwarded-frame ~986 ms, max ~2823 ms) against `relay_send_ms_*`, `capture_ms_*`, `input_to_frame_ms_*`, browser paint delay, JPEG byte size and actual mouse/keyboard usability.
7. Until a **new approved ClientFlow release is built and deployed**, client runtime changes in this branch cannot change Viborg1's installed capture agent. No automatic deployment or client upgrade is included.

## Rollback & limitations

Backend/frontend can be reverted by their normal GitHub/Render release procedure if interactive behavior regresses. Client runtime remains unchanged until a separate release gate. The no-frame issue on PipeWire is not proven resolved; do not restart GNOME/PipeWire or combine capture workers as a speculative fix. Keep the existing single Render instance architecture; no new paid infrastructure.
