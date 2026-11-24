# 63D-49 — Automatic, sealed superadministrator GNOME RDP login

**Status: source implementation in draft PR #413, NOT DEPLOYED or physically accepted.**  
**Context:** ClientFlow physical kiosk GNOME/Wayland; Viborg1 client ID 3, 2560×1080 at 60Hz; Render Docker/PostgreSQL; installed client release 1248; release 1249 blocked.

## Approved user experience

An already authenticated and authorized **PlanIQ Display superadministrator** selects Remote Desktop and clicks **Forbind sikkert med automatisk RDP-login**. No GNOME username, password, TLS certificate fingerprint, backup code or separate Ubuntu login is requested. The existing PlanIQ human login remains mandatory. ClientFlow kiosk machines are machine identities and do not perform interactive human MFA. The absence of a GNOME password prompt must NEVER mean GNOME RDP authentication is disabled.

The installed 63D-30 protected GNOME pilot still generates a unique random username and strong password for each guarded session, a temporary TLS certificate and an independent expiry watchdog. The root credential file remains 0600 and is never copied into an unprivileged readable path or database.

## Chosen security design (transport-independent control-plane contract)

1. Browser generates a non-extractable ephemeral P-256 ECDH private key and a random UUID request challenge; only its public point crosses the existing superadmin Remote Desktop control WebSocket. The browser private key stays in memory and is destroyed when the React component is disposed.
2. Render accepts a request only for the active client 3, currently authenticated superadmin user, the identical browser login-session binding and a live, unrevoked Remote Desktop session. At most one 20-second pending challenge belongs to the browser session.
3. The existing authenticated, separate machine-credential ClientFlow agent receives only client ID, session ID, request UUID and browser public key.
4. The agent connects to a dedicated Unix socket owned by root:clientflow-remote-desktop-agent (0660); root checks SO_PEERCRED against the dedicated agent UID. The root-only broker checks GNOME's actual watchdog/kernel firewall through the pinned 63D-30 code, boot, client identity, active protected pilot and expiry.
5. Root reads GNOME's existing **ephemeral** username/password and public TLS certificate. It computes the certificate fingerprint and encrypts those credentials into a **one-time** P-256 ECDH / HKDF-SHA256 / AES-256-GCM envelope, with AEAD associated data binding client 3 + browser session UUID + request UUID. The sealed envelope expires within 60 seconds or when the physical pilot expires, whichever comes first.
6. The agent and Render **relay only the ciphertext**, never the password. Render checks the same current superadmin authority and its pending challenge before delivering the envelope. No secret is written to a database, telemetry, console, audit, HTTP query or client localStorage.
7. The browser validates the envelope's exact version, session ID, challenge, key encoding and expiry, decrypts it within the browser, and launches the existing FreeRDP WASM iframe with the verified certificate fingerprint. The iframe is disposable, and credentials are not retained for automatic reconnect after the authorized session closes.
8. When the physical GNOME watchdog expires, the root broker must stop and remove the Unix socket; the existing 63D-30 guard removes GNOME credentials and TLS private keys. No static password or default username should remain valid.

## Current implementation boundaries

- `frontend/src/pages/clientdetailspage/remotedesktop/nativeRdpAutologin.mjs`: browser ECDH and authenticated decryption.
- `NativeRdpViewer.jsx`: feature-gated one-click flow; **legacy manual pilot** remains available while this phase is not deployed. Activate only after the complete physical security gate, via `VITE_NATIVE_RDP_AUTOLOGIN=true` for approved clients.
- `RemoteDesktop.jsx`: passes opaque encrypted bootstrap through existing active control WebSocket.
- `backend/service1/routers/remote_desktop_v2.py`: superadmin-only, single-use challenge in **memory**, no persistent schema; no new public endpoint.
- `client/runtime/clientflow_runtime/native_rdp_autologin.py`: agent's bounded AF_UNIX request and envelope validation.
- `client/runtime/clientflow_runtime/remote_desktop_agent.py`: processes authorized control message and returns only opaque envelope.
- `experiments/63d49-autologin/clientflow-rdp-autologin.socket` and `.service`: **inactive** on-demand Unix socket activation and 360-second bounded root service. The socket is 0660 root:agent and the privileged process checks both physical watchdog and nftables before sealing. No public port, no always-on graphics process. These candidate systemd units are NOT copied into the installed release and the root broker executable path is NOT installed; enabling them before a reviewed canonical release package is forbidden.
- `scripts/clientflow_63d49_autologin_broker.py`: root-only protected broker. **This is new code, not yet an installed privileged service.** Requires audited `cryptography` dependency in the root runtime, guarded GNOME pilot and a boot-ephemeral systemd service with independent runtime limit. Do not activate just by making the file executable.
- `scripts/tests/test_clientflow_63d49_autologin_broker.py`, `scripts/tests/test_clientflow_63d49_agent_autologin.py`, `backend/tests/test_native_rdp_autologin_63d49.py`, `frontend/tests/nativeRdpAutologin63d49.test.mjs`: cryptographic and fail-closed regression tests.

## Outstanding gates before enabling

**Functional:** whole-source Python/JS CI and reproducible build pass; root broker ownership, dependency availability and runtime expiry verified on Viborg1; stage it only under the existing six-minute GNOME RDP protection. A physical session must automatically log in *without* manually supplying RDP credentials; mouse/key/drag/scroll and full 2560×1080 still require separate acceptance.

