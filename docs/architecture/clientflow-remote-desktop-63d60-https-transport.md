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

## 63D-62A — CI repair, mixed transport test and pilot packaging

Repin the pilot to the integrated 63D-61D commit, staging four runtime
modules; the 20-minute rollback is unchanged and recognizes either exact
root-owned service override. install defaults to WSS, install-https selects
HTTPS for an approved physical pilot. The CORS assertion verifies the exact
new header contract. Parent-to-iframe delivery has an outstanding FIFO cap
of 2 MiB/512 frames with ordered acknowledgements after the child callback.
This does not bound internal decoder/OS buffers. The new matrix exercises
native handlers and actual HTTP routes via ASGI for four combinations,
byte integrity, origin rejection and revoked/idle authority. Identity and
DB checks are stubbed. No real sockets, TLS, firewall, Render or GNOME proof.
CI, controlled proxy and FreeRDP executable proof, physical idle/Terminal
checks, load and latency measurements and permanent lifecycle review remain
required. No deployment or physical state changes.

## 63D-62B — dependency-free matrix and loopback TLS regression

The matrix now drives the actual ASGI app without httpx or skipped cases.
The separate real loopback TLS server test checks the actual agent HTTP
request adapter: raw binary GET/POST, bounded response reads, redirect
refusal and certificate hostname mismatch. Local automated proof only;
no real municipal proxy, Render throughput or physical FreeRDP/GNOME proof.
Deployment remains disabled pending CI.

## 63D-65 — agent HTTPS throughput and validation cost

Physical WSS passed 20/20; Terminal 9/9; mixed WSS/HTTPS 10/10 functional
but significantly slower. Render observed 1003 HTTP 200/204 responses in
one minute, CPU up to 0.252 vCPU and memory 139–156 MB across the service.
The direct agent uses persistent HTTP/1.1 TLS lanes, separate upload, poll
and teardown; respects the configured HTTPS proxy via the original urllib
path (no pooling in that path). No retry on ambiguous delivery. The bounded
read-ahead uploader batches already available 16 KiB blocks, max 15 frames
per batch, one upload in flight. First block has no intentional delay.
Each HTTP operation still checks the exact bearer owner against the DB.
Before reading or waiting, check identity/generation/idle/expiry in memory;
perform full authorization before accepting/delivering data. No auth cache.
The native periodic watchdog and independent contact expiry remain unchanged.
No new dependencies, no WSS algorithm change. Logs report only request,
connection, error counts and cumulative response duration. Keep-alive is
subject to the actual proxy/server. Blocking workers are not force-cancelled;
retired lanes cannot be reused and socket timeouts/cleanup remain necessary.
CI and repeat physical measurement are required before approving performance.

### 63D-65B

The transport matrix records the actual next download sequence independently
for each HTTPS peer. Revocation is tested at that sequence and must return
403 with the authorization detail, without delivering queued ciphertext.
The persistent and proxy HTTP adapters reject a response whose advertised
length exceeds the actual bytes received; a syntactically valid prefix of
an interrupted binary response is not sufficient to accept delivery.
The real TLS regression includes a deliberately truncated response.


## 63D-67–70 — release-readiness entry gate (2026-11-25)

Immutable physical pilot candidate: `10036e0f3b157fb97789584873424c1240a5ab0e`.
All four workflows passed. Operator confirmed 9/9 physical HTTPS checks on
Viborg1 ID 3, 11:22–11:25 CET: markedly faster than prior HTTPS, slightly
slower than WSS. Render service-wide minute sample: 1591 HTTP 200/204,
0.2564858 vCPU maximum observed, 147–152 MB after startup. Prior: 1003,
0.252 vCPU, 139–156 MB. The deployment overlaps this window; workload and
active duration were not controlled, and counts include other API requests.
No cost saving or fleet concurrency has been proved.

The release builder already packages pinned root helpers and permanent
lifecycle/sealer units. Do not remove the independent physical firewall,
boot/expiry guard or rollback protections. The remaining pilot-specific
client ID and hostname checks span backend tunnel/admission, browser,
agent, root helper, lifecycle and proof; replacing a single hard-coded
value would not establish an authorized fleet policy. Keep Viborg1-only
admission until the entire chain is reviewed. WSS is default, HTTPS
explicit opt-in; no automatic downgrade on authentication/TLS errors.
The 16-peer limit and 32 MiB framed queue budget are not proof of
100 simultaneous remote desktops. Idle fleet size and concurrent support
sessions are distinct metrics.

Add bounded per-peer HTTPS counters to the HTTP boundary: accepted upload
batches and framed bytes, empty/nonempty polls and prepared download bytes,
observed ASGI response errors. One content-free summary per retired peer,
no identifiers or credentials, no DB calls, no new dependency. Prepared
responses are not proof of remote receipt. A response error racing peer
retirement can occur after the summary, so the observed error count is
not an exhaustive network loss metric. Keep full authorization before
acceptance/delivery; no auth caching or transport behavior change.

Next release gate: compare matched stable WSS/mixed HTTPS runs using
agent request/connection counters, server summary and Render metrics;
review root lifecycle and signed per-client policy as a single security
boundary; verify release source integrity, install/upgrade/rollback and
100-idle-client load separately from bounded active-session load.
No new release approval, catalog update, deployment, or fleet enablement
from this change. No automatic deletion of historical pilot tools.


### 63D-67D / 68A — physical matrix and transport chip

Operator passed all four physical binary transport combinations on Viborg1,
including browser HTTPS/agent WSS and browser HTTPS/agent HTTPS on
`1b70b5cf0971835a8ce3b85dab83e80711ca69aa`. Render request logs confirm
both relevant HTTPS route families. Service-wide peak minute samples:
395, 1591, 2984 HTTP 200/204 for scenarios 2/3/4 respectively; CPU maxima
0.080, 0.256, 0.468 vCPU (limit 0.5). Nonmatched workload; deployment
overlap in earlier scenarios; session summaries not found. No cost or fleet
capacity conclusion. Physical matrix is closed for the tested candidate,
not a real restrictive network or canonical release approval.

Expose a neutral read-only chip below client availability. The existing
authenticated control channel reports the two attached binary peers, based
on the server-created HTTP adapter rather than browser claims or environment
settings. Emit only ready/closed events for the exact tunnel generation,
with bounded best-effort delivery and no additional database reads or
polling. The chip is hidden without a matching active control session or
when the operator disconnects. A missing status event leaves it absent.
This is binary tunnel attachment, not proof of pixel rendering, nor the
transport of unrelated JSON control/file/terminal channels. CI matrix and
physical UI verification remain required. No fleet gate change.
