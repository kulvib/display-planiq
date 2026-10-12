"""Retention audit must never authorize downgrade or delete source archives."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import audit_clientflow_release_retention as audit


def _store(tmp_path: Path) -> Path:
    directory = tmp_path / "store"
    directory.mkdir(mode=0o700)
    return directory


def _bundle(dirpath: Path, version: str, seq: int) -> Path:
    path = dirpath / f"clientflow-{version}-seq-{seq}.tar"
    path.write_bytes(b"pretend approved bytes")
    return path


def _approved_fake(path: Path, *, require_deployable: bool = True):
    # Here format verification is stubbed only to exercise retention policy;
    # the real bundle validator has its own independent fixture-based tests.
    match = audit.RELEASE_FILE.fullmatch(path.name)
    assert require_deployable is True and match
    version, sequence = match.group(1), int(match.group(2))
    return (
        {"version": version, "release_sequence": sequence,
         "release_id": path.stem,
         "release_approval": {"reference": "approved/test"},
         "source": {"commit": "a" * 40}},
        None, path.stat().st_size, "f" * 64, path.open("rb"),
    )


def test_protects_three_newest_without_modifying_any_bytes(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    older = _bundle(directory, "1.3.33", 1234)
    _bundle(directory, "1.3.34", 1235)
    _bundle(directory, "1.3.35", 1236)
    _bundle(directory, "1.3.36", 1237)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = audit.inspect_store(directory, require_three=True)
    assert [x["release_sequence"] for x in result["protected_latest"]] == [1237, 1236, 1235]
    assert [x["release_sequence"] for x in result["older_review_only"]] == [1234]
    assert result["rollback_enabled"] is False
    assert result["automatic_deletion_enabled"] is False
    assert older.exists()
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_missing_three_does_not_claim_ready(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1236)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    result = audit.inspect_store(directory)
    assert result["retention_ready"] is False
    with pytest.raises(audit.StoreAuditError, match="Fewer than three"):
        audit.inspect_store(directory, require_three=True)


def test_corrupt_and_symlink_fail_closed(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1236)
    _bundle(directory, "1.3.36", 1237)
    (directory / "clientflow-1.3.37-seq-1238.tar").symlink_to(directory / "clientflow-1.3.36-seq-1237.tar")
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    with pytest.raises(audit.StoreAuditError, match="Unsafe release store"):
        audit.inspect_store(directory)


def test_unverified_bytes_never_count_as_approved(tmp_path):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1236)
    with pytest.raises(audit.StoreAuditError, match="Unsafe release store"):
        audit.inspect_store(directory)


def test_duplicate_sequence_fails_closed(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1237)
    _bundle(directory, "1.3.36", 1237)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    with pytest.raises(audit.StoreAuditError, match="Unsafe release store"):
        audit.inspect_store(directory)


def test_bad_directory_permissions_are_rejected(tmp_path):
    directory = _store(tmp_path)
    directory.chmod(0o777)
    try:
        with pytest.raises(audit.StoreAuditError, match="insecure"):
            audit.inspect_store(directory)
    finally:
        directory.chmod(0o700)


def test_noncanonical_candidate_filename_blocks_audit(tmp_path):
    directory = _store(tmp_path)
    (directory / "clientflow-bogus.tar").write_bytes(b"bad")
    with pytest.raises(audit.StoreAuditError, match="Unsafe release store"):
        audit.inspect_store(directory)


def test_stdout_has_no_secrets_and_is_machine_readable(tmp_path, monkeypatch, capsys):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1236)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    assert audit.main(["--artifact-dir", str(directory)]) == 0
    output = capsys.readouterr().out
    assert "RELEASE_STORE_AUDIT=PASS" in output
    assert "RELEASE_RETENTION_READY=NO" in output


def test_real_approved_bundle_is_verified_by_retention_audit(tmp_path):
    # The real bundle structure and approval gate are exercised here, without
    # monkeypatching the format verifier.
    from backend.tests.test_clientflow_release_publication_51h import _approved_bundle

    directory = _store(tmp_path)
    _approved_bundle(
        directory,
        approval_reference="retention-integration-test",
        source_commit="c" * 40,
        marker=b"approved-source-bytes",
    )
    result = audit.inspect_store(directory)
    assert result["approved_count"] == 1
    assert result["retention_ready"] is False
    assert result["invalid_artifacts"] == []
    assert result["protected_latest"][0]["source_commit"] == "c" * 40
