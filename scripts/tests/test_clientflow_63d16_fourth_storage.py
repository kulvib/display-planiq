"""63D-16 temporary storage waiver may only append immutable signed 1248."""
from __future__ import annotations

from pathlib import Path
import pytest
from scripts import audit_clientflow_release_retention as audit
from scripts import clientflow_63d16_1248_storage_exception as exception


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "store"
    path.mkdir(mode=0o700)
    for release_id, (size, digest) in exception.HISTORICAL.items():
        # Fixture bytes are never accepted by the actual bundle validator.
        (path / (release_id + ".tar")).write_bytes(b"fixture")
    return path


def _fake_verified(path: Path, *, require_deployable=True):
    assert require_deployable
    release_id = path.stem
    if release_id in exception.HISTORICAL:
        size, digest = exception.HISTORICAL[release_id]
    else:
        size, digest = 400, "e" * 64
    return (
        {"version": path.name.split("-")[1], "release_sequence": int(path.stem.rsplit("-", 1)[1]),
         "release_id": release_id, "release_approval": {"reference": "test"},
         "source": {"commit": "a" * 40}},
        None, size, digest, path.open("rb"),
    )


def test_default_still_rejects_fourth(tmp_path, monkeypatch):
    root = _store(tmp_path)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _fake_verified)
    with pytest.raises(audit.StoreAuditError, match="three-release cap"):
        audit.plan_publication(root, release_id=exception.EXCEPTION_RELEASE_ID,
                               size_bytes=400, sha256="e" * 64)


def test_exact_fourth_is_permitted_only_when_explicit(tmp_path, monkeypatch):
    root = _store(tmp_path)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _fake_verified)
    plan = audit.plan_publication(
        root, release_id=exception.EXCEPTION_RELEASE_ID,
        size_bytes=400, sha256="e" * 64,
        authorized_1248_viborg1_fourth=True,
    )
    assert plan["disposition"] == "ready_to_publish"
    assert plan["retention_target_unchanged"] == 3
    assert plan["1248_viborg1_fourth_storage_only"] is True
    assert plan["automatic_deletion_enabled"] is False
    (root / (exception.EXCEPTION_RELEASE_ID + ".tar")).write_bytes(b"fixture-1248")
    result = audit.verify_publication(
        root, release_id=exception.EXCEPTION_RELEASE_ID,
        size_bytes=400, sha256="e" * 64,
        authorized_1248_viborg1_fourth=True,
    )
    assert result["approved_count"] == 4
    assert result["within_approved_limit"] is False
    with pytest.raises(audit.StoreAuditError, match="cap exceeded"):
        audit.verify_publication(root, release_id=exception.EXCEPTION_RELEASE_ID,
                                 size_bytes=400, sha256="e" * 64)


@pytest.mark.parametrize("other_id", [
    "clientflow-1.3.48-seq-1249", "clientflow-1.3.46-seq-1247",
    "clientflow-1.3.41-seq-1248",
])
def test_flag_cannot_authorize_another_identity(tmp_path, monkeypatch, other_id):
    root = _store(tmp_path)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _fake_verified)
    with pytest.raises(audit.StoreAuditError):
        audit.plan_publication(root, release_id=other_id,
                               size_bytes=400, sha256="e" * 64,
                               authorized_1248_viborg1_fourth=True)


def test_flag_denies_missing_historical_or_fifth(tmp_path, monkeypatch):
    root = _store(tmp_path)
    monkeypatch.setattr(audit, "open_verified_bundle_structure", _fake_verified)
    (root / "clientflow-1.3.44-seq-1245.tar").unlink()
    with pytest.raises(audit.StoreAuditError):
        audit.plan_publication(root, release_id=exception.EXCEPTION_RELEASE_ID,
                               size_bytes=400, sha256="e" * 64,
                               authorized_1248_viborg1_fourth=True)
    (root / "clientflow-1.3.44-seq-1245.tar").write_bytes(b"fixture")
    (root / "clientflow-1.3.43-seq-1244.tar").write_bytes(b"fixture")
    with pytest.raises(audit.StoreAuditError):
        audit.plan_publication(root, release_id=exception.EXCEPTION_RELEASE_ID,
                               size_bytes=400, sha256="e" * 64,
                               authorized_1248_viborg1_fourth=True)


def test_flag_denies_modified_historical_sha(tmp_path, monkeypatch):
    root = _store(tmp_path)
    def altered(path, *, require_deployable=True):
        manifest, payload, size, digest, handle = _fake_verified(path, require_deployable=require_deployable)
        if path.stem == "clientflow-1.3.45-seq-1246":
            digest = "1" * 64
        return manifest, payload, size, digest, handle
    monkeypatch.setattr(audit, "open_verified_bundle_structure", altered)
    with pytest.raises(audit.StoreAuditError):
        audit.plan_publication(root, release_id=exception.EXCEPTION_RELEASE_ID,
                               size_bytes=400, sha256="e" * 64,
                               authorized_1248_viborg1_fourth=True)
