# ClientFlow Remote Desktop — Architecture decision gate (63D-48)

**Date:** 2026-11-23 · **Status:** Research-backed provisional decision; physical A/B gate NOT PASSED · **Owner:** PlanIQ Display/ClientFlow · **Scope:** Ubuntu 26.04 GNOME/Wayland kiosks, 100+ registered clients, only the test client Viborg1 (client ID 3, active release 1248).

## Decision

**Keep** GNOME Remote Desktop *desktop sharing of the existing physical kiosk session*, GNOME/Mutter/PipeWire/libei, local-only RDP firewall, outbound-only authenticated connection over HTTPS/WSS 443, PlanIQ identity/RBAC and separate machine identity, on-demand session activation, and strict watchdog/rollback. **Do not yet approve** FreeRDP 3.33.1 SDL3 Emscripten/WASM as ClientFlow's permanent browser client. Test it against Apache Guacamole 1.6 as an alternate browser protocol implementation, using the same physical GNOME source and comparable network route. Consider a properly engineered direct media WebRTC branch only if the two RDP browser implementations fail objective latency/quality gates. Do not migrate the kiosk to Xorg, expose RDP/VNC ports, add Neon or paid services merely to get a test.

The present FreeRDP WebAssembly browser feature was officially introduced in **3.33.0, 2026-11-02**, with 3.33.1 patch **2026-11-10**; it is a promising new capability, not yet operationally proven by our physical tests. Guacamole 1.6 already has an established HTML5 browser client and FreeRDP server-side decoder/Guacamole protocol, plus new RDP GFX support. Neither is guaranteed faster until tested.

## ClientFlow physical evidence (operator supplied)

- GNOME/Mutter current primary physical monitor: **2560x1080 at 60Hz and scale 1.00** via read-only DisplayConfig query; physical mode MUST stay unchanged.
- RDP browser canvas reported a **different resolution**, exact canvas pixels have not yet been recorded. 63D-47 CSS fit / 1:1 are display transformations and cannot fix negotiated RDP graphics size.
- Pointer remains **very delayed** in physical 63D-47 trial. Keyboard, scroll, drag acceptance are unverified.
- Render backend 2026-11-23 ~20:48–20:50Z: three browser and agent RDP WSS pairs accepted; bounded safe traffic summaries available, including bidirectional packet/byte counts. First browser/agent bytes in ~220–340ms are connection startup offsets, **not input-to-visible-pixel latency**.
- Backend CPU light in previous snapshots; that alone does NOT localize latency or prove performance.
- Release 1248 was retained, six-minute GNOME and ten-minute shadow-agent timers, on-demand test only. PR #413 must remain draft; release 1249 is blocked.

## Evaluated options

| Option | Fit to same GNOME physical kiosk | Browser integration | Operational/security trade-off | Decision |
|---|---|---|---|---|
| GNOME Desktop Sharing RDP + PlanIQ WSS relay + FreeRDP 3.33.1 WASM | Strong (native GNOME) | Native RDP in browser, E2E RDP TLS certificate pin; no extra decoding service | New browser runtime (SDL3/Emscripten), mismatched dimensions and severe pointer lag observed; WebSocket buffering/backpressure; deep debugging burden | **Keep as A/B candidate only** |
| GNOME Desktop Sharing RDP + Apache Guacamole 1.6 (guacd + HTML5) | Strong | Mature browser client, RDP GFX support in 1.6 | Additional CPU/containers, secure reverse path for guacd needed; server-side RDP decryption, credentials/certificate must be protected on guacd; extra server trust boundary | **Primary comparison candidate** |
| GNOME PipeWire -> WebRTC low-latency video with separately prioritized input/libei | Possible, if implemented via GNOME-approved portal/session permissions | Native browser media pipeline, possible codec acceleration | Substantial capture/control/security engineering; STUN/TURN may be needed and adds relay bandwidth cost; previous ClientFlow WebRTC trial also lagged, not a proof the protocol cannot work | **Conditional third candidate** |
| GNOME VNC + noVNC | Depends on VNC backend and GNOME version | Mature JS VNC client | May have weaker compression/performance/security and additional desktop backend compatibility checks | **Fallback only** |
| RustDesk OSS | Wayland support exists, but unattended GNOME functionality has changed during 2026 | Separate client/server; OSS web integration/control-plane fit must be verified | Additional identity/tunnel stack and potential licensing/product-tier mismatch; separate management | **Do not replace current control plane now** |
| wayvnc | **No**: targets wlroots, not GNOME/Mutter | Browser only through noVNC | Wrong compositor | **Reject** |
| MeshCentral classic Linux desktop | GNOME/Wayland capture and input not yet proven on our environment | Browser capable generally | Project issue reports Wayland screen capture gap | **Reject as drop-in replacement** |

