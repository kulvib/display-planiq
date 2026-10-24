# ClientFlow 1242+ – durable reporting of centrally signed manual rollback

**Development candidate only.** No Render changes, new releases, key provisioning, backend rollout, or client activation are performed by this branch.

## Trust boundary and crash guarantees

A verified manual rollback with a non-null, centrally signed `permit_id` records its unique, deterministic `succeeded` event in the **same root-owned, fsynced `release/state.json` commit** that marks `active_release_id` as the target. A crash before this atomic commit cannot claim success; a crash immediately after it cannot lose the event. No secret, operator reason, signing material or release journal is copied to the unprivileged updater.

A root-only `planiq-rollback-outbox-export.timer` (separate from versioned `clientflow*` managed definitions) runs a restricted, offline-only service. It checks the root-only rollback consumption journal, then publishes only `permit_id`, deterministic `event_id`, `outcome`, UTC `occurred_at` and `to_release_id` as root-owned/group-readable JSON under `/var/lib/planiq-rollback-outbox`. The dedicated systemd `StateDirectory` provisions this location as root:`clientflow-updater` (0750) before applying the confined ExecStart, without changing `/var/lib/clientflow` ownership or modes. Publication is atomic and fsynced, idempotent, never consumes the authoritative root event and rejects edits to an already committed export. The timer survives a rollback to 1.3.40.

The existing **non-root** `clientflow-updater` uses the unchanged authenticated Update credential, TLS and DPoP transport to submit the receipt to the existing `/api/clientflow-update/rollback-permits/{permit_id}/events` endpoint. It records a private, fsynced acknowledgement only after an authenticated outcome-matching `status=succeeded` or `status=failed` response (including a server-side idempotent replay). An HTTP 409 while the Status agent has not yet confirmed the target remains pending and retries on the next timer tick. Other HTTP/network failures do **not** acknowledge the event, are visible in the updater journal, and cause a subsequent retry. Backend still checks client, credential, status, outcome and event uniqueness.

## Essential old-to-new activation bridge

A 1.3.40 root update controller invokes **its own old transaction code**, not code from a staged 1.3.41 candidate. For that reason new releases carry `clientflow-stable-rollback-promote.service`, required and ordered before successful startup of the **new `clientflow.target`**. Its ExecStart uses the *new active release's* transaction entry point `promote-rollback-host`. It validates the new immutable release tree, copies the matching stable updater PYZ from the verified release payload, creates the standalone non-`clientflow*` outbox service/timer and enables the exporter before the target health gate can succeed. The new promoter does not acquire the old controller's transaction lock. A failed promotion blocks target health and the old controller must restore the previous release.

The promotion marker is root-protected and monotonic; an older source release cannot downgrade a more recent already promoted stable updater. The standalone timer and stable PYZ are outside the directories replaced by legacy `_apply_definitions` during rollback. A fresh 1.3.41 installation uses the same health-gated activation bridge; pending, unapproved first installations do not run the promoter.

## Operational acceptance required before 1242 publication

1. All GitHub CI gates including Ubuntu 26.04 host executable proof and PostgreSQL/backend HTTP integration must be green. Confirm new `clientflow.target` requires and waits for the promotion unit with systemd 259.
2. Explicit approval of the Ed25519 trust keys and signed rollback policy. Keep private signing material in the backend environment, **never in Git, ZIP, or immutable client payload**. New 1242 bundles must pass existing trust/build gates.
3. On a *pilot* Ubuntu 26.04 client, update from 1.3.40 using the **old** privileged controller. Confirm stable PYZ checksum matches the staged 1242 payload and root exporter timer is enabled independently of active release.
4. Issue one signed rollback to the immediate predecessor. Simulate power loss at both sides of the root state commit; verify no false success and eventual export/retry after reconnect. Verify the old 1.3.40 runtime becomes active but the new stable updater and exporter remain installed.
5. Hold Status offline and verify backend HTTP 409 does not mark the receipt acknowledged. After Status confirms the target, require authenticated server success and durable local ack. Reboot twice and verify no duplicate terminal audit event. Test expired/invalid permit, rejected/changed receipt, invalid Update credential and TLS error.
6. Confirm 1.3.40 / 1.3.38 immutable releases and the current stable catalog remain unchanged. Release publication, rollout and Render activation require a separate operator decision.

## Known operational boundary

The exporter retains the root journal as the authority and the updater retains completed acknowledgements; per-client accumulation is bounded by 10,000 rollback receipts and is deliberately **not** silently pruned. Exhaustion is a fail-closed operational condition requiring separate audited maintenance. Old pre-1242 *wipe* code does not know about the independent `planiq-rollback-outbox-export.*` units; perform post-1242 wipe/cleanup through a current approved lifecycle procedure, and do not consider an older release's wipe to be a complete post-1242 deprovisioning.

No automatic success report is emitted for unsigned historic rollbacks, incomplete rollback transactions or activation requests without a verified central permit. A *terminal* failed signed rollback is reported as `failed` without requiring the target Status version; unresolved in-flight transactions are not reported as completed. The backend may receive an offline rollback report after revocation; it records what happened, **not** retroactive authorization.
