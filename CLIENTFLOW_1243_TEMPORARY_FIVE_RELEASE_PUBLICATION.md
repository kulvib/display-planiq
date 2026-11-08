# ClientFlow 1.3.42 / 1243 – temporary five-release publication bridge

**Scope:** A narrow, separately authorized, non-destructive **publication-only** exception. The permanent policy remains **the latest 3 approved releases**. No code in this branch deletes a bundle, changes the release catalog, enrolls a client, enables automatic rollout or authorizes manual rollback.

## Verified starting point (2026-11-08)

- Render `store` has four approved bundles: 1.3.38/1239, 1.3.39/1240, 1.3.40/1241, 1.3.41/1242. Each size and SHA-256 is pinned in `scripts/clientflow_1243_transition_policy.py`.
- Offsite GitHub release assets exist for 1239 through 1242. **GitHub tags alone do not prove artifact identity.** SHA-256 must match the approved bytes on every recovery/download. GitHub releases may be mutable.
- 1.3.42/1243 has an approved GitHub Release TAR, SHA-256 `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`, size `223610880`, source `b870cf8c3fa90286c6b4dccaae593eb8a0d57565`, approval `CF-1.3.42-1243-VIBORG2-PILOT-20261107`.
- `clientflow_release_catalog.json` deliberately remains at sequence 1242, stable/default/fresh 1.3.38, with **no** 1.3.42 entry. This must not be changed until the approved 1243 bundle exists in the authoritative Render store.
- Viborg2 (backend ID 2) has locally recovered 1.3.38 but must be reverified physically before any update; `clientflow-updater.timer` remains stopped. Heidi1 (ID 1) is excluded. Database `client.client_version = NULL` for both is NOT proof of the installed version.
- Latest database check: no active deployments; enrollment token ID 4 was bound to 1.3.38 and expires 2026-11-09. Do not delete this binding, assume its expiration, or silently rebind it. Suspend fresh installs before publication and recheck live database state immediately before any operational action.
- 1.3.41/1242 experienced a local activation/recovery failure; keeping it in storage does not authorize it as a safe rollback destination.

## Code changes and boundaries

The normal publisher and `plan_publication()` continue to reject exceeding **three approved bundles**. A **dedicated explicit opt-in** (`--authorize-1243-five-release-transition`) is supported only when all conditions are true:

1. `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` is in the current Render environment. Both enrollment creation and token consumption must remain blocked during the bridge.
2. **All** `CLIENTFLOW_1241_PILOT_CLIENT_ID`, `CLIENTFLOW_1242_PILOT_CLIENT_ID`, `CLIENTFLOW_1243_PILOT_CLIENT_ID` are absent/empty; this is not a client pilot authorization.
3. Existing inventory contains **exactly four** intact, independently verified 1239–1242 bundles with the pinned SHA-256 and size. A fifth existing, different release, unknown version or different digest fails closed.
4. Incoming artifact is **exactly** approved `clientflow-1.3.42-seq-1243`, with pinned SHA-256, size, source and approval provenance. The existing publisher's immutable no-replace handling, `O_NOFOLLOW`, file-descriptor checks, disk-reserve checks and exclusive publication lock remain active.
5. Independent post-publication verification requires **exactly the original four plus 1243**, all verified. The resulting five-bundle inventory explicitly reports `within_approved_limit=false` and **requires later cleanup**. There is no automatic deletion.

The exception may not be reused to publish 1244, skip 1243, alter a legacy SHA, change client permissions, or make a newer version installable. Ordinary release-publication paths remain strict.

## Operational sequence (NOT executed by merging this branch)

1. Merge only after all GitHub CI is green and Render smoke test passes. Inspect that `main` and live Render deployment commit match.
2. Check the exact GitHub asset again and the live authorized-deployment/enrollment database counts. Ensure old local recovery on Viborg2 and the independent GitHub 1239/1240 archives remain available. Verify no active install/download/recovery uses the old artifacts. Do not reset the previously observed anti-rollback sequence 1242.
3. Set Render `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1`; leave 1241/1242/1243 pilot flags **unset**. Confirm the suspension in live service configuration and re-run smoke test for unaffected existing client flows.
4. From Render Shell, as `display_app`, run the read-only preflight:

   ```bash
   cd /opt/display
   gosu display_app env PYTHONPATH=/opt/display/backend:/opt/display \
     python3 scripts/preflight_clientflow_1243_transitional_publication.py \
     --artifact-dir /var/data/clientflow-release-artifacts/store
   ```

   Require `CLIENTFLOW_1243_TRANSITION_PREFLIGHT=READ_ONLY_PASS`. This checks **neither** live database dependencies **nor** the independent GitHub archive: those are separate operator checkpoints.
5. Acquire **exact approved** `clientflow-approved-1.3.42-1243.tar` from the verified GitHub Release, into a secure staging path **outside** the active store. Independently compute its SHA-256 and confirm `ee35cc6c...8d6914`. Ensure staging plus immutable publication copy leave at least 64 MiB of free disk. Never use the runtime-input transport TAR as an approved release.
6. Only after the distinct operator approval of this bounded transition, invoke the existing publisher with normal exact SHA/source/approval flags **and** `--authorize-1243-five-release-transition`. Require `RELEASE_STORE_POSTFLIGHT=PASS`, `CLIENTFLOW_1243_TRANSITION=VERIFIED_FIVE_TEMPORARY`, and `RELEASE_APPROVED_LIMIT_MET=NO` (expected temporary state).
7. Stop before enabling any pilot: in a separately reviewed catalog change, add approved 1243 as a non-installable 1.3.38→1.3.42 update-only entry, preserving the 1.3.38 stable/default/fresh selector until independent physical acceptance. Full CI + smoke first. Explicit physical Viborg2 checks and separate manual authorization are required before any updater timer can start.
8. After successful physical testing (including an isolated rollback-failure test), decide the fresh-install default based on supported approved installation modes. Handle expired/unused enrollment bindings and offline clients. Only then authorize oldest-first deletions, one at a time, with the existing prune tool and independent no-dependency attestation. End with **exactly 1241, 1242, 1243**. Recheck `retention_ready=true` after cleanup. 1239/1240 remain accessible via verified GitHub releases/local recovery where applicable.

**STOP on any mismatch.** No attempted `--confirm-prune`, catalog promotion, deployment, reboot, rollback or release replacement in this source-only phase.
