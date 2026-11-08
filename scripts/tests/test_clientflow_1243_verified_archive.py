"""Non-destructive archive policy and hostile source-path tests."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import archive_clientflow_release_verified as arch
from scripts import audit_clientflow_release_retention as audit


def _fake_approved(path: Path, *, require_deployable=True):
    match = audit.RELEASE_FILE.fullmatch(path.name)
    assert match and require_deployable
    data = path.read_bytes()
    return (
        {"version": match.group(1), "release_sequence": int(match.group(2)),
         "release_id": path.stem, "release_approval": {"reference": "test-approval"},
         "source": {"commit": "e" * 40}},
        None, len(data), hashlib.sha256(data).hexdigest(), path.open("rb"),
    )


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _fake_approved)
    store = tmp_path / "store"
    archive = tmp_path / "archive"
    store.mkdir(mode=0o700)
    archive.mkdir(mode=0o700)
    release_id = "clientflow-1.3.38-seq-1239"
    path = store / (release_id + ".tar")
    payload = b"approved-1.3.38-bundle-bytes"
    path.write_bytes(payload)
    return store, archive, path, release_id, hashlib.sha256(payload).hexdigest()


def test_readonly_does_not_create_file(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    result = arch.verified_archive(store, archive, release_id=release_id, expected_sha256=sha)
    assert result["archived"] is False
    assert list(archive.iterdir()) == []
    assert path.read_bytes() == b"approved-1.3.38-bundle-bytes"


def test_exact_copy_idempotent_and_no_source_mutation(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    original_ino = path.stat().st_ino
    result = arch.verified_archive(store, archive, release_id=release_id,
                                   expected_sha256=sha, make_archive=True)
    assert result["archived"] is True
    assert result["operator_offsite_backup_still_required"] is True
    dest = archive / path.name
    assert dest.read_bytes() == path.read_bytes()
    assert path.stat().st_ino == original_ino
    assert arch.verified_archive(store, archive, release_id=release_id,
        expected_sha256=sha, make_archive=True)["mode"] == "already_archived_verified"
    assert sorted(x.name for x in archive.iterdir()) == [path.name]


def test_mutated_expected_sha_denied(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    with pytest.raises(arch.ArchiveDenied, match="not an exact verified"):
        arch.verified_archive(store, archive, release_id=release_id,
                              expected_sha256="0" * 64, make_archive=True)
    assert list(archive.iterdir()) == []


def test_archive_wrong_preexisting_bytes_is_never_replaced(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    preexisting = archive / path.name
    preexisting.write_bytes(b"UNRELATED")
    with pytest.raises(arch.ArchiveDenied, match="different bytes"):
        arch.verified_archive(store, archive, release_id=release_id,
                              expected_sha256=sha, make_archive=True)
    assert preexisting.read_bytes() == b"UNRELATED"


def test_symlink_and_unsafe_dest_are_blocked(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    link = tmp_path / "archive_link"
    link.symlink_to(archive, target_is_directory=True)
    with pytest.raises(RuntimeError):
        arch.verified_archive(store, link, release_id=release_id,
                              expected_sha256=sha, make_archive=True)
    archive.chmod(0o777)
    try:
        with pytest.raises(RuntimeError):
            arch.verified_archive(store, archive, release_id=release_id,
                                  expected_sha256=sha, make_archive=True)
    finally:
        archive.chmod(0o700)


def test_destination_must_be_outside_active_release_store(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    with pytest.raises(arch.ArchiveDenied, match="outside"):
        arch.verified_archive(store, store, release_id=release_id,
                              expected_sha256=sha, make_archive=True)
    subdir = store / "subdir"
    subdir.mkdir()
    with pytest.raises(arch.ArchiveDenied, match="outside"):
        arch.verified_archive(store, subdir, release_id=release_id,
                              expected_sha256=sha, make_archive=True)


def test_cannot_archive_tampered_source(tmp_path, monkeypatch):
    store, archive, path, release_id, sha = _setup(tmp_path, monkeypatch)
    path.write_bytes(b"wrong")
    with pytest.raises(arch.ArchiveDenied):
        arch.verified_archive(store, archive, release_id=release_id,
                              expected_sha256=sha, make_archive=True)
    assert not list(archive.iterdir())


def test_archive_has_no_delete_opt_in_or_prune_side_effect():
    source = Path(arch.__file__).read_text()
    assert "os.unlink(source_name" not in source
    assert "source_store.unlink" not in source
    assert "--confirm-prune" not in source
    assert "--delete" not in source
