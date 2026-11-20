# Phase 63D-14 — Viborg1 / 1247 one-shot recovery (operator gate)

**Status: source staged for independent GitHub CI review; NO physical recovery has occurred.**

The user independently verified both the local `phase63d13_viborg1_recovery_preflight.py` (`READ_ONLY_PREFLIGHT=PASS`) and Render's **actual local PostgreSQL** record (`BACKEND_RECOVERY_PREFLIGHT=PASS`). These checks are evidence from 20 November 2026, not perpetual authorization. The canonical 1247 TAR must not be rebuilt or modified; 1246 stays active until the operation.

- Host: `viborg1-NUC14MNK-B2`, backend client ID `3`.
- In-flight deployment: `f99607f6-f1b7-43e5-a489-d756246e1849`.
- Current `clientflow-1.3.45-seq-1246`; target staged `clientflow-1.3.46-seq-1247`.
- Approved TAR SHA256: `3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150`.
- Approval: `CF-1.3.46-1247-20261119-22a8a873-d60d63ba`.
- Current state: `activation_authorized`, no activation_intent, correct `update_clientflow` install coordination, updater timer **inactive**, status-agent active. No new deployment, no DB reset, no deletion of lock/state.

## Approach and trust boundaries

The known 1246 `update_controller.py` holds `update_clientflow` with the exact backend deployment ID, but 1246 `transaction.py` incorrectly refuses that same lock. Phase 63D-13 fixed `transaction.activate_release(... expected_update_deployment_id=...)` and the permanent controller call. The existing sealed 1246 controller cannot automatically see 63D-13's changed source.

The standalone, **default read-only** `scripts/phase63d14_viborg1_one_shot_recovery.py` requires **the exact source hashes** of:

1. The installed 1246 `transaction.py` and `update_controller.py` (prove historical code).
2. The source-reviewed fixed 63D-13 `transaction.py` (provided as private, root-owned external file).
3. The prior `phase63d13_viborg1_recovery_preflight.py` (provided privately, unmodified).
4. The root-owned staging directory `/var/lib/clientflow/63d14-recovery`, mode 0700, with individual files mode 0600.

The one-shot runner does not patch either signed release on disk. It loads the fixed transaction module **before** importing 1246's original controller, preserving Python class identity (`TransactionError`, `Layout`) so normal rollback reporting remains connected. The precise deployment ID is supplied only to the injected activation callable. All release transaction steps, local health checking, automatic rollback, backend DPoP re-authentication and deployment event reporting remain owned by the original 1246 machinery. Backend state is re-fetched at execution: a previous Render PASS is never enough.

`--check` performs only the local source and state validation. `--execute` requires root, the exact operator's `CLIENTFLOW_63D14_ONE_SHOT` value, systemd `INVOCATION_ID`, and systemd `CREDENTIALS_DIRECTORY` with the original update credentials. It does not bypass any missing backend authorization. A second execution is not allowed by the original local preflight once activation changes state.

## Required operator-controlled deployment procedure — not executed by merge

**Do not perform the steps below before all GitHub CI checks have passed and the exact reviewed scripts have been pinned by the new merge commit.** The active 1246 release must remain intact. An administrator must be able to reach Viborg1 physically if the transaction health check or automatic recovery fails. Keep the updater timer stopped.

1. Stage exactly these **three GitHub-commit-pinned** files into `/var/lib/clientflow/63d14-recovery` (root 0700, files 0600):
   - `scripts/phase63d14_viborg1_one_shot_recovery.py` as `phase63d14_viborg1_one_shot_recovery.py`;
   - `scripts/phase63d13_viborg1_recovery_preflight.py` as `phase63d13_viborg1_recovery_preflight.py`;
   - `client/release/lib/clientflow_release/transaction.py` as `transaction.py`.
   Verify their published SHA256 values and the new merge commit before execution. **Never stage into `/opt/clientflow/releases/` or `/opt/clientflow/active`.** Do not include credentials in the staged directory.
2. Run the non-mutating check with the **static pinned 1246 interpreter**: `/opt/clientflow/releases/clientflow-1.3.45-seq-1246/runtime/bin/python -I /var/lib/clientflow/63d14-recovery/phase63d14_viborg1_one_shot_recovery.py --check`. It must say `PHASE_63D14=CHECK_ONLY_PASS`.
3. Re-run independent Render `BACKEND_RECOVERY_PREFLIGHT` before executing, checking the **same original deployment** remains `activating`, bundle SHA and approval unchanged, without a completion or new event contradiction. Check timer remains inactive; preserve local snapshots for forensics.
4. Only with explicit physical recovery authorization, install a **temporary runtime-only systemd drop-in** for the EXISTING `clientflow-update-controller.service` (under `/run/systemd/system/clientflow-update-controller.service.d/`, not the sealed release), replacing `ExecStart` with the **pinned 1246 runtime interpreter** invoking the reviewed script with `--execute`. Set `CLIENTFLOW_63D14_ONE_SHOT` to the exact original UUID. Do not change the service's original `LoadCredential` or hardening. This ensures the actual activation process remains supervised when it stops ClientFlow's own runtime/terminal services.
5. Run `systemctl daemon-reload`, then start the existing controller **once** via `systemctl start --no-block clientflow-update-controller.service`; do not start the updater timer. Check `journalctl` and the deployment history. An execution error or ambiguous outcome is a STOP: no retry, manual unlock or manual rollback until local transaction and backend are inspected.
6. Check **both** local `release/state.json` and `/opt/clientflow/active` reference 1247, `activation_intent` cleared and original backend deployment state `succeeded` with the correct events, along with fresh 1.3.46 Status. Test runtime, Terminal, Livestream and Remote Desktop. If it rolled back or reported recovery_required, stop and diagnose rather than claiming success.
7. After a proven terminal outcome, remove only the **temporary runtime-only systemd drop-in** and reload systemd. Retain forensic logs until acceptance. Restart the stable updater timer **only after** verification of the permanent fix in a future approved ClientFlow release and normal update-plane policy; do not assume it is safe merely because the one-shot succeeded.

Operator shell commands for the runtime-only override must be prepared and reviewed **after** CI and receipt of the exact merged commit SHA. This document is an auditable plan, not a directive to execute physical recovery now.

## CI tests and negative controls

- `scripts/tests/test_phase63d14_viborg1_one_shot_recovery.py` exercises source and directory security, source modification/symlink denial, deployment mismatch, explicit systemd-operator gating, and the fixed transaction/controller exception identity.
- Existing `backend/tests/test_clientflow_63d13_update_coordinator.py` and `backend/tests/test_clientflow_update_controller.py` continue to exercise exact-UUID coordination, original deployment outcome/rollback and recovery paths.
- Legacy signed bundles and release metadata remain unchanged. No Render DB mutation and no new ClientFlow release are required for this code-only change.
