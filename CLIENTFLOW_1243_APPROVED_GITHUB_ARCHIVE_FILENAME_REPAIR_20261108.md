# ClientFlow 1.3.42/1243 – approved GitHub asset filename repair

## Failure and exact observed state

The initial `release-archive-approved.yml` workflow on 2026-11-08 created the expected transport-only GitHub prerelease, but failed in its final postflight because `gh release create "$TAG" "$ASSET_PATH#$ASSET_NAME"` treats `#name` as a *label* rather than as an uploaded asset filename. GitHub therefore stored exactly one asset named `clientflow-approved.tar` rather than `clientflow-approved-1.3.42-1243.tar`.

- Existing tag: `clientflow-1.3.42-1243-approved-transport`
- Existing target commit: `b870cf8c3fa90286c6b4dccaae593eb8a0d57565`
- Existing GitHub asset ID: `724299785`
- Exact reported GitHub asset size: `223610880` bytes
- Exact reported SHA-256: `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`
- Canonical approval run: `42391389115`
- Canonical approval reference: `CF-1.3.42-1243-VIBORG2-PILOT-20261107`

There is **no evidence of TAR corruption**, and the existing release must not be deleted or rebuilt merely to fix this filename mismatch.

## Code correction

1. The workflow still checks main CI, the *original successful approval run*, the downloaded handoff's approval record, full TAR and embedded payload/installer hashes.
2. If the archive release is not yet present, it verifies the tag does not exist, stages the approved TAR under its canonical filename, independently verifies the staged copy's bytes, and creates a new transport-only prerelease without replacing any existing asset.
3. If the tag already exists, it checks **exact** tag, source commit, prerelease flag, exactly one asset, upload state, asset ID, approved size and exact SHA-256. Only the known legacy handoff filename `clientflow-approved.tar` is eligible for the metadata-only `PATCH` name change.
4. A final independent read of GitHub's release metadata must show **one asset with the canonical filename and the original exact digest and size**, or the workflow fails closed.
5. Other existing tags, unexpected files, mismatched digests, incomplete assets, different source commits or unrelated releases remain blocked. The patch cannot publish to Render or authorize a deployment, catalog promotion, or rollback.

## Operational recovery

After merge and green main CI, run the `Archive exact approved ClientFlow bundle to GitHub Release` workflow **again on current `main`** with:

- `approval_run_id`: `42391389115`
- `expected_source_sha`: `b870cf8c3fa90286c6b4dccaae593eb8a0d57565`
- `expected_approved_sha256`: `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`
- `expected_approval_reference`: `CF-1.3.42-1243-VIBORG2-PILOT-20261107`
- `confirm_archive`: `true`

Expected `APPROVED_GITHUB_RELEASE_ARCHIVE=PASS`. Do **not** use 'rerun failed jobs' on the old workflow attempt: that may rerun the older workflow definition. Do not manually delete assets, tags, or archive records.
