"""Only a separately attested, exact oldest immutable release may be removed."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import audit_clientflow_release_retention as audit
from scripts import prune_clientflow_release_retention as cleanup
from scripts.clientflow_1244_transition_policy import ClientFlow1244ResetDenied


def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    return root


def fixture_artifact(root: Path, seq: int) -> Path:
    path = root / f"clientflow-1.3.{seq-1200}-seq-{seq}.tar"
    path.write_bytes(f"approved-{seq}".encode())
    return path


def approve_stub(path: Path, *, require_deployable=True):
    match = audit.RELEASE_FILE.fullmatch(path.name)
    assert match and require_deployable
    raw = path.read_bytes()
    return (
        {"version": match.group(1), "release_sequence": int(match.group(2)),
         "release_id": path.stem,
         "release_approval": {"reference": "approved/test"},
         "source": {"commit": "a" * 40}},
        None, len(raw), hashlib.sha256(raw).hexdigest(), path.open("rb"),
    )


def test_dry_run_lists_only_oldest_and_changes_nothing(tmp_path, monkeypatch):
    directory = store(tmp_path)
    paths = [fixture_artifact(directory, seq) for seq in range(1236, 1241)]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    before = {p.name: p.read_bytes() for p in paths}
    result = cleanup.plan_cleanup(directory)
    assert result["deleted"] is False
    assert result["prune_candidate"]["release_sequence"] == 1236
    assert len(result["protected"]) == 4
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_cleanup_needs_exact_identity_and_two_authorizations(tmp_path, monkeypatch):
    directory = store(tmp_path)
    paths = [fixture_artifact(directory, seq) for seq in range(1236, 1241)]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    oldest = paths[0]
    digest = hashlib.sha256(oldest.read_bytes()).hexdigest()
    with pytest.raises(cleanup.PruneDenied, match="Both explicit"):
        cleanup.prune_one_oldest(directory, expected_release_id=oldest.stem,
                                 expected_sha256=digest, confirm_prune=True)
    with pytest.raises(cleanup.PruneDenied, match="identity"):
        cleanup.prune_one_oldest(directory, expected_release_id=oldest.stem,
                                 expected_sha256="0" * 64)
    with pytest.raises(cleanup.PruneDenied, match="oldest approved release identity changed"):
        cleanup.prune_one_oldest(directory, expected_release_id=paths[-1].stem,
                                 expected_sha256=hashlib.sha256(paths[-1].read_bytes()).hexdigest(),
                                 confirm_prune=True, confirm_no_dependencies=True)
    assert len(list(directory.iterdir())) == 5


def test_explicit_cleanup_removes_only_exact_oldest(tmp_path, monkeypatch):
    directory = store(tmp_path)
    paths = [fixture_artifact(directory, seq) for seq in range(1236, 1241)]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    oldest = paths[0]
    digest = hashlib.sha256(oldest.read_bytes()).hexdigest()
    report = cleanup.prune_one_oldest(
        directory, expected_release_id=oldest.stem,
        expected_sha256=digest, confirm_prune=True,
        confirm_no_dependencies=True,
    )
    assert not oldest.exists()
    assert report["approved_count_after"] == 4
    assert report["remaining_excess"] == 1
    assert [item.name for item in paths[1:]] == sorted(p.name for p in directory.iterdir())
    assert not audit.inspect_store(directory)["within_approved_limit"]


def test_cleanup_rejects_unrecognized_six_or_more_and_corrupt_symlink(tmp_path, monkeypatch):
    directory = store(tmp_path)
    paths = [fixture_artifact(directory, seq) for seq in range(1236, 1242)]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    with pytest.raises(ClientFlow1244ResetDenied, match="(?i)exact pinned"):
        cleanup.plan_cleanup(directory)
    paths[-1].unlink()
    paths[-2].unlink()
    paths[-2].symlink_to(paths[-3])
    with pytest.raises(audit.StoreAuditError, match="Unsafe release store"):
        cleanup.plan_cleanup(directory)


def test_cleanup_cli_defaults_to_read_only_and_refuses_half_confirmation(tmp_path, monkeypatch, capsys):
    directory = store(tmp_path)
    paths = [fixture_artifact(directory, seq) for seq in range(1236, 1241)]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    assert cleanup.main(["--artifact-dir", str(directory)]) == 0
    assert "RELEASE_RETENTION_CLEANUP=DRY_RUN_ONLY" in capsys.readouterr().out
    assert cleanup.main(["--artifact-dir", str(directory), "--confirm-prune"]) == 1
    assert all(p.exists() for p in paths)


def test_rotation_from_four_to_three_then_next_publication_refused_until_two(tmp_path, monkeypatch):
    directory = store(tmp_path)
    paths = [fixture_artifact(directory, seq) for seq in range(1237, 1241)]
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    proposed = cleanup.plan_cleanup(directory)
    assert proposed["approved_count_before"] == 4
    assert proposed["approved_count_after"] == 3
    assert proposed["prune_candidate"]["release_id"] == paths[0].stem
    result = cleanup.prune_one_oldest(
        directory, expected_release_id=paths[0].stem,
        expected_sha256=hashlib.sha256(paths[0].read_bytes()).hexdigest(),
        confirm_prune=True, confirm_no_dependencies=True,
    )
    assert result["approved_count_after"] == 3
    assert not paths[0].exists()
    # The approved cap is three, so further rotation to two is required
    # before a new bundle is allowed to enter the store.
    with pytest.raises(audit.StoreAuditError, match="three-release cap"):
        audit.plan_publication(directory, release_id="clientflow-1.3.41-seq-1241", size_bytes=1024, sha256="f" * 64)
    two_plan = cleanup.plan_cleanup(directory)
    assert two_plan["approved_count_after"] == 2
    next_oldest = paths[1]
    assert two_plan["prune_candidate"]["release_id"] == next_oldest.stem
    cleanup.prune_one_oldest(
        directory, expected_release_id=next_oldest.stem,
        expected_sha256=hashlib.sha256(next_oldest.read_bytes()).hexdigest(),
        confirm_prune=True, confirm_no_dependencies=True,
    )
    new = audit.plan_publication(directory, release_id="clientflow-1.3.41-seq-1241", size_bytes=1024, sha256="f" * 64)
    assert new["disposition"] == "ready_to_publish"
    assert len(new["protected_after_publication"]) == 3
    assert new["older_review_only"] == []


def test_current_stable_1338_is_pinned_even_with_both_deletion_flags(tmp_path, monkeypatch):
    # Historical 1239 was pinned until 1244 was promoted; preserve this proof.
    monkeypatch.setattr(
        cleanup, "CATALOG_PATH",
        Path(__file__).resolve().parents[2] / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json",
    )
    directory = store(tmp_path)
    oldest = directory / "clientflow-1.3.38-seq-1239.tar"
    oldest.write_bytes(b"approved-1239")
    for seq in (1240, 1241, 1242):
        fixture_artifact(directory, seq)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    plan = cleanup.plan_cleanup(directory)
    assert plan["catalog_pin_blocks_cleanup"] is True
    assert oldest.stem in plan["catalog_pinned_release_ids"]
    with pytest.raises(cleanup.PruneDenied, match="Cannot delete active stable/default"):
        cleanup.prune_one_oldest(
            directory, expected_release_id=oldest.stem,
            expected_sha256=hashlib.sha256(oldest.read_bytes()).hexdigest(),
            confirm_prune=True, confirm_no_dependencies=True,
        )
    assert oldest.exists()


def test_fail_closed_when_active_catalog_missing_or_invalid(tmp_path, monkeypatch):
    directory = store(tmp_path)
    oldest = fixture_artifact(directory, 1239)
    for seq in (1240, 1241):
        fixture_artifact(directory, seq)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    monkeypatch.setattr(cleanup, "CATALOG_PATH", tmp_path / "not-present.json")
    with pytest.raises(cleanup.PruneDenied, match="Unable to verify active release catalog"):
        cleanup.plan_cleanup(directory)
    assert oldest.exists()


def test_cannot_skip_oldest_to_delete_an_unpinned_newer_release(tmp_path, monkeypatch):
    # Historical 1239 was pinned until 1244 was promoted; preserve this proof.
    monkeypatch.setattr(
        cleanup, "CATALOG_PATH",
        Path(__file__).resolve().parents[2] / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json",
    )
    directory = store(tmp_path)
    (directory / "clientflow-1.3.38-seq-1239.tar").write_bytes(b"approved-1239")
    for seq in (1240, 1241, 1242):
        fixture_artifact(directory, seq)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", approve_stub)
    newer = directory / "clientflow-1.3.40-seq-1240.tar"
    with pytest.raises(cleanup.PruneDenied, match="Cannot delete active stable/default"):
        cleanup.prune_one_oldest(
            directory, expected_release_id=newer.stem,
            expected_sha256=hashlib.sha256(newer.read_bytes()).hexdigest(),
            confirm_prune=True, confirm_no_dependencies=True,
        )
    assert newer.exists()
