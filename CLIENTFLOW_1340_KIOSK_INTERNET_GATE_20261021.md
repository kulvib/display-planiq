# ClientFlow 1.3.40 – offline-safe kiosk browser (2026-10-21)

Source: the freshly supplied `display-planiq-main(20261021-164354).zip`, GitHub main `d122c198a36701f0549f3bd28b85179eab5b6e91` (PR #303). This is a **source-stage change**; it is not a published client bundle and must be re-frozen before release 1.3.40 / sequence 1241.

## Behavior

- The Display Runtime alone controls the canonical Chrome kiosk process. Its separate asynchronous HTTPS monitor probes the PlanIQ backend `/health` endpoint (no database calls), then falls back to the *origin* of the configured HTTPS kiosk URL. HTTPS certificate validation and DNS resolution are required. Redirects are not followed, HTTP is not accepted as internet proof, and the kiosk URL's path/query/credentials are never sent in a probe.
- At boot, Chrome remains closed until successful independent checks span at least 10 seconds. While offline, explicit Start/configuration/calendar start requests are **remembered** but cannot launch Chrome.
- The monitor samples at 10-second intervals. A brief failure leaves Chrome running. A confirmed 20-second outage from the first failed probe closes Chrome without deleting its profile or cookies. The runtime retains `browser_requested` for automatic recovery, subject to an explicit calendar/manual stop.
- The last two successful probes (minimum 10 seconds apart) allow automatic recovery. Active Ethernet/WiFi switching does not close Chrome if the checked HTTPS routes remain reachable.
- `waiting_internet` and `internet_access` are published in the existing runtime status. Local GUI and backend operator projections use “Kiosk browser afventer internetforbindelse…”. The local GUI can explicitly Stop even while waiting, preventing later restart.
- Display-readiness treats a **fresh**, unspawned `waiting_internet` state as a *healthy runtime waiting for a prerequisite*, but still requires the authenticated local kiosk Wayland session and live local GUI. This prevents a systemd restart loop while offline; it never calls a stopped browser healthy/running. A waiting status is periodically refreshed.
- A manual calendar/GUI/backend stop always clears `browser_requested`. Internet transitions preserve the stop event/source in the status. Browser Guard, client GUI and System agents are not suspended.

## Test and operational gates

- Python integration/security tests cover no launch offline, never launching on Start, no offline countdown, loss grace, stable recovery, WiFi-to-Ethernet handover, HTTP restriction and token-free HTTPS fallback, stale-readiness rejection, local-GUI authority, profile/cookie survival, and preserved manual/calendar stops.
- The existing browser/consent/countdown tests explicitly provide an online mock: they are **not removed or weakened**.
- Physical acceptance requires a **sacrificial clean 1.3.40 test client**, or a supervised maintenance window. Never sever the remote admin path on Heidi1 to simulate a network outage. Test offline boot, actual DNS/HTTPS failure, Ethernet-to-WiFi handover, Calendar OFF, manual stop while offline, restored internet and GUI status. Keep System, local GUI and offline rescue available.
- This release source change requires new GitHub `main` commit, all CI gates green for exactly that commit, new source-freeze, runtime-input transport, two independent reproducible builds, explicit approval, and a controlled 1.3.38→1.3.40 controller-bridge pilot. No deployment, release catalog promotion or physical host mutation is part of this package.

## Probe limitations and costs

“Internet available” here is *validated HTTPS reachability* to at least one known external destination, not a guarantee that **every** page or third-party service is reachable. A corporate firewall denying both approved HTTPS destinations will safely keep Chrome closed. The backend `/health` is database-free; its low-cost endpoint avoids extra Neon queries. Monitoring is performed off the Display control event loop with short timeouts and non-overlapping requests.
