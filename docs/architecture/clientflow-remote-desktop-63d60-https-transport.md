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

## 63D-61C — experimental endpoint adapters

Added isolated browser and agent binary peers using the same framing and
sequence contract. Both require explicit approval and exact client 3. They
accept an injected authenticated, bounded, no-retry request function; no
credentials are persisted, no RDP bytes replayed after errors, and peer
closure requests are best-effort with server supervision as backstop.
Browser adapter exposes WebSocket-like events and bounded upload buffering;
agent adapter exposes async iteration/send/context-manager. Tests cover
canonical framing, ordered traffic and rejection without replay. Neither is
wired into the running FreeRDP or agent forwarder. Remaining integration:
parent-owned browser request channel with exact origin/source/generation,
CORS and same-origin poll behavior, bounded no-redirect TLS HTTP client,
actual mixed transport tests, explicit allowed-network policy and physical
validation. No automatic transport selection is implemented yet. Do not
activate the experimental HTTP router before these gates. WSS is unchanged.

## 63D-61D — explicitly approved end-to-end transport wiring

The router is registered only when CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED=true
on the backend. Frontend VITE_NATIVE_RDP_TRANSPORT=https additionally requires
VITE_NATIVE_BINARY_HTTPS_ENABLED=true; otherwise WSS remains the default.
On the physical agent CLIENTFLOW_NATIVE_RDP_TRANSPORT=https additionally
requires CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED=true in the root-controlled
service environment. Each binary hop may select independently. These are
pilot deployment controls, not end-user switches or production defaults.
No automatic downgrade on ambiguous WSS errors, TLS errors or auth denials.
Selection from explicit approved configuration happens before data transfer,
with a fresh generation. A network-specific automatic selection mechanism
would require an independently trusted policy signal, not browser error text.
The frontend parent uses bearer-only bounded no-retry binary requests and an
exact single-generation MessagePort to the WASM iframe. The agent uses TLS
with hostname verification and a bounded no-redirect HTTP request adapter;
its blocking requests run in threads and require timeout/load validation.
The original WSS path remains direct. JSON control uses the existing HTTPS
relay for the approved browser mode; the existing agent control fallback is
unchanged. Added binding of the HTTP control relay ticket to its owner.
The HTTP boundary still performs auth reads per request; measure the cost.
ASGI send completion is not proof that a remote HTTP client received bytes;
sequence and independent supervision remain the fail-closed backstop.
No deployment flags set, no pilot installer updated yet, no physical proof.
