# ClientFlow: four approved bundles and Heidi1 1.3.38 → 1.3.40 rollback acceptance

**Status: code and synthetic gates only. NOT a live pruning authorization or physical acceptance.**

The sole current development client is Heidi1 / backend client ID 1. The source build
is ClientFlow 1.3.40 / sequence 1241. The physical controller bridge has passed
preflight and was applied while the active client remained 1.3.38. The 1.3.40
pilot flag remains **off** until independently authorized.

## Store policy: latest FOUR approved bundles, not four catalog selections

The approved-bundle limit applies to immutable `.tar` files physically present in
Render's configured persistent artifact store, **not** entries in the active
installation catalog or source Git history. It does not allow keeping an extra
fifth bundle simply because its release was problematic in the field. An
approved-but-field-failed release still counts until explicitly removed under
retention policy. Historical approval/deployment records remain immutable.

The inventory is ordered by **approved release sequence** (descending), not by
lexical filename, modification time or "stable" status. The current verified
snapshot reported five: 1.3.40/1241, 1.3.39/1240, 1.3.38/1239,
1.3.37/1238, 1.3.36/1237. Thus **only 1.3.36/1237** is a candidate for
removal from that snapshot. Reconfirm actual live inventory before acting.

- `scripts/audit_clientflow_release_retention.py` is read-only. The report
  includes `approved_count`, `approved_limit=4`, `within_approved_limit`,
  `protected_latest` and `older_review_only`. `--require-four` fails unless
  exactly four verified approved bundles remain. Its legacy `--require-three`
  argument is retained as a deprecated alias for the **four-bundle** gate.
- A new immutable publication **fails closed before writing bytes** if it would
  bring the approved store above four bundles, even when enough disk space
  exists. Concurrent publishers take an advisory exclusive directory lock to
  prevent simultaneous commits from exceeding the limit. Publication does NOT
  silently delete approved releases.
- `scripts/prune_clientflow_release_retention.py` is **read-only by default**.
  Destructive operation can remove **only the single oldest** verified approved
  bundle when exactly four or five exist, and only after an operator supplies its exact
  release ID and whole-bundle SHA-256 and explicitly attests that all offline
  clients, active downloads/deployments, future recoveries, and install needs
  have been reviewed. Its retention transaction uses the same directory lock,
  revalidates the approved store and file inode/hash, and independently verifies
  the remaining three or four. It does **not** autonomously discover offline clients;
  this limitation is why the attestation is mandatory.

### Next production safety gates (NOT executed by this branch)

1. Merge through green GitHub CI and verify the exact new `main` commit has
   automatically deployed on Render. Do not manually redeploy an auto-deploying
   service.
2. Run the **read-only** store audit. The existing five should give
   `approved_count=5` and `within_approved_limit=false`, not a false PASS of
   full compliance. Confirm version/SHA for each item.
3. Run the cleanup tool **without confirm flags**. Independently verify the
   single candidate against the store audit, catalog, live client inventory,
   all deployments, offline/recovery dependencies and retained backup/rebuild
   evidence. Never infer safety merely from the oldest sequence.
4. Obtain separate operator authorization specifically for deleting the named
   release/SHA. Only then provide both required confirmation flags to the
   cleanup tool. No automatic deletion in this phase.
5. Re-run `--require-four`: protected list must be **exactly** the latest four,
   with zero invalid bundles. Independently recheck all four SHA-256 hashes.
6. Before publishing the *next* release when four exist, repeat dependency
   review and explicitly clean up the fourth-oldest **first** (four to three),
   then publish the new verified release (three to four). A direct fifth publication is blocked;
   this preserves a strict four-bundle maximum, although it means publication
   can pause for safety instead of always proceeding automatically.

This first phase intentionally prioritizes never deleting an offline client's
only recoverable bundle. Full fleet-aware automatic retention is a later
architectural step and must be gated on proven client inventory, downloads,
rollback pins and storage dependency tracking.

## Important separation: rollback ≠ download of an older bundle

