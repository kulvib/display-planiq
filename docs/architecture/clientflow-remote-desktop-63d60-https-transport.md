# 63D-60 — Optional binary HTTPS transport

Design only. WSS remains default. HTTPS must be explicitly approved by IT and
disabled otherwise. Never retry authorization, certificate or policy denials
through another transport. No public RDP port, JPEG, or paid service.

Existing JSON HTTPS relay can discard obsolete JPEG frames and cannot carry
the native byte stream unchanged. Browser control and both binary hops need
independent approved transport selection; agent control/files already have
JSON fallback. Reuse exact native tunnel authority, physical guard and leases.
New generation and ticket on switching; never replay ambiguous bytes.
Prototype binary application/octet-stream batches with explicit sequence and
acknowledgement, one reader/writer per direction, bounded memory, liveness and
cleanup. Proposed initial limits: 64 KiB frame, 256 KiB batch, 2 MiB queue,
20 s poll. Validate actual Render/proxy behavior before selecting transport.
Require same user/login/client/credential/generation, origin and CSRF checks,
no per-packet database writes, revocation and idle closure. Test ordered bytes,
capacity, concurrency, stale generations, replay, all mixed WSS/HTTPS paths,
controlled upgrade rejection on approved networks, real WASM, and physical
Viborg1 latency, CPU, request rate and memory. No release capability claim yet.

## Terminal warning
Both terminal modes use a server-owned 600-second inactivity limit from
authorized PTY creation, reset by accepted input/script or explicit continue.
Output, resize and keepalive do not reset it. Existing standard/root absolute
limits and root-grant expiry remain unchanged; warn at the earlier deadline.
A hard-limit warning cannot extend the grant. Close the PTY and browser
session at expiry; require an explicit new connection. Existing step-up is
still enforced. Terminal/Remote Desktop countdowns share the same visual
language. Physical testing is required, including active support scripts.