**Guacamole security note:** It terminates RDP inside `guacd` before delivering the Guacamole protocol to HTML5. It cannot simply be swapped in while preserving current browser-to-GNOME TLS end-to-end semantics. Explicitly document and protect this revised trust boundary; do not advertise E2E RDP TLS if using guacd. Guac can be run in Render Docker on demand for pilot, but concurrency/memory and audit/access must be verified first.

## Best-practice target architecture (technology-neutral)

`PlanIQ Display login + RBAC + step-up -> short-lived, single-client, single-session ticket -> Render session broker -> authenticated outbound ClientFlow agent (HTTPS/WSS 443) -> loopback-only physical GNOME screen-sharing service`

- No inbound RDP 3389/VNC 5900 on the public internet; nftables guard and per-session kill/revoke are fail closed.
- Display's human identities and authorization remain separate from unattended kiosk machine identity (no human MFA prompt on the kiosk).
- Never persist passwords, TLS private keys, screen pixels, or raw RDP packets in app logs/PostgreSQL; bound telemetry only.
- Only active remote-control sessions should consume graphics bandwidth/CPU, not all 100+ registered kiosks.
- Render's WebSocket load balancer assigns each new connection to an arbitrary instance: current in-memory browser/agent matching is **single-instance only** unless session-aware coordination is explicitly added and tested.
- Handle deploy interruptions with explicit disconnect, bounded reconnect and fresh authorized session; do not automatically resurrect privileged control.
- Do not let the admin browser viewport change the physical kiosk monitor resolution (especially 2560x1080 on Viborg1).

## Single physical A/B investigation BEFORE new feature changes

1. **Freeze** active Render frontend/backend at `e58a1f2a2fe52df79df5c0dc50649077d042ccc1`, physical release 1248, and draft PR #413. A speculative untested `/size:2560x1080` was reverted on the draft branch to avoid treating a CLI hint as proof.
2. **Source:** measure GNOME primary `2560x1080`, session mode mirror-primary and local GNOME capture/encoder event timings with read-only telemetry.
3. **RDP reference:** run a standard supported native FreeRDP client against the **same** GNOME desktop via a temporary authenticated private tunnel/loopback path; do **not** open port 3389 to the internet. Inspect its negotiated framebuffer, cursor response and screen refresh. This is the decisive discriminator between GNOME/RDP origin and browser/WASM/relay issues. Prevent recursive capture when doing the local-control test.
4. **Browser A:** run existing WASM through PlanIQ WSS, record precise `FreeRDP-canvas: WxH` and CSS WxH, input->network send, queue depth and timer slip, Render traffic summaries (not mistaken for RTT), decoded-frame completion and observed input-to-visible change. Test click, drag, scroll and keyboard.
5. **Browser B:** isolated, security-reviewed Guacamole 1.6 pilot with GNOME source, same protected agent/Render route and physical test, without third-party external desktop accounts. Make browser/guacd tunnel and TLS trust boundaries explicit. Record the same metrics.
6. **Conditional C:** if RDP browser implementations do not meet targets, evaluate direct GNOME/PipeWire -> WebRTC SRTP with hardware-assisted encoding where available, prioritized reliable input path and TURN economics. The old 15-second-lag ClientFlow pipeline is not an acceptable implementation baseline.

