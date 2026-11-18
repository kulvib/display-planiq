# GitHub upload · PlanIQ Display · Fase 63D-4

- **Base:** fresh `display-planiq-main(20261118-115838).zip`, GitHub `main` `bc7adef9fec4f4f4bc8382a5a9d212b71b9a9085`.
- **Branch:** `feature/display-63d4-1246-approved-pilot-staging-20261118`.
- Upload changed/new files from this ZIP to that branch, preserving paths. Do not overwrite the ZIP root or GitHub Actions workflow.
- Scope: exact 1246 archive lock; fail-closed, client-3-only route guard; inactive 1246 update-only pilot catalog stage (1245 stays stable); readonly admin stage; offline TAR verification and negative tests.
- The current 1245 active catalog, authenticated deployment behavior for existing releases, existing 1245 pilot flags and release bytes stay unchanged.
- **Absolutely no automatic artifact publication, catalog cutover, fresh install, pilot activation, fleet rollout, or physical acceptance.**
- Full GitHub CI must pass before merge. Run an explicitly approved offline TAR preflight and future Render-store audit before proposing a catalog transition. Do not authorize pilot merely because CI is green.

See `docs/PLANIQ_DISPLAY_63D4_1246_APPROVED_ARCHIVE_PILOT_STAGING_20261118.md`.
