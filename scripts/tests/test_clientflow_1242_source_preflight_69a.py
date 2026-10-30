"""Read-only source-preflight guardrails; never build or activate a release."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clientflow_1242_source_preflight import inspect_source  # noqa: E402

SPKI = bytes.fromhex("302a300506032b6570032100")
PUBLIC = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")


def fixture(tmp_path: Path, *, version: str = "1.3.41", seq: int = 1242, trusted: bool = True) -> Path:
    repo = tmp_path / "repo"
    (repo / "client/release").mkdir(parents=True)
    (repo / "backend/service1").mkdir(parents=True)
    (repo / "client/VERSION").write_text(version, encoding="utf-8")
    (repo / "client/release/release-input.json").write_text(json.dumps({"release_sequence": seq}), encoding="utf-8")
    key = {
        "key_id": hashlib.sha256(SPKI + PUBLIC).hexdigest()[:32],
        "public_key_b64": base64.urlsafe_b64encode(PUBLIC).rstrip(b"=").decode("ascii"),
        "min_policy_revision": 1,
        "minimum_safe_release_sequence": 1239,
    }
    (repo / "client/release/rollback-trust.json").write_text(json.dumps({"schema_version": 1, "enabled": trusted, "keys": [key] if trusted else []}), encoding="utf-8")
    (repo / "backend/service1/clientflow_release_security_policy.json").write_text(json.dumps({"schema_version": 1, "revision": 1, "minimum_safe_release_sequence": 1239, "revoked_release_ids": []}), encoding="utf-8")
    return repo


def test_current_source_is_safely_blocked() -> None:
    result = inspect_source(ROOT)
    assert result["phase"] == "source_stage_only"
    assert result["source_stage_ready"] is False
    assert result["publish_authorized"] is False
    assert result["activation_authorized"] is False
    assert {c["name"] for c in result["checks"]} == {"release_version", "release_sequence", "manual_rollback_safety_mode"}


def test_valid_public_trust_does_not_authorize_production(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    result = inspect_source(repo)
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert result["source_stage_ready"] is True
    assert all(c["passed"] for c in result["checks"])
    assert result["publish_authorized"] is False
    assert result["activation_authorized"] is False
    assert result["requires_operator_signer_identity_verification"]
    assert result["manual_rollback_mode"] == "signed"
    assert result["requires_physical_pilot"]
    assert before == after


def test_disabled_trust_is_explicit_safe_source_mode_without_signer(tmp_path: Path) -> None:
    result = inspect_source(fixture(tmp_path, trusted=False))
    assert result["source_stage_ready"]
    assert result["manual_rollback_mode"] == "disabled"
    assert not result["requires_operator_signer_identity_verification"]
    assert result["publish_authorized"] is False
    assert result["activation_authorized"] is False
    assert all(c["passed"] for c in result["checks"])


def test_identity_mismatch_fails_closed_even_with_valid_public_trust(tmp_path: Path) -> None:
    result = inspect_source(fixture(tmp_path, version="1.3.40", seq=1241))
    assert not result["source_stage_ready"]
    assert sum(not c["passed"] for c in result["checks"]) == 2


def test_cli_exits_2_when_unready_and_does_not_emit_secret_material(tmp_path: Path) -> None:
    repo = fixture(tmp_path, version="1.3.40", seq=1241, trusted=False)
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/clientflow_1242_source_preflight.py"), "--repo-root", str(repo)], capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["source_stage_ready"] is False
    assert "public_key_b64" not in completed.stdout
    assert "CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64" not in completed.stdout
    assert "public_key_b64" not in completed.stdout


def test_cli_source_ready_is_not_release_approval(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/clientflow_1242_source_preflight.py"), "--repo-root", str(repo)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert report["source_stage_ready"] is True
    assert report["publish_authorized"] is False
