# PlanIQ Display · 63D-37 · Local RFB isolation and read-only security gate

Date: 2026-11-22. Existing draft PR #407, no merge/deployment or client changes.
Continue the physically accepted 63D-32 GNOME Desktop Sharing + FreeRDP/Xvfb
pilot without repeating any of its 5/5 clicks and pixel checks.

## Verified upstream package status

- Ubuntu 26.04 / resolute, x11vnc CVE-2026-32853:
  https://ubuntu.com/security/CVE-2026-32853 — **Needs evaluation**.
- Ubuntu 26.04 / resolute, TigerVNC x0vncserver CVE-2026-34352:
  https://ubuntu.com/security/CVE-2026-34352 — **Needs evaluation**.
  The upstream fixed boundary is TigerVNC 1.16.2; do not equate source
  version strings with patched Ubuntu package build or a supported ABI.
- GNOME Desktop Sharing and FreeRDP local pilot were already physically
  accepted; **the remaining blocker is RFB producer privilege/isolation**,
  not the GNOME RDP handshake or Render/DB functionality.
- These CVEs affect local cross-user framebuffer isolation, so wrapping
  a vulnerable server in HTTPS or hiding TCP/5900 is NOT sufficient.
- Until official Ubuntu package vulnerability status and exact build are
  independently reviewed, do **not** install or start x11vnc, TigerVNC
  x0vncserver or unreviewed source builds on Viborg1.

## Source-only implementation

### client/runtime/clientflow_runtime/native_rfb_local_gate.py

- `PRODUCER_APPROVED = False`, **not** an environment variable; cannot
  accidentally be enabled by a Render configuration change.
- Future native client connector requires a canonical UUIDv4 generation,
  fixed private directory `/run/clientflow/native-rfb` (0700, owned by
  the expected unprivileged agent), and AF_UNIX SOCK_STREAM inode (0600
  same UID and device), with symlinks and unexpected types rejected.
- `open_approved_socket` first requires explicit code approval, then
  performs two inode+owner/mode checks around a bounded 2s AF_UNIX
  connection, closes if the socket is replaced, and never opens TCP or
  starts processes.
- Any future host supervisor must create this directory/socket in a
  permission-preserving, atomic and root-monitored manner. Do not pass
  arbitrary paths from HTTP, browser or client messages.
- Existing `native_rfb_stream.py` remains the bounded byte forwarder
  for a **pre-connected**, approved socket; it is not a VNC daemon.

### scripts/clientflow_63d37_rfb_preflight.py

- **Read-only** inventory of a *specific* verified host:
  `viborg1-NUC14MNK-B2`, root, ClientFlow ID=3, Ubuntu 26.04.
- Only three fixed non-mutating commands:
  `dpkg-query -W` (installed candidate versions),
  `ss -H -lntup` (IPv4/IPv6 TCP/UDP RDP/VNC exposure),
  `nft list table inet clientflow_63d29_rdp_guard` (visibility check).
  It also reads `/etc/clientflow/identity.json` and `/etc/os-release`.
- Emits JSON including CVE blockers, package versions, guard visibility
  and exposed-port check. All output says `activation_permitted=false`,
  `producer_security_approved=false`, `filesystem_modified=false`.
- An observed guard table does **not** prove its complete nft rule contents;
  a future privileged launch must reuse the rigorous 63D-29/30 exact
  firewall/watchdog/source-integrity preflights.
- Does not use APT install, systemctl, network downloads, chmod, chown,
  mkdir, reboot, gsettings, GNOME service startup or any RFB listener.

## Synthetic CI acceptance (no physical client access)

- Test canonical session/generation IDs, rejecting path traversal,
  wrong UID, root agent, symlinked private directory, regular fake
  socket, wrong 0600/0700 permissions, and socket replacement.
- Test that unapproved producers categorically refuse Unix connection.
- Simulate source-approval **only in a test against an in-process AF_UNIX
  fake RFB banner**; demonstrate ordered input and response, shutdown,
  and no TCP listener, package or GNOME activation.
- Test no exposed TCP/UDP 3389/5900; mismatched OS/host/ID,
  missing firewall/ss evidence, and exact read-only command allowlist.
- Full GitHub CI and single-node Render/Docker PostgreSQL smoke must
  pass on the same exact commit; these tests are not a physical RDP
  frontend/browser acceptance.

## Remaining hard STOP before physical 63D-37

1. Obtain a verified Ubuntu 26.04 RFB server version **not affected by
   local framebuffer/IPC exposure**, or build an independently reviewed,
   source-/hash-pinned alternative in an isolated CI runner. No risky
   package may be installed just to conduct this check.
2. Implement and review a root-managed on-demand producer with no public
   3389/5900, a private socket exclusively for the authorised agent,
   Xvfb/Xauthority isolation, ephemeral credentials, strict lease
   < = 360s, and fail-closed watchdog across reboot/logout/reconnect.
3. Wire the existing native agent lane to `open_approved_socket`
   **only after** the producer gate is green; do not switch the two
   source-disabled browser/backend flags yet.
4. Prove visible real GNOME pixels and actual mouse/key-up through
   PlanIQ Display browser, compare input→visible pixel p50/p95 against
   current JPEG, test WSS-blocked HTTPS fallback, shutdown/restart and
   physical HLS >=90s before any merge/deploy.
5. Cost guard: existing Render Docker with embedded PostgreSQL, zero Neon,
   zero extra paid servers and zero extra per-idle-client processes.

Viborg1 stays ClientFlow 1248. This phase does **not** mark native RDP in
browser as working and does not change existing JPEG/livestream.

## Version-level finding from Ubuntu archive, 22 November 2026

Ubuntu resolute's advertised `tigervnc-scraping-server` build is
`1.15.0+dfsg-2build1`, while the upstream source fix for
CVE-2026-34352 is in 1.16.2; **do not select this distro candidate**:
https://packages.ubuntu.com/uk/resolute/x11/
https://nvd.nist.gov/vuln/detail/CVE-2026-34352

Ubuntu resolute's x11vnc source package is `0.9.17-2`. The upstream
version alone is NOT a proof of a patched Ubuntu security build, and
Ubuntu still marks x11vnc's CVE-2026-32853 as Needs evaluation:
https://packages.ubuntu.com/source/resolute/x11vnc
https://ubuntu.com/security/CVE-2026-32853

The package's exact `dpkg-query` version on **Viborg1** must eventually
be inventoried with the read-only script, not assumed from the archive.