## Proposed acceptance gate — targets, not claims

- **Fidelity:** native RDP/HTML5 displays entire primary 2560x1080 (or an explicitly documented verified negotiated mirror format) with correct aspect and no physical monitor mode change. All click coordinates line up in normal and 1:1 modes.
- **Interactive latency:** illustrative provisional service targets p50 <=150ms, p95 <=250ms for pointer/visible-change under a defined normal network, measured end-to-end with repeatable methods rather than WebSocket first byte or local event delay. Adjust only following an explicit user-approved SLA and measured network baseline.
- **Interaction:** successful consecutive movement, clicks, drag, scroll and typing with no broken keyboard layouts or stuck buttons; re-auth/session expiry works.
- **Security:** short-lived authorization, TLS identity, 3389 local only, independent watchdog and agent rollback, no credentials or screen pixels logged, no post-revocation input.
- **Scalability/cost:** report both 100 idle/registered clients and separately 1/5/10/15 concurrent viewed desktops. Per-session RAM/CPU, Render bandwidth and realistic monthly cost must be measured. No assumptions that 100 registered equals 100 concurrent.
- **Release 1249:** no approval until all physical gates pass and no new security or cost regression.

## Primary references (as checked 2026-11-23)

1. Canonical, *Ubuntu 26.04 Desktop Sharing vs Remote Login*: https://ubuntu.com/desktop/docs/en/26.04/how-to/share-your-desktop-remotely/
2. GNOME remote-desktop internals (PipeWire, libei, Mutter): https://github.com/GNOME/gnome-remote-desktop/blob/main/README.md
3. FreeRDP 3.33.0 (2026-11-02; new browser WASM): https://www.freerdp.com/2026/11/02/3_33_0-release
4. FreeRDP 3.33.1 patch (2026-11-10): https://www.freerdp.com/2026/11/10/3_33_1-release
5. Apache Guacamole 1.6 architecture: https://guacamole.apache.org/doc/gug/guacamole-architecture.html
6. Guacamole 1.6 RDP graphics pipeline/resize config: https://guacamole.apache.org/doc/gug/configuring-guacamole.html
7. Guacamole 1.6 release graphics optimizer: https://guacamole.apache.org/releases/1.6.0/
8. RustDesk OSS/Pro features: https://rustdesk.com/docs/en/self-host/rustdesk-server-oss/
9. RustDesk unattended Wayland (preview): https://rustdesk.com/blog/unattended-remote-access-wayland/
10. wayvnc compositor support: https://github.com/any1/wayvnc
11. MeshCentral Wayland limitation: https://github.com/Ylianst/MeshCentral/issues/7875
12. Render WebSockets load distribution: https://render.com/docs/websocket
13. Render deployment interruption behavior: https://render.com/docs/uptime-best-practices
14. Browser WebSocket queuing/backpressure: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket
15. WebRTC real-time RTP and TURN economics: https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Intro_to_RTP and https://webrtc.org/getting-started/turn-server

## Implementation batch 63D-48A — native reference, isolated Guacamole lab, evidence gate

The first A/B investigation batch is implemented as non-production code, NOT a new streaming solution.

