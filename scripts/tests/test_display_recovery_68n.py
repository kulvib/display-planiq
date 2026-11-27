"""68N-B1 offline fixtures; no production DB, Docker or secret material."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_recovery_68n as recovery


def test_reviewed_profile_is_exact():
    p, rows = recovery.profile()
    assert p["revision"] == 3
    assert p["migration"] == "20261115_61a_cf_release_admin"
    assert p["stable_release_id"] == "clientflow-1.4.1-seq-1251"
    assert set(rows) == {"clientflow-1.3.47-seq-1248.tar",
                         "clientflow-1.4.0-seq-1250.tar", "clientflow-1.4.1-seq-1251.tar"}
    assert rows[p["stable_release_id"] + ".tar"] == (
        "835610b0a59510b2119601468ad47c0aa1fb418b96c4cfaaa8cdd81042dc1ab6", 223897600)
    assert "revision = 3" in recovery.policy_sql(p, rows)
    with pytest.raises(recovery.RecoveryStop, match="UNKNOWN_PROFILE"):
        recovery.profile("unreviewed")


@pytest.fixture
def stage(tmp_path):
    p, rows = recovery.profile()
    root = tmp_path / "stage"
    root.mkdir(mode=0o700)
    (root / "releases").mkdir(mode=0o700)
    def write(path, data):
        path.write_bytes(data)
        path.chmod(0o600)
        return hashlib.sha256(data).hexdigest(), len(data)
    fixture_rows = {name: write(root / "releases" / name, name.encode()) for name in rows}
    digest, size = write(root / "database.pgdump", b"PGDMP synthetic fixture")
    manifest = dict(schema="planiq-display-62b-backup-staging-v1",
                    stable_release_id=p["stable_release_id"],
                    stable_sha256=fixture_rows[p["stable_release_id"] + ".tar"][0],
                    db=dict(filename="database.pgdump", format="pg_dump_custom", sha256=digest, size=size),
                    releases=[dict(filename=name, sha256=sha, size=size)
                              for name, (sha, size) in fixture_rows.items()],
                    backup_offsite_verified=False, backup_restored_to_isolated_postgres=False,
                    database_cutover_authorized=False, deployment_authorized=False)
    write(root / "manifest.json", json.dumps(manifest).encode())
    return root, p, fixture_rows, manifest


def test_exact_stage_does_not_claim_restore_or_authority(stage):
    root, p, rows, _ = stage
    result = recovery.verify_stage(root, p, rows)
    assert result["retained_release_count"] == 3
    assert result["stage_bytes_verified"] is True
    assert result["isolated_database_restore_verified"] is False
    assert all(result[key] is False for key in recovery.FALSE_GATES)
    with pytest.raises(recovery.RecoveryStop):
        recovery.verify_stage(root, *recovery.profile())


@pytest.mark.parametrize("attack", ["wrong_stable", "missing", "extra", "duplicate",
                                   "digest", "forged_restore", "tampered_dump", "symlink",
                                   "public_file", "duplicate_json"])
def test_negative_stage(stage, attack):
    root, p, rows, manifest = stage
    path = root / "manifest.json"
    if attack == "wrong_stable":
        manifest["stable_release_id"] = "clientflow-1.4.0-seq-1250"
    elif attack == "missing":
        manifest["releases"].pop()
    elif attack == "extra":
        manifest["releases"].append(dict(manifest["releases"][0], filename="extra.tar"))
    elif attack == "duplicate":
        manifest["releases"][-1] = manifest["releases"][0]
    elif attack == "digest":
        manifest["releases"][0]["sha256"] = "0" * 64
    elif attack == "forged_restore":
        manifest["backup_restored_to_isolated_postgres"] = True
    elif attack == "tampered_dump":
        (root / "database.pgdump").write_bytes(b"PGDMP tampered")
    elif attack == "symlink":
        f = root / "releases" / next(iter(rows))
        f.unlink()
        f.symlink_to(root / "database.pgdump")
    elif attack == "public_file":
        (root / "database.pgdump").chmod(0o644)
    if attack == "duplicate_json":
        path.write_text('{"schema":"bad",' + json.dumps(manifest)[1:])
    else:
        path.write_text(json.dumps(manifest))
    with pytest.raises((RuntimeError, OSError, ValueError)):
        recovery.verify_stage(root, p, rows)


def test_restore_never_runs_on_live_host(stage, monkeypatch, tmp_path):
    root, p, rows, _ = stage
    monkeypatch.setattr(recovery, "MOUNT", tmp_path)
    monkeypatch.setattr(recovery, "run", lambda *a, **k: pytest.fail("Docker must not run"))
    with pytest.raises(recovery.RecoveryStop, match="LIVE_HOST_FORBIDDEN"):
        recovery.offline_restore(root, p, rows)


def test_pinned_source_refuses_modified_bytes(tmp_path):
    path = tmp_path / "pin.json"
    path.write_text('{"test":1}')
    with pytest.raises(recovery.RecoveryStop, match="SOURCE_PIN"):
        recovery.read_json(path, "0" * 64)


@pytest.mark.parametrize("restore_result", ["PASS", "STOP"])
def test_offline_restore_uses_local_disposable_docker_and_cleans_up(stage, monkeypatch, tmp_path, restore_result):
    root, p, rows, _ = stage
    monkeypatch.setattr(recovery, "MOUNT", tmp_path / "not-live")
    monkeypatch.setattr(recovery, "SOCKET", tmp_path / "no-socket")
    calls = []
    container = "a" * 64
    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert argv[:3] == ["docker", "--host", "unix:///var/run/docker.sock"]
        if argv[3] == "run":
            assert "--pull=never" in argv and argv[argv.index("--network") + 1] == "none"
            assert "-p" not in argv and "--mount" not in argv and "-v" not in argv
            return container
        if "pg_restore" in argv:
            assert kwargs["stdin"].read(5) == b"PGDMP"
            assert "--single-transaction" in argv and "--exit-on-error" in argv
        if "psql" in argv:
            assert "revision = 3" in argv[-1]
            return restore_result
        return ""
    monkeypatch.setattr(recovery, "run", fake_run)
    if restore_result == "PASS":
        evidence = recovery.offline_restore(root, p, rows)
        assert evidence["isolated_database_restore_verified"] is True
        assert evidence["offsite_verified"] is False
        assert evidence["deployment_authorized"] is False
    else:
        with pytest.raises(recovery.RecoveryStop, match="RESTORED_POLICY"):
            recovery.offline_restore(root, p, rows)
    assert calls[-1][3:] == ["rm", "--force", "--volumes", container]
