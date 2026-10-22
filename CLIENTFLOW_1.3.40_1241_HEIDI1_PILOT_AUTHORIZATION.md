# ClientFlow 1.3.40 / 1241 — single-client pilot authorization gate

This document describes the later pilot-catalog branch. It does not alter the earlier
source-stage statement `CLIENTFLOW_1.3.40_1241_SOURCE_STAGE.md` (which was true
at the time), the approved immutable release bundle, or the recovery_failed
1240 deployment history.

- Source release: 1.3.38 / 1239 on the sole development client Heidi1, backend id 1.
- Approved target: `clientflow-1.3.40-seq-1241`.
- Immutable bundle SHA-256: `b63211454c9cee0f24277c51f0d13d75099729e641d13f9ce4ed9ad696468783`.
- Bundle bytes: `223518720`.
- Candidate SHA-256: `c38442404905515dce0f06db2d69be68903f9ffeaf3522cfe968ff16e977419d`.
- Original signed source: `f4a25bcefba1c222bd3f908309ce2e94cbf5c4db`.
- Approval: `CF-1.3.40-1241-20261021-f4a25bce`.
- **Closed old pilot**: no 1.3.39/1240 selector in the active catalog;
  retired guard permanently refuses requests regardless of
  `CLIENTFLOW_1240_PILOT_CLIENT_ID`. Do not remove the historical evidence.
- **Disabled by default**: `CLIENTFLOW_1241_PILOT_CLIENT_ID` must equal exact
  string `1` to permit a request; this is a backend feature flag, not the
  release-client version or a fleet list.
- Only superadmin (router dependency), client id 1, fresh canonical online
  Status 1.3.38, explicit justification, approved nondeleted client, no
  pending System command, no repair/downgrade, exact 1.3.40/1241 target
  and exact published immutable bundle identity. Guards run before artifact
  lookup and after locking the canonical client row.
- Catalog stable/default/fresh-install remains 1.3.38. No automatic update,
  no automatic rollback, no remote downgrade.

## Rollout (separate explicit user approvals)

1. Upload changes-only branch to GitHub and obtain green CI. Use a fresh merged
   repository ZIP as the next source of truth.
2. Deploy updated backend to Render **without** setting the new flag; confirm
   old pilot flag off, unchanged stable/default and zero active deployments.
3. Reconfirm Heidi1 bridge + idle controller + active 1.3.38 + online Status.
4. Only on separate user authorization, enable the new flag for the dedicated
   pilot and manually create one 1.3.40 deployment. Do not use `latest`.
5. Observe local activation, recovery, journal and user-facing runtime incl.
   kiosk internet guard, Chrome/Wayland, GUI, online status and reboot.
6. Disable pilot flag after acceptance or failure and verify no new deployments.
   Retire temporary systemd bridge only after checking target controller unit
   installation and drop-in cleanup safety.

All field acceptance remains PENDING until actually observed on Heidi1.
