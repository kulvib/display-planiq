# 68K-E4 – closed catalogue promotion and operator store rotation

Source-only promotion of the exact 1250 closed stage; 1251 remains an independently approved artifact, not a standard release. PR 445 and main CI were green before this branch. Existing 1250 and 1251 archive pins are unchanged. Historical catalogue tests now use the corresponding immutable 1248 stage as a fixture; historical source guards remain fail-closed for old pilot commands. No new runtime or build of 1251.

After reviewed merge and green main, redeploy backend/frontend. The old 1245 control binding remains closed until the operator explicitly applies the reconciliation. During this brief transition only the exact existing 1250 physical host retains native RDP eligibility, using the original pinned historical policy and exact closed catalogue. No 1248 or successor grant in the bridge.

The operator script `scripts/reconcile_clientflow_1251_store.py` defaults to non-mutating inventory. It validates local PostgreSQL, exact source catalogue, client #3 fresh canonical 1250 status, successful predecessor deployment, single Update credential, no active deployment/System command, no unresolved recovery, live provisioning/enrollment/rollback permits or rollout authority, no live draft/paused wave or physical acceptance. All closed policy flags must remain closed. It does not expose secrets or invent acceptance. Before deletion it streams three old public GitHub archives and downloads 1251 to ephemeral storage, verifying exact SHA-256 and size. Then it rebinds the singleton from revision 1 / 1245 to revision 2 / closed 1250 in an audited transaction, removes exact oldest files via the canonical locked prune mechanism, and publishes 1251 via the strict publisher. No fourth approved file is created. If interrupted after rebind, only the exact verified remaining oldest-first suffix is resumable. Filesystem changes and DB binding are not a single atomic transaction; 1248 and 1250 are preserved throughout. Actual downloads and DB inventory have not yet been performed. No destructive operation in this PR.

Run in the Render backend shell as the existing application user; no secrets on the command line:
```bash
cd /opt/display
gosu display_app env DATABASE_URL='postgresql:///display?host=/run/display-postgres' \
  PYTHONPATH=/opt/display/backend:/opt/display PYTHONDONTWRITEBYTECODE=1 \
  python3 -B scripts/reconcile_clientflow_1251_store.py
# After dry-run PASS and fresh local readiness attestation, same invocation with
# --apply --confirm-viborg1-local-preflight
```

The operator must not initiate concurrent deployment, System or enrollment actions during rotation. A stopped rotation is not proof of failure-free recovery or successful installation; inspect its exact output and re-evaluate. Once the final inventory is three exact TARs, verify 1250 Remote Desktop and the other media/runtime functions before ordering the one-shot 1251 pilot in release administration. Do not select or manually downgrade through historical mechanisms. Full physical acceptance and final release promotion remain outstanding.