1. **Activation-failure recovery** is a local transaction path; a failed
   activation should restore a previous known healthy local release without
   requesting an older bundle from Render. Test a *controlled* health-check
   failure, not random file deletion or arbitrary disk corruption.
2. **Manual post-success rollback** is an explicit, root-authorized **local**
   operation to an already installed, immutable, provenance-bound release. It
   requires its exact `release_approval_reference` and an audit reason.
   `highest_release_sequence` must **not** be lowered.
3. **Remote downgrade** is NOT permitted by the 1.3.40 pilot. The backend
   release catalog still has `rollback_allowed=false`. Local rollback must not
   be confused with granting all users an online downgrade endpoint.
4. A deployment or local health check passing does not guarantee that a prior
   app version can read data modified by the new release. Verify schema and
   configuration compatibility before an operator initiates any rollback.

## Physical acceptance on Heidi1 (after separately authorized pilot deployment)

**Before update:** record `hostname`, `client/VERSION`, active symlink, local
`release/state.json` active/staged/previous IDs and highest sequence, active
controller sandbox and drop-in, active target/updater health, and the exact
immutable 1.3.38 release approval from the *installed state*, never from a
retyped guess. Check no activation intent or deployment is pending. Confirm
active release 1.3.38, highest 1240, staged 1.3.39, idle controller and the
verified bridge. Do not print credentials from state or config to the terminal.

**Test A – successful update:** separately authorize the single-client pilot
flag; manually create one backend deployment pinned to exact release
`clientflow-1.3.40-seq-1241`, SHA-256
`b63211454c9cee0f24277c51f0d13d75099729e641d13f9ce4ed9ad696468783`,
size 223518720, approval `CF-1.3.40-1241-20261021-f4a25bce`.
Monitor stage, activation, reboot, backend result, kiosk internet gate,
Chrome/Wayland/GUI, Control Room and terminal. Verify 1.3.40 really becomes
active and 1.3.38 remains installed. **No success is assumed in advance.**

**Test B – local manual rollback after success:** only if the installation
passed and the local machine is accessible, reconfirm no active deployment or
activation intent and the presence of the verified older 1.3.38 release tree.
Obtain its exact approval reference from the installed state and manifest.
The transaction entry point is:

```text
sudo /opt/clientflow/active/release/bin/clientflow-release-transaction rollback \
  --release-id clientflow-1.3.38-seq-1239 \
  --expected-release-approval-reference '<EXACT_INSTALLED_1338_APPROVAL>' \
  --reason 'Manual development rollback acceptance from 1.3.40'
```

**This is a real mutation: do not run it as part of a read-only preflight.**
The actual executable path must be reverified after Test A: the CLI available
in the active release may be elsewhere. Run its `--help` before committing.
The command may interrupt the remote terminal and ClientFlow services.
Afterward verify active 1.3.38, healthy kiosk/GUI/backend, same anti-rollback
highest sequence 1241, and a `manual_rollback` history event. Restart the host
and retest. The existing 1.3.40 bundle stays immutable and locally installed.

**Test C – automatic rollback:** conduct an isolated, controlled health-check
failure with validated fault injection in a **separate** test case after Test B.
The recovery outcome must be explicitly `rolled_back` / documented error, and
the original release must pass health. If both fail, do not claim success:
expect a fail-closed `recovery_failed` incident with the activation intent
preserved and a manual repair plan.

**Test D – re-update:** confirm whether a new forward update from the
restored 1.3.38 is allowed by version/sequence policy. A staged 1.3.40 at the
highest sequence cannot simply be re-staged under anti-rollback; the existing
approved immutable local release must be handled via a reviewed activation
path or a strictly newer sequence. Do not implement an anti-rollback bypass
merely to pass this test.

## Current test evidence and remaining gaps

Automated tests verify retention inventory, fifth-publication refusal,
operator-authorized oldest-only cleanup, race-preventing lock presence, and
synthetic manual rollback success/rejection/failure with the highest-sequence
invariant. These are software tests, **not** proof of field rollback on Heidi1.
The release publisher, approval, and existing auto-recovery tests remain in
CI. No deployment, rollback, Render deletion or catalog change is performed
by this repository change.
