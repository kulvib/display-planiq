PlanIQ Display — 61B-1 FK insertion-order production hotfix (2026-11-16)

Source of truth: display-planiq-main(20261115-181059).zip

New branch from main:
  fix/display-61b1-draft-fk-order-20261116

Upload only the three files in their original repository paths:
  backend/service1/routers/clientflow_release_administration.py
  backend/tests/test_clientflow_release_admin_61a_http.py
  SHA256SUMS.txt

Root cause candidate confirmed by SQLAlchemy FK-order reproduction:
  Parent ClientFlowRolloutWave and child ClientFlowRolloutTarget were added
  together without a relationship or explicit flush. SQLAlchemy may INSERT
  target before wave, violating PostgreSQL's non-deferrable wave_id FK.
  The new session.flush() inserts the parent first inside the same transaction.

Regression: ASGI HTTP test records SQL INSERT order and requires wave before
  target; remains default-closed (no deployments, no cutover, no fleet).

No migration, releases, Render environment, or client-side changes.

Validation completed locally: AST parse, SHA256 of all 585 manifest paths,
  and minimal real SQLite foreign-key order demonstration.
Full repository integration tests could not run locally (sqlmodel unavailable).
Use green GitHub CI as gate before merge, then Render redeploy and smoke.

Once deployed, re-try one inert draft and verify that it appears in history,
  then review/pause/resume/cancel and check all gates still closed.
