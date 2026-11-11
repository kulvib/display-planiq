# ClientFlow 1.3.43/1244 – retire Heidi1 and Viborg2's obsolete backend identities

## Scope and operator decision

The physical installations on Heidi1 and Viborg2 were wiped. The newly approved
**1.3.43 / sequence 1244** is the only approved/selectable fresh-install
release in the Render store. Historical client IDs **1 (Heidi1)** and **2
(Viborg2)** still exist with active credential rows and require secure closure
before fresh installations can resume.

This branch is **source-only**. Merging it **does not revoke anything, change
Render configuration, remove old data, issue install codes or authorize
physical installation**. It does not change the immutable approved 1244 TAR.

The separate, irreversible operational decommission requires **fresh-install
suspension** and the exact one-release 1244 catalog + verified TAR. The
operator must independently affirm the physical wipe and confirm that no
recoverable/offline client, active download, open enrollment or deployment
needs either old identity. The script refuses to operate on names or IDs
other than exactly `1=Heidi1` and `2=Viborg2`; it does not search by mutable
client names alone. It changes the two clients **in one database transaction**.

## Security contract

- Default: **read-only preflight**; count active credentials/sessions, verify
  catalog, env, one approved TAR and exactly pinned backend IDs + names.
- Execution requires three independent explicit arguments (`--confirm-decommission`,
  `--confirm-physical-wipe`, and exact `--approval-reference`).
- Refuse if `CLIENTFLOW_FRESH_INSTALL_SUSPENDED != 1`, any 1241–1243 pilot
  flag is active, global active enrollments/deployments exist, identity or
  isolated-domain states differ, or release SHA-256 does not match.
- Revoke shared Status/Display/System, Livestream, Terminal, Remote Desktop,
  asymmetric updater and SYSTEM encryption keys. Invalidate legacy client
  secret/token-version; revoke update provisioning codes, root grants and
  rollback permits; expire old enrollment resume receipts.
- Disable Terminal and Remote Desktop identities; revoke active sessions with
  append-only session events; cancel in-flight shared/livestream commands,
  stop active generations and end old viewer sessions. Completed history is
  not altered. Clear pending legacy Chrome action.
- Keep old client rows, completed deployments, credential audit history and
  session history. Mark them permanently as `deleted` with
  `deleted_reason=clientflow_1244_identity_decommissioned` and append two
  critical audit records without secrets.
- The existing REST restore, client-secret rotation, client-update and purge
  endpoints reject these tombstoned IDs. The new installs must claim **new
  backend client IDs** and newly provisioned credentials. Do not reuse the
  historical IDs or restore their rows.
- Independent post-commit read-back must find **zero** active credentials,
  session grants, sessions or provisioning/resume tokens for those IDs.
- Repeat execution is a non-mutating idempotent audit when both clients are
  already completely decommissioned; partial or inconsistent states fail closed.

## Operator sequence – not authorized merely by merging

1. Merge only after green full GitHub CI and green Render smoke; verify live
   Render deployment commit matches main. Verify fresh-install pause remains `1`.
2. Execute the read-only preflight in Render Shell as `display_app`:

   ```bash
   cd /opt/display
   gosu display_app env \
     PYTHONPATH=/opt/display/backend:/opt/display \
     DATABASE_URL="postgresql:///display?host=/run/display-postgres" \
     python3 scripts/decommission_clientflow_1244_old_identities.py \
     --artifact-dir /var/data/clientflow-release-artifacts/store
   ```

   Require `CLIENTFLOW_1244_IDENTITY_DECOMMISSION=READ_ONLY_PASS`, the exact
   client IDs/names and no active enrollments/deployments. Do not print hashes,
   keys, session tokens or enrollment codes.
3. Separately review operator authorization, physical-wipe confirmation and
   dependency state; only then run the same command with the three approval
   flags:

   ```text
   --confirm-decommission
   --confirm-physical-wipe
   --approval-reference CF-1244-OLD-IDENTITY-DECOMMISSION-20261111
   ```

   Require `CLIENTFLOW_1244_IDENTITY_DECOMMISSION=PASS` and independent
   postflight with every active count `0` for both historical IDs. The script
   commits the operation **only** if both clients can be completed atomically.
4. Keep `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` until a separately authorized
   end-to-end enrollment readiness review and fresh-install smoke test have
   passed. Reopen installs via the normal reviewed Render change only.
5. Reinstall Ubuntu 26.04 LTS and fresh ClientFlow 1.3.43 first on Viborg2,
   physically accept OS/package recovery, boot, browser/Wayland, Display,
   Calendar, Livestream, Remote Desktop, Terminal and reconnect. Then repeat on
   Heidi1 and only thereafter begin onboarding new clients.

## Data and integration boundaries

The script never deletes `client`, `clientflow_deployment`, `clientflow_deployment_event`,
`terminal_session`, `remote_desktop_session`, historical credential rows,
`audit_logs` or any client release TAR. It never changes fresh-install
suspension. Shared status/command and isolated domain models remain
operationally independent.

Do not use `/clients/{id}/purge` or the normal trash route to substitute for
this transaction. Do not infer physical wipes from `client_version IS NULL` or
`last_seen_at` in the backend.
