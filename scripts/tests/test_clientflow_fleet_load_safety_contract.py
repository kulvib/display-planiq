"""No-dependency CI guard for the isolated fleet load rehearsal."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_fleet_load_is_ci_only_with_isolated_database_and_no_external_host():
    source = (ROOT / "backend/tests/test_clientflow_fleet_capacity_ci.py").read_text()
    assert 'os.environ.get("GITHUB_ACTIONS") != "true"' in source
    assert 'parsed.host not in ("localhost", "127.0.0.1")' in source
    assert 'parsed.database != "planiq_ci"' in source
    assert 'parsed.port != 5432' in source
    assert 'schema_translate_map={None: schema}' in source
    assert 'CREATE SCHEMA' in source and 'DROP SCHEMA' in source
    assert "TRUNCATE" not in source
    assert 'SIZES = (5, 10, 15)' in source
    assert 'await asyncio.gather(' in source
    assert 'credentials[domain] = credential_id' in source
    assert 'cross_domain.status_code in (401, 403)' in source
    assert 'response.status_code in (401, 403)' in source
    assert 'event.listen(engine, "before_cursor_execute"' in source
    assert 'event.listen(engine, "checkout"' in source


def test_fleet_load_has_explicit_required_ci_gate():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'Execute isolated 5 / 10 / 15 ClientFlow fleet load gate' in ci
    assert 'python -m pytest -s -q backend/tests/test_clientflow_fleet_capacity_ci.py' in ci
    assert '--ignore=backend/tests/test_clientflow_fleet_capacity_ci.py' in ci
    assert (ROOT / "CLIENTFLOW_FLEET_CAPACITY_CI_20261016.md").is_file()
