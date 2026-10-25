"""Existing signer reuse: never rotate an already configured rollback key."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
from clientflow_existing_rollback_key import inspect_existing_key, public_trust_record, SPKI

# RFC 8032 example data, for tests ONLY. Never an operating or production signer.
RFC_EXAMPLE_PRIVATE = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc4" "4449c5697b326919703bac031cae7f60")


def signer():
    key = Ed25519PrivateKey.from_private_bytes(RFC_EXAMPLE_PRIVATE)
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    encoded = base64.b64encode(pem).decode("ascii")
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return encoded, hashlib.sha256(public).hexdigest()[:32], base64.urlsafe_b64encode(public[len(SPKI):]).rstrip(b"=").decode("ascii")


def repo_with_trust(tmp_path: Path, entry=None, enabled: bool = False) -> Path:
    repo = tmp_path / "repo"
    (repo / "client/release").mkdir(parents=True)
    (repo / "backend/service1").mkdir(parents=True)
    (repo / "client/release/rollback-trust.json").write_text(json.dumps({
        "schema_version": 1, "enabled": enabled, "keys": [entry] if entry else [],
    }), encoding="utf-8")
    (repo / "backend/service1/clientflow_release_security_policy.json").write_text(json.dumps({
        "schema_version": 1, "revision": 1, "minimum_safe_release_sequence": 1239, "revoked_release_ids": [],
    }), encoding="utf-8")
    return repo


def test_missing_does_not_claim_absent_from_external_vault(tmp_path):
    report = inspect_existing_key(environ={}, repo=repo_with_trust(tmp_path))
    assert report["status"] == "missing"
    assert report["key_id"] is None
    assert report["key_generated"] is False
    assert "separat" in report["note"]


def test_existing_signer_even_with_feature_disabled_is_reusable(tmp_path):
    encoded, key_id, public = signer()
    report = inspect_existing_key(environ={"CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": encoded, "CLIENTFLOW_SIGNED_ROLLBACK_ENABLED": "false"}, repo=repo_with_trust(tmp_path))
    assert report["status"] == "valid_existing_key"
    assert report["key_id"] == key_id
    assert report["public_key_b64"] == public
    assert report["source_trust"] == "disabled"
    assert report["backend_feature_activation_authorized"] is False
    assert report["release_publication_authorized"] is False
    assert report["feature_flag"] == "disabled"
    assert report["private_key_exported"] is False
    assert encoded not in json.dumps(report)


def test_existing_key_matches_source_immutably(tmp_path):
    encoded, key_id, public = signer()
    entry = {"key_id": key_id, "public_key_b64": public, "min_policy_revision": 1, "minimum_safe_release_sequence": 1239}
    repo = repo_with_trust(tmp_path, entry=entry, enabled=True)
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    report = inspect_existing_key(environ={"CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": encoded}, repo=repo)
    assert report["source_trust"] == "matches_existing_signer"
    assert before == {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert public_trust_record(report, json.loads((repo / "backend/service1/clientflow_release_security_policy.json").read_text())) == entry


def test_mismatched_source_does_not_accept_unrelated_key(tmp_path):
    encoded, key_id, public = signer()
    entry = {"key_id": "a" * 32, "public_key_b64": public, "min_policy_revision": 1, "minimum_safe_release_sequence": 1239}
    report = inspect_existing_key(environ={"CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": encoded}, repo=repo_with_trust(tmp_path, entry=entry, enabled=True))
    assert report["key_id"] == key_id
    assert report["source_trust"] == "no_matching_public_key"


def test_invalid_or_wrong_type_never_auto_replaced(tmp_path):
    path = repo_with_trust(tmp_path)
    bad = inspect_existing_key(environ={"CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": "***"}, repo=path)
    assert bad["status"] == "invalid_key" and bad["key_generated"] is False
    assert public_trust_record(bad, {"revision": 1, "minimum_safe_release_sequence": 1239}) is None
    flag = inspect_existing_key(environ={"CLIENTFLOW_SIGNED_ROLLBACK_ENABLED": "foo"}, repo=path)
    assert flag["status"] == "invalid_config"


def test_public_pinning_requires_valid_existing_key_and_policy(tmp_path):
    encoded, _, _ = signer()
    report = inspect_existing_key(environ={"CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": encoded}, repo=repo_with_trust(tmp_path))
    assert public_trust_record(report, {"revision": 0, "minimum_safe_release_sequence": 1239}) is None
    assert public_trust_record(report, {"revision": True, "minimum_safe_release_sequence": 1239}) is None
    assert public_trust_record(report, {"revision": 1, "minimum_safe_release_sequence": -1}) is None


def test_cli_never_prints_private_material(tmp_path):
    import os
    encoded, key_id, public = signer()
    repo = repo_with_trust(tmp_path)
    env = {**os.environ, "CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": encoded, "CLIENTFLOW_SIGNED_ROLLBACK_ENABLED": "false"}
    command = [sys.executable, str(ROOT / "backend/scripts/clientflow_existing_rollback_key.py"), "--repo-root", str(repo), "--public-trust"]
    proc = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "GENBRUG DEN" in proc.stdout
    assert key_id in proc.stdout and public in proc.stdout
    assert encoded not in proc.stdout
    assert base64.b64decode(encoded).decode("ascii") not in proc.stdout
    assert RFC_EXAMPLE_PRIVATE.hex() not in proc.stdout
    assert "private_key" not in proc.stdout
    assert not any(repo.rglob("*.pem"))


def test_invalid_key_cli_never_leaks_key(tmp_path):
    import os
    secret = "invalid_password_dont_print_123"
    env = {**os.environ, "CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64": secret}
    proc = subprocess.run([sys.executable, str(ROOT / "backend/scripts/clientflow_existing_rollback_key.py"), "--repo-root", str(repo_with_trust(tmp_path))], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert secret not in proc.stdout + proc.stderr


def test_cannot_use_update_private_key_purpose(tmp_path):
    # Signer inventory deliberately reads ONLY its dedicated rollback env var.
    encoded, _, _ = signer()
    report = inspect_existing_key(environ={"CLIENTFLOW_UPDATE_AUTH_PRIVATE_KEY": encoded}, repo=repo_with_trust(tmp_path))
    assert report["status"] == "missing"


def test_key_identifier_matches_existing_backend_signer(monkeypatch, tmp_path):
    encoded, expected_id, _ = signer()
    sys.path.insert(0, str(ROOT / "backend"))
    from service1.clientflow_rollback_signing import _signing_key
    monkeypatch.setenv("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "true")
    monkeypatch.setenv("CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64", encoded)
    _, backend_id = _signing_key()
    report = inspect_existing_key(repo=repo_with_trust(tmp_path))
    assert backend_id == expected_id == report["key_id"]
    assert report["feature_flag"] == "enabled"
    assert report["release_publication_authorized"] is False
