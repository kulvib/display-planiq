# PlanIQ Display

Canonical source repository for **PlanIQ Display**, a general-purpose platform for digital screen management, and its ClientFlow client runtime.

The repository is under active construction and review. The goal of the v2 baseline is to represent the currently validated architecture directly, without historical installer overlays or legacy control-plane paths.

## Repository layout

```text
.
├── backend/                  FastAPI backend, Alembic migrations and tests
├── frontend/                 React/Vite frontend and tests
├── client/
│   ├── runtime/              Canonical ClientFlow runtime source
│   ├── systemd/              Canonical systemd definitions
│   ├── sysusers.d/           ClientFlow system-user definitions
│   ├── tmpfiles.d/           Runtime/state directory definitions
│   ├── config-examples/      Installed configuration templates
│   ├── libexec/              Fixed-function privileged helpers
│   └── release/              Release transaction, builder inputs and docs
├── scripts/                  Repository/release validation and build tools
├── render-single-node.yaml   Docker backend topology reference (not a live-state export)
└── render.yaml               Historical external-DB blueprint; not the active backend
```

## Runtime domains

ClientFlow has separate functional/security domains:

- Status
- Display
- System
- Livestream
- Terminal
- Remote Desktop

Status, Display and System share the reviewed shared-domain control plane. Livestream, Terminal and Remote Desktop own isolated credentials and runtime/session state.

The physically validated Livestream, Terminal and Remote Desktop runtime behavior is treated as frozen baseline. Structural changes around packaging, provisioning or shared infrastructure must not change their functional runtime behavior without a documented root cause and physical regression test.

## Active deployment architecture

The active Display backend uses Render Docker (`backend/Dockerfile.single-node`) with local PostgreSQL 18.4 on a persistent disk. `backend/scripts/start_single_node.sh` fixes the database URL to a local Unix socket, starts PostgreSQL without TCP, uses a non-superuser application role and runs Alembic before the API starts. The React frontend is a separate Render static service. Display does not use Neon in the active topology.

Neither checked-in Blueprint is a live export of the existing Render services. `render.yaml` is retained as historical external-database infrastructure evidence, not instructions to provision a new service. `render-single-node.yaml` is a backend topology reference; do not apply either file to the active workspace without a reviewed reconciliation. No additional paid service is implied.

The operational baseline is ClientFlow 1.4.0 / 1250 on Viborg1 (client 3). The 1.4.1 / 1251 source is staged only: it is not published, authorized or physically accepted. See `CLIENTFLOW_1.4.1_1251_CANDIDATE_STAGE.md`. The old catalog and fleet/fresh-install holds remain in place. Backend restart can interrupt long-lived connections; recovery and physical acceptance remain explicit gates.

## Database

Alembic is authoritative for schema changes. Application startup must not create or mutate database schema implicitly.

Run migrations from `backend/` through:

```bash
python scripts/run_migrations.py
```

The canonical shared-foundations base is `20260819_50a_canonical`. Determine the current repository head from Alembic rather than copying an old revision into operational instructions. The reviewed 61A migration defines `20261115_61a_cf_release_admin`. `/health/db` checks readiness against the running source. The Docker startup owns migrations; do not run an additional live migration or point Display at an external database as part of routine deployment.

## ClientFlow release model

ClientFlow uses a keyless runtime-release model with explicit fresh-install and in-place-update modes:

- source version: `client/VERSION`
- monotonically increasing sequence: `client/release/release-input.json`
- canonical runtime wheel is rebuilt from `client/runtime/` for every release candidate
- source-independent Python/runtime platform inputs are packaged by the deterministic `scripts/build_clientflow_runtime_input_transport.py` helper and must match `client/release/runtime-platform-inputs.lock.json` byte-for-byte
- canonical release builds run in `.github/workflows/release-build.yml` from an exact CI-green source SHA with a pinned Python/pip/setuptools build toolchain
- two independent GitHub runners must produce byte-identical release output before an unapproved candidate is handed to the separate approval gate
- release candidates are non-deployable by default
- manifest schema 8 declares `artifact_type: runtime_release`, explicit `install_modes`, and the exact fresh-installer file/size/SHA-256
- backend deployment authority is derived from the exact approved bytes published in `CLIENTFLOW_RELEASE_ARTIFACT_DIR`
- artifact download requires a deployment-bound, DPoP-bound updater authorization; legacy System-domain bearer tokens are not accepted
- a separate explicit approval step binds approval to the exact candidate SHA-256, source commit, and fresh-installer SHA-256
- installation/activation is manual; no automatic reboot or automatic activation is permitted

See:

- `client/release/docs/CLIENTFLOW_RELEASE_AND_ROLLBACK.md`
- `client/release/docs/CLIENTFLOW_INSTALLATION.md`
- `CLIENTFLOW_RELEASE_PROCEDURE.md`

## Development checks

Backend source-contract checks:

```bash
python -m pytest -q backend/tests/test_*source*.py
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run audit:dependencies
node --test tests/*.test.mjs
npm run build
```

Client runtime/release code should compile before a release candidate is built:

```bash
python -m compileall -q client/runtime client/release/lib scripts backend/service1 backend/migrations
```

## Review principle

Actual source code is the implementation source of truth. Physical Ubuntu tests are the source of truth for observed runtime behavior. Documentation supports the review but does not override working, physically verified behavior.

Changes to runtime behavior require a documented category A/B finding, root cause and relevant regression plan. Production-readiness hardening is handled separately from the current correctness/isolation review.

## Quality and operations

See `docs/PLANIQ_DISPLAY_68J8_QUALITY_REVIEW.md` for the scoped findings, evidence and open acceptance gates. A green CI run does not replace physical media or recovery tests. An isolated CI backup restore is not a verified off-host restore of the actual database. Retain immutable historical release evidence; do not remove files merely because they are old.