- scripts/clientflow_63d48_native_reference.py: Viborg1-only root-verified capability check plus bounded native FreeRDP graphical reference. Requires an ALREADY ACTIVE six-minute GNOME Desktop Sharing pilot, independent root watchdog, verified kernel firewall, ephemeral protected credentials. Does NOT start RDP, alter GNOME display settings or change the ClientFlow agent. Uses private Xvfb with no TCP listener and unprivileged FreeRDP client, requests 2560x1080 in the REFERENCE CLIENT ONLY, checks one-time TLS certificate fingerprint and passes credentials via /args-from:stdin, never argv/env/logs. Optionally checks if the local X11 image changes. DOES NOT prove GNOME screen geometry or end-to-end pointer latency. Does not click, type or alter the remote kiosk.
- scripts/clientflow_63d48_evidence_gate.py: offline strict secret-free A/B comparator for native-freerdp, browser-freerdp-wasm and browser-guacamole. Requires ALL THREE candidates, 2560x1080, verified interaction/security gates, 30+ measurements with a valid pointer-to-visible-change method and bounded CPU/memory/bandwidth. RDP bytes, WebSocket first-byte timers or browser event lag are not accepted as pointer RTT. Proposed targets: pointer p50 ≤150ms and p95 ≤250ms. It NEVER approves release 1249 automatically.
- experiments/63d48-guacamole/compose.offline.yaml: digest-pinned, no host port, internal-only, read-only, low-privilege OFFLINE guacd capability definition. There is deliberately no Guacamole web application, user database, browser endpoint, physical GNOME connection or running service. It is NOT a completed Guacamole A/B. Before execution, validate actual image architecture, SBOM and Trivy severity and ensure no credential or private-route exposure.
- scripts/tests/test_clientflow_63d48_decision_gate.py: negative tests for firewall/watchdog requirements, no-public-ports posture, native source size, no false positive latency, missing candidates, credentials never in evaluation files, and unknown Guacamole trust boundary.

### Physical operator sequence (separate explicit safety gate)
1. Keep active Render frontend/backend at e58a1f2a2fe52df79df5c0dc50649077d042ccc1, physical release 1248 and draft PR #413. Do NOT deploy this code into production.
2. Run root-only pinned native operator with action preflight. It is safe without an active GNOME RDP pilot and never prints secrets.
3. In the *already independently guarded* six-minute GNOME RDP window, run native 14. The private Xvfb client tests native graphical connection WITHOUT Render, WSS or WASM. Do not claim mouse or keyboard latency has been measured.
4. Existing WASM evidence: physical source 2560x1080@60Hz, canvas 1024x768; FreeRDP default size is 1024x768. Test an explicit 2560x1080 client request only as a separate source-pinned, reversible experiment. Do not change the physical monitor mode or assume this resolves delay.
5. Before enabling Guacamole, explicitly design authorized ephemeral browser -> guacd transport over Render, the NEW server-side RDP TLS termination trust boundary, localhost-only GNOME route, session expiry/revocation, concurrent sessions and deployment failures. The existing per-process native RDP WSS relay cannot simply be treated as a guacd ingress without new reviewed code.
6. Only measured physical mouse pointer-to-visible-change response, correct video mode and successful real click/drag/scroll/keyboard tests can pass the final gate.

### No-regression decisions
- No public 3389/5900/4822, no NAT forwarding, default Guacamole login or password, no user bypass.
- No saved screen pixels or RDP credentials, no public HTML test tool, no new Neon DB, no second Render service, no paid licenses.
- Native Xvfb graphic activity is supportive evidence about the GNOME/RDP source, NOT proof that browser latency is fixed.
- Release 1249 remains blocked.

## One-shot native reference operator (preferred physical execution)

The one-shot operator in scripts/clientflow_63d48_native_oneshot.py integrates all safety-critical steps into one root-only, SHA-pinned, **non-Render** physical test. It downloads verified GNOME 63D-29/30 and native 63D-48 source code, validates the actual GNOME primary mode through the kiosk user's existing D-Bus, checks normal ClientFlow release 1248 agent configuration, and checks Xvfb/Xauthority/native FreeRDP capability **before** starting GNOME RDP. It uses the independently reviewed root nftables/watchdog staging, starts a single six-minute RDP mirror-primary window, invokes a 14-second native FreeRDP graphics check with a separately verified TLS/auth-only test, and invokes GNOME stop before any watchdog unstage. It never exposes RDP or guacd publicly, logs a password or writes screenshot pixels.

