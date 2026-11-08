"""Exact-byte approved GitHub release archive safety tests; no repository writes."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_clientflow_approved_release_asset import (  # noqa: E402
    ApprovedArchiveDenied,
    verify_handoff,
)

SOURCE = "b870cf8c3fa90286c6b4dccaae593eb8a0d57565"
REFERENCE = "CF-1.3.42-1243-VIBORG2-PILOT-20261107"
CANDIDATE = "4e52cbfbaa844c2d835e5b57f625b5a64cb98346c428ee410aead02b7c67c88a"
PAYLOAD = b"verified-test-payload"
INSTALLER = b"verified-test-installer"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_handoff(directory: Path) -> tuple[dict, str]:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "release_id": "clientflow-1.3.42-seq-1243",
        "version": "1.3.42", "release_sequence": 1243, "deployable": True,
        "source": {"commit": SOURCE, "dirty": False},
        "release_approval": {"reference": REFERENCE, "candidate_sha256": CANDIDATE},
        "payload": {"file": "clientflow-payload.tar", "size": len(PAYLOAD), "sha256": sha(PAYLOAD)},
        "fresh_installer": {
            "file": "clientflow-installer-1.3.42.pyz",
            "size": len(INSTALLER), "sha256": sha(INSTALLER),
        },
    }
    with tarfile.open(directory / "clientflow-approved.tar", mode="w:") as tar:
        for name, data in (
            ("manifest.json", json.dumps(manifest).encode()),
            ("clientflow-payload.tar", PAYLOAD),
            ("clientflow-installer-1.3.42.pyz", INSTALLER),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    binary = (directory / "clientflow-approved.tar").read_bytes()
    record = {
        "schema_version": 1, "source_commit": SOURCE,
        "candidate_sha256": CANDIDATE,
        "installer_sha256": sha(INSTALLER),
        "approval_reference": REFERENCE,
        "approved_bundle_sha256": sha(binary),
        "approved_bundle_size": len(binary),
        "release_build_run_id": 42390711483,
    }
    (directory / "APPROVAL.json").write_text(json.dumps(record), encoding="utf-8")
    (directory / "APPROVAL.txt").write_text(
        f"APPROVED_BUNDLE_SHA256={sha(binary)}\n"
        f"APPROVED_BUNDLE_SIZE={len(binary)}\n"
        f"INSTALLER_SHA256={sha(INSTALLER)}\n", encoding="utf-8",
    )
    return record, sha(binary)


def checked(handoff: Path, record: dict) -> dict:
    return verify_handoff(
        handoff,
        expected_source_sha=SOURCE,
        expected_approved_sha256=record["approved_bundle_sha256"],
        expected_approval_reference=REFERENCE,
    )


def test_approved_handoff_identity_and_release_tag(tmp_path: Path) -> None:
    record, digest = create_handoff(tmp_path)
    verified = checked(tmp_path, record)
    assert verified["approved_bundle_sha256"] == digest
    assert verified["tag"] == "clientflow-1.3.42-1243-approved-transport"
    assert verified["asset_name"] == "clientflow-approved-1.3.42-1243.tar"
    assert verified["source_commit"] == SOURCE
    assert verified["approval_reference"] == REFERENCE
    assert verified["release_build_run_id"] == 42390711483


def test_wrong_approved_sha_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    with pytest.raises(ApprovedArchiveDenied, match="SHA-256 differs"):
        verify_handoff(tmp_path, expected_source_sha=SOURCE,
            expected_approved_sha256="a" * 64, expected_approval_reference=REFERENCE)


def test_wrong_source_commit_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    with pytest.raises(ApprovedArchiveDenied, match="source commit differs"):
        verify_handoff(tmp_path, expected_source_sha="b" * 40,
            expected_approved_sha256=record["approved_bundle_sha256"],
            expected_approval_reference=REFERENCE)


def test_wrong_approval_reference_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    with pytest.raises(ApprovedArchiveDenied, match="reference differs"):
        verify_handoff(tmp_path, expected_source_sha=SOURCE,
            expected_approved_sha256=record["approved_bundle_sha256"],
            expected_approval_reference="CF-UNAPPROVED")


def test_tampered_bundle_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    bundle = tmp_path / "clientflow-approved.tar"
    with bundle.open("ab") as f:
        f.write(b"tampered")
    with pytest.raises(ApprovedArchiveDenied, match="content size/hash differs"):
        checked(tmp_path, record)


def test_unexpected_handoff_files_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    (tmp_path / "README.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ApprovedArchiveDenied, match="Unexpected handoff"):
        checked(tmp_path, record)


def test_symlink_handoff_member_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    original = tmp_path / "APPROVAL.txt"
    original.rename(tmp_path / "APPROVAL.original.txt")
    (tmp_path / "APPROVAL.txt").symlink_to(tmp_path / "APPROVAL.original.txt")
    (tmp_path / "APPROVAL.original.txt").unlink()
    with pytest.raises((ApprovedArchiveDenied, FileNotFoundError)):
        checked(tmp_path, record)


def test_forged_candidate_digest_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    record["candidate_sha256"] = "d" * 64
    (tmp_path / "APPROVAL.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ApprovedArchiveDenied, match="candidate SHA-256 differs"):
        checked(tmp_path, record)


def test_forged_installer_digest_denied(tmp_path: Path) -> None:
    record, _ = create_handoff(tmp_path)
    record["installer_sha256"] = "d" * 64
    (tmp_path / "APPROVAL.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "APPROVAL.txt").write_text(
        f"APPROVED_BUNDLE_SHA256={record['approved_bundle_sha256']}\n"
        f"APPROVED_BUNDLE_SIZE={record['approved_bundle_size']}\n"
        "INSTALLER_SHA256=" + "d" * 64 + "\n", encoding="utf-8",
    )
    with pytest.raises(ApprovedArchiveDenied, match="installer differs"):
        checked(tmp_path, record)


def test_workflow_enforces_no_replace_source_approval_and_digest() -> None:
    workflow = (ROOT / ".github/workflows/release-archive-approved.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "default: false" in workflow
    assert 'test "$CONFIRM_ARCHIVE" = true' in workflow
    assert 'test "$GITHUB_REF_NAME" = main' in workflow
    assert '"path": ".github/workflows/release-approve.yml"' in workflow
    assert '"conclusion": "success"' in workflow
    assert "verify_clientflow_approved_release_asset.py" in workflow
    assert "--latest=false" in workflow
    assert "--prerelease" in workflow
    assert "--target \"$SOURCE_SHA\"" in workflow
    assert "git/ref/tags/$TAG" in workflow
    assert "Archived asset digest differs" in workflow
    assert "APPROVED_GITHUB_RELEASE_ARCHIVE=PASS" in workflow
    assert "publish_clientflow_release" not in workflow
    assert "CLIENTFLOW_1243_PILOT_CLIENT_ID" not in workflow
