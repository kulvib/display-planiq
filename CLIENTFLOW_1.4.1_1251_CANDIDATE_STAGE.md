# ClientFlow 1.4.1 / 1251 — unsigned candidate stage

Source baseline: 86c45147aa90323dee69dedf27152ec1584eab20 (68F, PR 436).
This stages only the exact successor source identity for reproducible build.
It includes the merged canonical systemd status collector and Ubuntu inventory
freshness/reboot-marker changes. Existing 1250 approval bytes remain immutable.

## Gates

- Complete source checksum manifest; exact-source CI; two independent builds;
  explicit hash-bound approval; verify immutable transport.
- Existing historical catalog and 1250 approval unchanged. No catalog promotion,
  authorization, fresh install, fleet rollout or retention deletion is granted.
- Native RDP admission currently requires the exact 1250 baseline. Before any
  1251 physical installation, review and implement a separately scoped,
  artifact-bound successor authorization and recovery plan that preserves 1250.
  Do not simply replace the baseline constant or bypass admission.
- Verify physical Viborg1 systemd, Ubuntu inventory, firmware, kiosk startup,
  Remote Desktop, Livestream, Terminal, files and simultaneous media after an
  approved update. Keep existing working 1250 until that path is verified.

Infrastructure: Render Docker with local PostgreSQL on persistent disk;
no Neon, new paid service, or new environment variables.