One-shot status is PASS only if the native reference process was still running through its bounded window, authentication passed, and all GNOME RDP cleanup checks passed. The result is **NOT** an end-to-end pointer-latency PASS. A second physical proof is still required for cursor/click/drag/scroll and the browser comparison. On a partial GNOME start or a cleanup error, the one-shot returns STOP and retains the independent firewall/watchdog if safe removal cannot be proven. An already staged independent watchdog is preserved rather than silently removed.

Preferred invocation after full CI passes: a SHA256-verified copy from the fixed reviewed GitHub commit, run as root on Viborg1; only the calling wrapper should download the operator source. The operator obtains GNOME and native comparison dependencies from their independently fixed source commits and validates every SHA256. Do not run the operator in a public terminal, and do not paste temporary RDP credentials into chat.

This is a *source-chain reference* and a necessary discriminator between GNOME and browser transport, not a final A/B victory for any candidate. Apache Guacamole remains a non-enabled, internal-only laboratory candidate until an audited agent-to-guacd trust boundary exists.

## 63D-48B – preflight correction from Viborg1 (24 November 2026)

The first physical root operator reached `MONITOR_READONLY=PASS_2560x1080_60HZ_SCALE_1`, then returned `NATIVE_REFERENCE_DEPENDENCY_MISSING` before GNOME RDP stage. Release 1248 and Render were unchanged. This is **not** evidence of a GNOME, RDP or mouse failure.

Source audit found two issues in the pilot code, corrected together:
1. `xwd` is an **optional** X11 framebuffer-change sampler, but the original one-shot incorrectly treated any `=NOT_INSTALLED` result as a fatal required dependency. Now only FreeRDP, xvfb-run, Xvfb, xauth and openssl are mandatory; the operator reports exactly which of these is absent before staging GNOME. If xwd is unavailable, frame-change evidence remains UNKNOWN; this is not represented as a decoded-graphics PASS.
2. The original root-protected `/run/clientflow-63d48-reference/` directory is inaccessible to the unprivileged `clientflow-kiosk` Xvfb worker. A new temporary, SHA256-verified root-owned **source-only** copy (0644) is staged under `/run/clientflow-63d48-native-worker.py`, executed as the kiosk user, then removed. No credentials, TLS keys, raw RDP bytes or images are placed in that readable file; all secrets remain on private stdin. A pre-existing worker file is never overwritten. A failed worker cleanup fails closed.
3. The revised one-shot uses a distinct `/run/clientflow-63d48-reference-r2` directory to avoid reusing SHA-pinned obsolete source files left by the first STOP. The former runtime directory is not silently altered or deleted. Script retrieval remains tied to a fixed GitHub commit and SHA256; the installed kiosk release remains unchanged.

The historical test STOP did not activate the six-minute RDP session. Retest only with the corrected SHA-pinned launcher once the new CI gate is green.

## 63D-48F — physically observed kiosk authentication and scoped resolution experiment (2026-11-24)

63D-48E: root auth returned 1 with no known signature, kiosk-user auth returned 0; native graphics process survived 14 seconds requesting 2560x1080. No X11 frame-change evidence (xwd absent), negotiated size and input-to-pixel delay unmeasured. GNOME stop/unstage and cleanup all PASS. Do not infer the precise root cause from the different environments. No Render or installed release changes.

Promote the kiosk-user authentication path to the canonical native comparison script, retaining root guard verification, temporary credentials on stdin, certificate pin and private Xvfb. The browser candidate requests initial /size:2560x1080 ONLY on the validated client-3 tunnel path; no dynamic resolution or physical monitor configuration change. Regression tests check the scoped argument and unprivileged invocation. This does not prove correct canvas size, working input, low latency or automatic browser credentials. 63D-49 activation remains blocked; Guacamole is still an inactive comparison candidate. Do not deploy or merge until CI and the separate security gates are reviewed.
