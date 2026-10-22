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


def test_protects_four_newest_without_modifying_any_bytes(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    older = _bundle(directory, "1.3.33", 1234)
    _bundle(directory, "1.3.34", 1235)
    _bundle(directory, "1.3.35", 1236)
    _bundle(directory, "1.3.36", 1237)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = audit.inspect_store(directory, require_three=True)
    assert [x["release_sequence"] for x in result["protected_latest"]] == [1237, 1236, 1235, 1234]
    assert result["older_review_only"] == []
    assert result["within_approved_limit"] is True
    assert result["retention_ready"] is True
    assert result["rollback_enabled"] is False
    assert result["automatic_deletion_enabled"] is False
    assert older.exists()
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_missing_four_does_not_claim_ready(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1236)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    result = audit.inspect_store(directory)
    assert result["retention_ready"] is False
    with pytest.raises(audit.StoreAuditError, match="exactly four"):
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


def test_publication_plan_keeps_four_and_never_deletes_older(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    paths = [
        _bundle(directory, "1.3.33", 1234),
        _bundle(directory, "1.3.34", 1235),
        _bundle(directory, "1.3.35", 1236),
    ]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    state = {p.name: p.read_bytes() for p in paths}
    decision = audit.plan_publication(
        directory, release_id="clientflow-1.3.36-seq-1237",
        size_bytes=223498240, sha256="b" * 64,
    )
    assert decision["disposition"] == "ready_to_publish"
    assert decision["protected_after_publication"] == [
        "clientflow-1.3.36-seq-1237",
        "clientflow-1.3.35-seq-1236",
        "clientflow-1.3.34-seq-1235",
        "clientflow-1.3.33-seq-1234",
    ]
    assert decision["older_review_only"] == []
    assert decision["rollback_enabled"] is False
    assert decision["automatic_deletion_enabled"] is False
    assert state == {p.name: p.read_bytes() for p in paths}


def test_publication_plan_refuses_insufficient_disk_space(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    actual_statvfs = audit.os.statvfs

    class LowSpace:
        f_bavail = (audit.RESERVED_FREE_BYTES + 200) // 4096
        f_frsize = 4096
        f_blocks = 300000

    monkeypatch.setattr(audit.os, "statvfs", lambda path: LowSpace() if path == directory else actual_statvfs(path))
    with pytest.raises(audit.StoreAuditError, match="Insufficient free disk"):
        audit.plan_publication(
            directory, release_id="clientflow-1.3.36-seq-1237",
            size_bytes=1024, sha256="b" * 64,
        )


def test_publication_plan_fails_closed_on_corruption_and_old_sequences(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    _bundle(directory, "1.3.35", 1236)
    # Without a verified approval, even a nominally good release may not be
    # counted. This blocks publication before any temporary file is written.
    with pytest.raises(audit.StoreAuditError, match="Unsafe release store"):
        audit.plan_publication(
            directory, release_id="clientflow-1.3.36-seq-1237",
            size_bytes=1024, sha256="b" * 64,
        )
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    with pytest.raises(audit.StoreAuditError, match="older release"):
        audit.plan_publication(
            directory, release_id="clientflow-1.3.34-seq-1235",
            size_bytes=1024, sha256="b" * 64,
        )
    with pytest.raises(audit.StoreAuditError, match="duplicates"):
        audit.plan_publication(
            directory, release_id="clientflow-1.3.36-seq-1236",
            size_bytes=1024, sha256="b" * 64,
        )


def test_publication_plan_idempotency_requires_identical_approved_bytes(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    artifact = _bundle(directory, "1.3.35", 1236)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    plan = audit.plan_publication(
        directory, release_id=artifact.stem,
        size_bytes=artifact.stat().st_size, sha256="f" * 64,
    )
    assert plan["disposition"] == "already_published"
    assert plan["required_available_bytes"] == 0
    with pytest.raises(audit.StoreAuditError, match="does not match"):
        audit.plan_publication(
            directory, release_id=artifact.stem,
            size_bytes=artifact.stat().st_size, sha256="e" * 64,
        )


def test_publication_postflight_requires_verified_bytes_and_reserve(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    artifact = _bundle(directory, "1.3.35", 1236)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    result = audit.verify_publication(
        directory, release_id=artifact.stem,
        size_bytes=artifact.stat().st_size, sha256="f" * 64,
    )
    assert result["approved_count"] == 1
    with pytest.raises(audit.StoreAuditError, match="missing or failed"):
        audit.verify_publication(
            directory, release_id=artifact.stem,
            size_bytes=artifact.stat().st_size, sha256="e" * 64,
        )


def test_fifth_published_bundle_reports_violation_without_mutation(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    for seq in range(1236, 1241):
        _bundle(directory, f"1.3.{seq-1200}", seq)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    report = audit.inspect_store(directory)
    assert report["retention_target"] == 4
    assert report["approved_count"] == 5
    assert report["within_approved_limit"] is False
    assert report["retention_ready"] is False
    assert [item["release_sequence"] for item in report["protected_latest"]] == [1240, 1239, 1238, 1237]
    assert [item["release_sequence"] for item in report["older_review_only"]] == [1236]
    with pytest.raises(audit.StoreAuditError, match="exactly four"):
        audit.inspect_store(directory, require_four=True)
    with pytest.raises(audit.StoreAuditError, match="Post-publication approved release cap exceeded"):
        audit.verify_publication(directory, release_id="clientflow-1.3.40-seq-1240", size_bytes=22, sha256="f" * 64)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_publication_refuses_fifth_approved_release_without_mutation(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    for seq in range(1236, 1240):
        _bundle(directory, f"1.3.{seq-1200}", seq)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(audit.StoreAuditError, match="Approved release cap exceeded"):
        audit.plan_publication(
            directory,
            release_id="clientflow-1.3.40-seq-1240",
            size_bytes=1024,
            sha256="b" * 64,
        )
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_existing_release_idempotency_still_allowed_with_four(tmp_path, monkeypatch):
    directory = _store(tmp_path)
    for seq in range(1236, 1240):
        _bundle(directory, f"1.3.{seq-1200}", seq)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _approved_fake)
    decision = audit.plan_publication(
        directory, release_id="clientflow-1.3.39-seq-1239",
        size_bytes=22, sha256="f" * 64,
    )
    assert decision["disposition"] == "already_published"
    assert len(decision["protected_after_publication"]) == 4
