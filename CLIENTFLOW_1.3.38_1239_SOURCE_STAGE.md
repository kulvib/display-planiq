# ClientFlow 1.3.38 / sequence 1239 — source identity stage

Status: **STAGED SOURCE IDENTITY ONLY** — **NOT approved**, **NOT published**, **NOT catalog-promoted**.

- Source identity: `client/VERSION=1.3.38` and `client/release/release-input.json` sequence `1239`.
- Runtime remains Python `3.13.14` for Ubuntu Desktop `26.04` / `amd64`, GNOME Wayland.
- Production catalog still selects exactly **ClientFlow 1.3.37 / 1238**, which remains **fresh-install-only**. `update_allowed=false`, `rollback_allowed=false`; **No in-place update** or rollback to any 1.3.38 candidate is authorized.
- There is no approved 1.3.38 bundle, exact source SHA, candidate digest, approval reference, publication, or physical acceptance claim at this stage. Source SHA is assigned by GitHub after review/merge, not invented in this document.
- Build may only begin from a new exact-source CI-green commit, with separately verified locked runtime-input transport, reproducible independent builds and the Ubuntu 26.04 physical candidate gate.
- Release approval, immutable store publication, and subsequent catalog promotion are separate independently verified steps. Never advance the catalog before publication.

## Acceptance contract for the new release

1. GUI on actual Ubuntu 26.04/Wayland: copy the complete displayed kiosk URL and active IP, verify actual paste into another kiosk-session application, and verify icon visibility for empty, placeholder and populated rows.
2. Kiosk cursor hides after idle and reappears on activity without affecting technician-facing GTK status GUI or standard desktop frontend layout.
3. Calendar wake requests at most one actual reboot per local active calendar day and only when the host has not already rebooted that day. Verify a changed Linux boot ID before claiming success. The host must return to usable display/browser state, including after an ambiguous or failed reboot attempt. Manual display wake and physical-input wake must never reboot.
4. Control Room shows accurate calendar-vs-other reboot provenance and explicitly unknown, pending, unplanned and error states, including stale/offline status; no additional polling/query fanout.
5. Preserve installation, lockdown, terminal, remote desktop, livestream, dvale/countdown/wake and exact-source security gates. Re-test on a separately authorized clean fresh-install client. Existing 1.3.37 installation on Viborg1 is immutable, and fresh-install-only release policy does not permit applying a 1.3.38 candidate to it in place.

The branch for source staging must have fully green GitHub CI before triggering `runtime-input-transport.yml` and `release-build.yml`. A source-stage CI PASS does not imply physical acceptance, approval or production readiness.