**Security:** superadmin role revocation, login-session expiry, invalid ticket, wrong client, replay challenge, browser refresh, TLS fingerprint tampering, agent identity substitution, unprivileged socket peer, root helper timeout, service stop, local kernel firewall and secrets-in-logs regression. A dedicated fresh passkey/MFA step-up for sensitive remote control is a preferred **additional** requirement from PlanIQ Identity integration; Display's existing superadmin login/session checks do NOT currently constitute proof of fresh step-up. Do not claim step-up already exists. For production, enable after approving a fail-closed step-up policy.

**Operations:** wire broker startup/shutdown to the supervised on-demand GNOME session in the native ClientFlow release, not a manual shell or permanent service. No new Render/Neon resources; no paid MFA. Guacamole alternative has a different RDP TLS termination boundary, so do not assume this browser-specific encrypted delivery can be transplanted to guacd without a new review.

**Rollback:** until all gates pass, keep legacy manual pilot and feature flag off. Do not deploy to Render and do not publish release 1249 based on this source-only implementation.


## 63D-49B — integration review and activation hold

The first CI run stopped at Ruff F821 because a test imported neither pathlib.Path nor an equivalent. Restore the required import. The previous frontend, PostgreSQL smoke and browser startup checks passed; that does not establish a full successful test suite for subsequent commits.

The socket-activated broker originally rejected the systemd-created socket as already existing before checking LISTEN_FDS. It now distinguishes the inherited descriptor from standalone creation, verifies socket owner/path/mode, and only removes a socket it bound itself. Non-object IPC frames are denied. The physical guard subprocess now verifies both root-owned staged sources and adds only their verified 0700 directory to Python isolated-mode imports.

**Do not activate the experimental systemd units.** Their restrictive capability/address-family/read-only settings are not compatible with the existing GNOME status runner (nftables netlink, switching to the kiosk UID for D-Bus settings, and opening its root lock for status). This requires an independently reviewed separation between the existing privileged watchdog/guard and the credential-only sealer; do not simply grant the sealer broad capabilities to make a test pass. The installed broker lifecycle, root dependency availability and watchdog-driven socket removal remain unproven.

**Trust boundary clarification:** the ECDH envelope prevents accidental plaintext disclosure to a forwarding relay, logs and persistence in normal operation with the trusted PlanIQ application and agent. It does not provide an independent authenticated key exchange against an actively compromised Render control plane or a maliciously modified frontend, since the browser public key is relayed by that control plane. Likewise the trusted agent may request a sealed envelope. A single-use envelope is not itself proof that GNOME's password is single-use or immediately rotated on browser disconnect; the existing physical pilot deadline is the currently demonstrated cleanup boundary. An authenticated device trust model, session-scoped revocation and a fresh step-up check must be specified and tested before fleet/production approval.

No new installation or deploy is authorized by these corrections. The physical native-reference comparison remains independent of this autologin experiment.


## 63D-52A — session-bound bootstrap hardening, still source-only

The Render frontend layout pilot remains separately pinned to 516373b; the
backend remains on 73a3d14. This draft is not deployed. Align the envelope
acceptance window to 60 seconds at browser, agent and relay; reject a boolean
schema value, agent replies arriving on the input socket, and a reply after
superadmin demotion even if a generic auth-state check returns ok. The root
broker rechecks its grant after the firewall probe, and the agent's socket
response deadline allows the existing bounded 10-second guard probe without
extending the relay challenge window. Browser operation generations and a
session-keyed viewer prevent asynchronous ticket/credential completion from
relaunching a disconnected/replaced viewer. This is not server-side credential
revocation, and the 60-second envelope TTL is not a GNOME password TTL.

Remaining integration before physical pilot: separate privileged GNOME
lifecycle verification from the credential-only service with authenticated
root-owned short-lived authorization state; bind it to the actual current
session and enrolled device. Install and remove the protected broker through
the canonical runtime lifecycle (no enabling experimental units). Define
single active native RDP lease, credential rotation and tunnel closure on
disconnect, logout, role revocation, watchdog, restart and network failure.
No static client-ID bypass or universal rollout until client identity binding
is implemented and tested across all layers. Browser auto-start and controlled
reconnect need current server authorization and a fresh grant, not cached
credentials. Dynamic RDP resolution requires proof of FreeRDP/GNOME negotiation
and physical pointer precision; CSS zoom alone does not prove it. Keep the
existing strict TLS pin and loopback-only kernel guard. Production step-up
policy remains an explicit security decision; no extra manual RDP credentials.

Do not enable the automatic login flag, deploy this draft, or approve release
1249 from the source-level regression tests. The six-minute watchdog remains
the physical pilot boundary until independently validated lifecycle integration.


## 63D-52B — control-plane-bound native tunnel shutdown (source only)

Invalidate the control session and pending bootstrap before auxiliary activity
lease persistence; close its exact native tunnel immediately. Retain a client's
single tunnel slot until both bounded socket-close attempts complete. Bind the
tunnel to the exact authenticated control channel object, reject a replacement
even with the same credential, and check authorization before the first byte.
Existing periodic DB checks remain; the added per-packet generation check is
only an in-memory lookup. Keep cleanup on failed socket accept. This closes
the transport, not the underlying GNOME credential lease. The root lifecycle,
session-specific credential rotation, unattended start, reconnect and dynamic
resolution remain unimplemented/unverified. No pilot activation or deployment.
