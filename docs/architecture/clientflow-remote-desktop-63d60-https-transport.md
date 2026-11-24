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

## 63D-61A — isolated executable binary peer

The experimental core has no HTTP routes and cannot be selected by any client.
It uses length-prefixed raw binary frames (4-byte big-endian length), bounded
batch size/count, sequential upload acknowledgements and download sequences,
no replay, strict one-poll concurrency, fail-closed queue limits, shared
32 MiB framed-payload budget and independent 45-second contact supervision.
Empty polls do not advance a sequence. Ambiguous deliveries close a generation.
The queue budget does not include Python object overhead or concurrent HTTP
bodies; the HTTP integration must independently bound those, enforce one writer
before streaming body consumption, and close on abandoned response delivery.
Tests exercise byte ordering, replay/gap rejection, simultaneous polls,
capacity, cancellation, independent cleanup and the existing native pump.
No change to WSS, WASM, client binaries or production authorization. Still
required: authenticated HTTP endpoints, strict body/read limits, browser and
agent adapters, explicit IT policy and controlled proxy + physical proofs.

## 63D-61B — isolated authenticated HTTP boundary

The separate experimental router is intentionally not included in the app.
It also requires an explicit opt-in environment flag and client 3. The browser
open requires existing platform authentication, an allowed explicit origin,
current managed session and a fresh one-time ticket consumed by the unchanged
native tunnel handler. Agent open uses the current domain credential and exact
native tunnel/control generation. The same owner, session, managed request
and control channel are rechecked for every data request; a foreign owner
cannot manipulate another peer. Strict byte body and sequence limits, one
upload and poll lane through ASGI response delivery, maximum 16 peers, and
independent supervision bound the prototype. Authentication reads per request
must be measured before enabling; no media or renewal writes are added here.
No browser/agent adapter, CORS integration, live endpoint, or transport switch
yet. Tests cover the boundary primitives and fail-closed response handling,
not a real HTTP/FreeRDP handshake or physical firewall test.
