# PlanIQ Display 61B-2B – CI correction (2026-11-16)

## Apply

Upload the **four files** from this archive to the **existing** GitHub branch:
`feature/display-61b2b-offline-fullscreen-20261116`
Preserve their relative paths. Do not merge or redeploy before all required GitHub CI jobs pass.

## Changes

1. Fullscreen reader test: simulate root ownership of the temporary files while preserving the real security checks (`O_NOFOLLOW`, `st_uid == 0`, restrictive permissions, validated schema, and recovery on corrupt state). Added explicit negative checks for a non-root-owned directory and marker. Production reader not modified.
2. Ubuntu 26.04 preclaim executable probe: verify the locked APT artifact from Canonical as before. When the ephemeral GitHub runner has a newer installed apt than the pinned approved artifact, call the real production recovery guard and require it to reject a downgrade **without removing apt-get**. On a runner with equal/older apt, preserve the destructive executable recovery proof. Curl restoration probe remains mandatory in both cases. The production recovery guard and pinned artifact remain unchanged.
3. Regression tests for the newer-apt guard and malformed runner/version identity.
4. SHA256 manifest updated; two pre-existing security-critical CI scripts that were absent from the manifest are newly covered. 593/593 entries.

## Verified locally

- 57 focused regression tests passed (including CI workflow and manifest checks).
- 7 fullscreen tests passed **as unprivileged `nobody`**.
- Python syntax compiled successfully.
- 593/593 SHA256 entries pass.

## CI gate

A full backend test run could not collect locally because the container lacks `passlib`. The GitHub Ubuntu 26.04 preclaim destructive host job is **not** executable in this container; it must run on GitHub Actions. CI remains required. Neither source release 1.3.44/1245 nor platform-input lock, Docker/Render settings, approval gates or migrations were changed.
