# 68J-9 – realtime security and recovery (2026-11-27)

Baseline: main f7d096df5b036e88cc36ff473b3e68863e6f90b5; merged PR 442, all three workflows green, exact pinned WASM fast path verified. Installed pilot remains 1.4.0/1250; 1251 remains unbuilt and unauthorized.

## Findings and changes

- Browser realtime capabilities previously survived a process restart while their generation counters reset. Bind newly issued capabilities to a random process epoch; the existing 401/reissue and authoritative snapshot flow repairs the subscription after redeploy. Bound wait to the signed expiry and recheck expiry before returning. No additional DB checkout, new setting or wire change for callers.
- Display/System agent wake-only sockets previously verified their signed token at admission but not before subsequent wake replies. Recheck cryptographically after every bounded wait and close with 4401 when invalid; HTTP long-poll also checks before and after the wait. No durable command authority or DB revocation policy is changed. Revocation of the wake-only capability remains bounded by its signed lifetime; immediate DB revocation of command operations remains unchanged.
- Livestream's existing 15-second database recheck was in an elif branch that could be starved by continuous generation advances. Check the deadline before sending any wake, retain the existing cadence; do not introduce new polling or DB work on every event.
- Expected peer disconnects during wake WebSocket accept or first response are handled by the same boundary as subsequent sends. OSError/disconnect/runtime closure is treated as transport termination. Cancellation is not swallowed.
- Add executable negative regression tests for expiry during wait, previous process capabilities, wrong client/domain, sustained wake traffic, handshake disconnect and the existing Control Room role matrix. Viewer is intentionally global read-only under current policy, not silently changed to org-scoped. This matrix tests selected authorization helpers, not every HTTP endpoint.

## Render evidence

Read-only request logs, 2026-11-27 13:30–14:35 UTC (14:30–15:35 Danish time), two pages exhausted: 105 HTTP 502 and five HTTP 500. The latter were System wake WebSocket (2), Livestream wake WebSocket (1), Terminal agent WebSocket (1), Remote Desktop files WebSocket (1). No application error logs returned with the error-level filter. These changes address verified source defects, not a proven root cause of all five 500 responses. Terminal/Remote Desktop file transport and actual media remain untouched pending an identified cause. Single-node deployment interruption remains expected; no zero-downtime claim.

## Acceptance

- CI including existing DB query budgets, async waiter scale and release security contracts, new regressions and full frontend contracts.
- After merge and green main, backend redeploy; no migrations or new variables. Physical Viborg1: online, kiosk, control commands, browser state resync, Livestream recovery, simultaneous Remote Desktop, Terminal/files; verify normal operation past token renewal if practicable and review sanitized Render logs.
- No changes to client runtime, canonical artifact authorization, stable catalog, fleet/fresh-install holds, credentials, Render configuration or database schema. New UI realtime token is reissued through existing authenticated capability endpoint. Off-host backup/restore, full endpoint-level authorization matrix, mobile/accessibility, fleet/media load and 1251 approval remain open.
