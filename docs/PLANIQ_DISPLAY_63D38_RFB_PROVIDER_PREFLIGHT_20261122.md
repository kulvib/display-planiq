# PlanIQ Display · Fase 63D-38 · Actual Ubuntu RFB package candidate preflight

Date: 22 November 2026 · draft PR #407 · no merge, no deployment, no
Viborg1 installation or service activation. This note corrects conflation
of distinct 2026 CVEs in earlier draft phase documents.

## Physical evidence already accepted (do not repeat)

Read-only checks on Viborg1 (ClientFlow client 3, Ubuntu 26.04):
- GNOME RDP system service and kiosk user service inactive/disabled.
- FreeRDP `freerdp-x11` `3.32.2+dfsg-0ubuntu0.26.04.1` and
  `xfreerdp` available; Xvfb `2:21.1.22-1ubuntu1.3`;
  Xauth `1:1.1.2-1.1build1`.
- x11vnc and TigerVNC scraping-server not installed. Earlier host
  inventory found no external RDP/VNC ports and no remaining
  temporary pilot firewall table; no client runtime process activated.
- GH CI and local Render Docker / PostgreSQL smoke passed on
  Fase 63D-37 correction `c8d452a56fdc9eea022303db16b4ba7938ce4492`.
- The 63D-32 GNOME FreeRDP proof already had 5/5 real mouse ACKs and
  visible pixel updates (local p50 ~120.7 ms); these do NOT establish
  browser RDP/noVNC performance or backend roundtrip.

## Authoritative current security distinction

- `CVE-2026-32853` in LibVNCServer is an UltraZip **client decoder**
  out-of-bounds read: https://ubuntu.com/security/CVE-2026-32853 .
  Ubuntu 26.04 `libvncserver` is explicitly "Not affected" by this CVE.
  However Ubuntu still lists `x11vnc` itself as "Needs evaluation".
  These are distinct upstream/source-package tracking rows, not a
  definitive vulnerability or security clearance for the binary.
- USN-8494-1 (2 July 2026) requires Ubuntu resolute
  `libvncserver1` and `libvncclient1`
  `0.9.15+dfsg-3ubuntu0.2` or newer with Debian epoch-aware comparison:
  https://ubuntu.com/security/notices/USN-8494-1 .
- `CVE-2026-34352` is a separate TigerVNC `x0vncserver`
  *cross-user framebuffer shared-memory permissions* issue, upstream
  fixed in 1.16.2; Ubuntu 26.04 still "Needs evaluation":
  https://ubuntu.com/security/CVE-2026-34352 .
  Do NOT install the known Ubuntu 26.04 `tigervnc-scraping-server`
  1.15.0 package as a substitute.
- Upstream `x11vnc 0.9.17` documents
  `-unixsock <private-path> -rfbport 0`, a Unix-only mode that
  avoids TCP/5900, but the upstream document also warns about historical
  libvncserver socket implementation limitations:
  https://github.com/LibVNC/x11vnc/blob/master/doc/OPTIONS.md .
  This must be proven with the exact Ubuntu binary/library combination
  before trusting it for an unattended client. Do not assume support
  from a documentation string alone.

## New 63D-38 executable preflight

`scripts/clientflow_63d38_rfb_provider_preflight.py` is intentionally
**read-only**, with a fixed target identity and *only* these inspections:
1. `apt-cache policy` for `x11vnc`, `libvncserver1`,
   `libvncclient1`, `tigervnc-scraping-server`;
2. `dpkg-query -W` for their actual installed versions;
3. `dpkg --compare-versions` (read-only) for the current library
   candidates against Ubuntu's 0.9.15+dfsg-3ubuntu0.2 baseline.

It reports `candidate_versions`, `installed_versions`, and
`library_candidate_at_least_usn_8494_1`, explicitly **without**
asserting `x11vnc` safe merely because dependencies have a patched
candidate. The JSON always sets `producer_approved=false` and
`activation_permitted=false`; source never calls apt install,
systemctl, starts RDP/VNC, modifies permissions or opens TCP listeners.

`scripts/tests/test_clientflow_63d38_rfb_provider_preflight.py`
covers Ubuntu apt policy parsing, Debian epoch versions,
package-not-installed status, malicious version strings, mixed security
versions, wrong machine/UID/client/OS, and strict command allowlisting.

## Next physical and implementation gates

1. Run only the SHA256-pinned, read-only 63D-38 candidate preflight on
   nonproduction Viborg1. Review the *actual installed and candidate*
   LibVNCServer versions and x11vnc candidate, do not guess them.
2. Validate the exact upstream x11vnc source/package against current
   security advisories and test `-unixsock -rfbport 0` behavior in
   disposable isolated CI, not by opening a service on Viborg1.
3. Only then implement the on-demand privileged Xvfb+FreeRDP/RFB
   supervisor, strict user-private Unix socket, 360-second timeout and
   root watchdog; wire the existing client agent byte lane and
   browser noVNC WSS/HTTPS lanes.
4. Obtain physical browser pixels + keyboard/mouse input-to-visible-
   pixel p50/p95, WSS-blocked HTTPS fallback, release rollback and
   ≥90 second independent HLS playback validation before merge/deploy.
5. Keep PlanIQ Display backend in Render Docker with embedded
   PostgreSQL; no Neon, no extra paid services or public RDP/VNC port.

**None of these gates should repeat the already accepted local 63D-32
FreeRDP proof, or claim that a green source-only CI is a working browser.**
