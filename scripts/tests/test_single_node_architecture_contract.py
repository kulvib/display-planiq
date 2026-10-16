"""Contracts for the alternative one-service, no-Neon Display architecture.

These tests validate topology and trust boundaries; the Docker smoke workflow
verifies executable PostgreSQL migrations and restart persistence.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / 'backend/Dockerfile.single-node').read_text(encoding='utf-8')
START = (ROOT / 'backend/scripts/start_single_node.sh').read_text(encoding='utf-8')
BLUEPRINT = (ROOT / 'render-single-node.yaml').read_text(encoding='utf-8')
WORKFLOW = (ROOT / '.github/workflows/single-node-smoke.yml').read_text(encoding='utf-8')


def test_postgresql_kept_and_runtime_built_with_locked_dependencies():
    assert 'FROM postgres:18.4-bookworm' in DOCKERFILE
    assert 'FROM python:3.13.16-slim-bookworm' in DOCKERFILE
    assert '--require-hashes --no-cache-dir' in DOCKERFILE
    assert 'COPY backend/' in DOCKERFILE
    assert 'ENTRYPOINT ["/opt/display/backend/scripts/start_single_node.sh"]' in DOCKERFILE


def test_local_db_is_unix_socket_only_and_has_separate_non_superuser_app_role():
    assert "listen_addresses=" + chr(39)*2 in START
    assert 'unix_socket_permissions=0770' in START
    assert 'unix_socket_group=display_app' in START
    assert '--auth-local=peer' in START
    assert 'CREATE ROLE display_app LOGIN' in START
    assert 'CREATE DATABASE display OWNER display_app' in START
    assert 'gosu "$APP_USER" python -m uvicorn' in START
    assert 'gosu postgres pg_ctl' in START
    assert 'export DATABASE_URL="postgresql:///' in START
    assert 'gosu "$APP_USER" python scripts/run_migrations.py' in START
    assert 'MIGRATION_ALLOW_EMPTY_DATABASE=false' in START
    assert 'MIGRATION_ALLOW_EMPTY_DATABASE=true' in START
    assert 'PG_VERSION' in START and 'refusing destructive initialization' in START
    assert 'chmod 0777' not in START


def test_single_node_blueprint_has_exactly_one_paid_service_and_no_neon_secret():
    assert re.search(r'(?m)^- type: web$', BLUEPRINT)
    assert BLUEPRINT.count('type: web') == 1
    assert 'runtime: docker' in BLUEPRINT
    assert 'plan: starter' in BLUEPRINT
    assert 'numInstances: 1' in BLUEPRINT
    assert 'dockerfilePath: ./backend/Dockerfile.single-node' in BLUEPRINT
    assert 'mountPath: /var/data/clientflow-release-artifacts' in BLUEPRINT
    assert 'sizeGB: 5' in BLUEPRINT
    assert 'CLIENTFLOW_RELEASE_ARTIFACT_DIR' in BLUEPRINT
    assert 'DATABASE_URL' not in BLUEPRINT
    assert 'preDeployCommand' not in BLUEPRINT
    assert 'databases:' not in BLUEPRINT
    assert 'api.display.planiq.dk' not in BLUEPRINT or 'domains:' not in BLUEPRINT


def test_ci_executes_real_schema_and_restart_not_prod():
    assert 'runs-on: ubuntu-latest' in WORKFLOW
    assert 'docker build --file backend/Dockerfile.single-node' in WORKFLOW
    assert '127.0.0.1:18000:10000' in WORKFLOW
    assert '/health/db' in WORKFLOW
    assert 'ci_persistence_marker' in WORKFLOW
    assert 'docker stop --time 90' in WORKFLOW
    assert 'SINGLE_NODE_SMOKE_OK' in WORKFLOW
    assert 'NEON_API_KEY' not in WORKFLOW
    assert 'api.display.planiq.dk' not in WORKFLOW
    assert 'docker rm -f display-single-node-ci' in WORKFLOW


def test_original_neon_render_blueprint_and_ci_tests_are_not_weakened():
    original = (ROOT / 'render.yaml').read_text(encoding='utf-8')
    assert 'runtime: python' in original
    assert 'preDeployCommand: "python scripts/run_migrations.py"' in original
    assert "- key: DATABASE_URL\n        sync: false" in original
