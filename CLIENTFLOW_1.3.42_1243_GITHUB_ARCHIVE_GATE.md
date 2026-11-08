# ClientFlow 1.3.42/1243 — GitHub archive gate (no backend or kiosk activation)

## Purpose

The 1.3.42/1243 approved bundle already exists in the successful canonical approval workflow run (run ID `42391389115`). It is *not* yet an approved TAR asset in GitHub Releases. The previous 1.3.38–1.3.41 approved bundles already have GitHub transport-only release assets with independently verified SHA-256 digests.

This source-only change adds a **manual**, exact-byte, no-replace archival workflow: `.github/workflows/release-archive-approved.yml`. It operates on an already approved GitHub Actions artifact, not on a rebuild and not on a kiosk, and does not write to Render's artifact store.

## Exact handoff for 1.3.42/1243

| Field | Exact value |
|---|---|
| `approval_run_id` | `42391389115` |
| `expected_source_sha` | `b870cf8c3fa90286c6b4dccaae593eb8a0d57565` |
| `expected_approved_sha256` | `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914` |
| `expected_approval_reference` | `CF-1.3.42-1243-VIBORG2-PILOT-20261107` |
| `confirm_archive` | `true` only after reviewed main CI |

After this changes-only branch is merged and **main CI green**, dispatch on `main` and expect:

- `APPROVED_GITHUB_TRANSPORT_PREFLIGHT=PASS`
- `APPROVED_GITHUB_RELEASE_ARCHIVE=PASS`
- New, non-replace prerelease tag `clientflow-1.3.42-1243-approved-transport`
- One asset `clientflow-approved-1.3.42-1243.tar` with size `223610880` and GitHub API digest `sha256:ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`
- Tag target source SHA `b870cf8c3fa90286c6b4dccaae593eb8a0d57565`

The workflow verifies the approval-run event, successful conclusion, exact source commit and approval workflow path; downloads the original approved handoff using the run ID; verifies approval record, approval text, full approved TAR, embedded manifest, payload and installer hashes; refuses an existing tag or release; creates a prerelease; then independently validates GitHub's published asset digest/size/source target. A failure after creation must be diagnosed manually; the workflow never overwrites or deletes an existing tag or asset.

**This remains transport-only, NOT a publication gate, fresh-install selector, physical acceptance, rollback approval, or client update.** The GitHub Releases API currently reports the historical transport-only releases as `immutable: false`; retain independent digest verification when retrieving them.

## Follow-up safety gates (not implemented here)

1. The Render active store still holds four approved releases (1.3.38–1.3.41), above the newly locked three-release limit, and 1.3.38 is still the current backend stable/default fresh-install catalog target. The existing oldest-only prune script correctly refuses deleting that pinned release.
2. GitHub approved TARs for 1.3.38/1.3.39 have verified digests; same-disk Render recovery archives also exist. Before deleting any Render bundle, independently audit active and offline client dependencies, in-flight enrollment and deployment bindings and Viborg2's verified local 1.3.38 recovery. Externally retained assets alone do not authorize deletion.
3. Prepare and review an explicitly authorized, fail-closed transition that handles the active fresh-install catalog pin **before** deletion and the exact 1.3.42 immutable Render publication **before** 1243 catalog promotion. Do not bypass the three-release cap or the old 1.3.38 pin just to proceed; add a safe transition mechanism or explicitly halt if dependency/order invariants cannot be satisfied.
4. Keep `CLIENTFLOW_1243_PILOT_CLIENT_ID` absent/disabled and the Viborg2 updater timer stopped until a separately approved physical single-device test. Neither GitHub archival nor three stored releases proves manual rollback; manual rollback remains disabled and requires a separate reviewed release/test path.
