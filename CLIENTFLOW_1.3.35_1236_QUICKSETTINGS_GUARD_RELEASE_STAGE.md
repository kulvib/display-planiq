# ClientFlow 1.3.35 / sequence 1236 – Quick-settings guard source stage

## Authority and status

- Source identity: `clientflow-1.3.35-seq-1236`, from the canonical version and release input.
- Source is **NOT approved**, **NOT published**, **NOT catalog-promoted**, and not physically accepted.
- Production selector remains the independently approved `clientflow-1.3.34-seq-1235` fresh-install-only catalog entry. There is **No in-place update** or rollback authority in that entry.
- Keep the existing `client/release/runtime-platform-inputs.lock.json` (Python 3.13.14, approved third-party artifacts) unchanged for this focused fix.
- This stage includes the `setpriv` quick-settings guard fix already merged into the latest repository; version and sequence are changed to prevent repackaging modified bytes under the immutable 1.3.34 release identity.

## Evidence and acceptance boundaries

The Ringkøbing1 Ubuntu 26.04 diagnostic at 2026-10-11 17:05 CEST recorded that the optional quick-settings guard failed with `runuser: cannot set user id: Operation not permitted` under a `NoNewPrivileges=yes` service. The separate periodic kiosk session policy succeeded. The guard's direct kiosk-user privilege drop uses `/usr/bin/setpriv`, and keeps the service sandbox and capability drop. Local source/CI tests do **not** prove the revised service runs successfully on a physical Ubuntu installation.

## Canonical next gates

1. Merge the exact staged source change through normal protected `main` with green canonical CI; record full source SHA. Do **not** advance the backend catalog yet.
2. Run `runtime-input-transport.yml` for that exact staged source SHA and the existing locked runtime bytes; capture its exact HTTPS URL and SHA-256.
3. Run `release-build.yml` twice-independent/reproducible candidate gates with that exact SHA and transport. Validate candidate and Ubuntu 26.04 executable gate.
4. Independently approve using `release-approve.yml` and publish the approved immutable artifact via the documented Render release-store procedure. Only after verified immutable re-read may a separate reviewed promotion advance the backend catalog from 1.3.34 to 1.3.35. Never invent artifact digests, release references or provenance.
5. Since 1.3.34 is **fresh-install only**, do **not** treat changing Render or using the stable updater as sufficient to upgrade existing Ringkøbing1. Use an authorized, fully verified fresh-install path for the new approved release; any future in-place update requires separate physical acceptance and explicit policy change.
6. Complete physical Ubuntu 26.04 verification: `systemctl is-active clientflow-kiosk-quicksettings-guard.service`, inspect unit journal for user-switch/systemd failures, confirm all lockdown checks (including `quick_guard`) remain true over time, reboot and recheck, and confirm backend observed lockdown status changes from `drifted` to `applied` with acceptable command/SQL rates. Keep `cfadmin` separate from the unprivileged kiosk user.

Do not claim a security fix complete based solely on GitHub CI or backend smoke tests.
