"""62A standard-library, filesystem-only storage preflight regression tests."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/display_62_storage_preflight.py"
spec = importlib.util.spec_from_file_location("display_62_storage_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
RELEASE = "clientflow-1.3.44-seq-1245"


def fixture(mount: Path):
    (mount / "postgres/data/base").mkdir(parents=True)
    (mount / "postgres/data/global").mkdir(parents=True)
    (mount / "postgres/data/pg_wal").mkdir(parents=True)
    (mount / "postgres/data/PG_VERSION").write_text("18\n")
    (mount / "postgres/data/global/pg_control").write_bytes(b"fixture only")
    (mount / "store").mkdir()
    (mount / "store" / f"{RELEASE}.tar").write_bytes(b"immutable fake test bytes")
    os.chmod(mount / "postgres/data", 0o700)
    os.chmod(mount / "store", 0o755)
    return hashlib.sha256(b"immutable fake test bytes").hexdigest()


def test_62a_is_explicitly_non_authorizing_and_validates_disk_and_hash(tmp_path):
    sha = fixture(tmp_path)
    r = module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha=sha,
                                 expected_size=len(b"immutable fake test bytes"))
    assert r["storage_preflight_ok"] is True, r
    assert r["checks_passed"] == r["checks_total"]
    for label in ("deployment_authorized", "database_cutover_authorized", "restore_verified", "backup_verified"):
        assert r[label] is False
    assert r["verified_artifact_bytes"] == len(b"immutable fake test bytes")


def test_62a_rejects_missing_wal_and_false_artifact_sha_and_symlinks(tmp_path):
    sha = fixture(tmp_path)
    (tmp_path / "postgres/data/pg_wal").rmdir()
    assert not module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha=sha)["storage_preflight_ok"]
    (tmp_path / "postgres/data/pg_wal").mkdir()
    p = tmp_path / "store" / f"{RELEASE}.tar"
    p.write_bytes(b"tampered")
    assert not module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha=sha)["storage_preflight_ok"]
    p.unlink()
    p.symlink_to(tmp_path / "postgres/data/PG_VERSION")
    assert not module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha=sha)["storage_preflight_ok"]


def test_62a_rejects_world_writable_store_and_incorrect_pg_major(tmp_path):
    sha = fixture(tmp_path)
    os.chmod(tmp_path / "store", 0o777)
    assert not module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha=sha)["storage_preflight_ok"]
    os.chmod(tmp_path / "store", 0o755)
    (tmp_path / "postgres/data/PG_VERSION").write_text("17\n")
    assert not module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha=sha)["storage_preflight_ok"]


def test_62a_cli_returns_nonzero_on_incomplete_storage_and_never_mutates(tmp_path):
    sha = fixture(tmp_path)
    cli = [sys.executable, str(SCRIPT), "--mount", str(tmp_path), "--release-id", RELEASE,
           "--expected-sha256", sha]
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    proc = subprocess.run(cli, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert '"database_cutover_authorized": false' in proc.stdout
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    (tmp_path / "store" / f"{RELEASE}.tar").unlink()
    assert subprocess.run(cli, capture_output=True, check=False).returncode == 2


def test_62a_rejects_invalid_release_identity_before_disk_access(tmp_path):
    with pytest.raises(ValueError):
        module.storage_preflight(tmp_path, release_id="../../x", expected_sha="a"*64)
    with pytest.raises(ValueError):
        module.storage_preflight(tmp_path, release_id=RELEASE, expected_sha="not-a-sha")
