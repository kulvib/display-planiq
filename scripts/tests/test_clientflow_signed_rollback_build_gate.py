"""Guard the 1242 transition before an immutable candidate is written."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from clientflow_release.builder import build  # noqa: E402
from clientflow_release.rollback_trust_build import validate_release_rollback_trust  # noqa: E402


PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
SPKI = bytes.fromhex("302a300506032b6570032100")


def _fixture(tmp_path: Path) -> tuple[Path, dict, dict]:
    repo = tmp_path / "repo"
    (repo / "client/release").mkdir(parents=True)
    (repo / "backend/service1").mkdir(parents=True)
    policy = {
        "schema_version": 1,
        "revision": 3,
        "minimum_safe_release_sequence": 1239,
        "revoked_release_ids": [],
    }
    public_key_b64 = base64.urlsafe_b64encode(PUBLIC_KEY).rstrip(b"=").decode("ascii")
    key = {
        "key_id": hashlib.sha256(SPKI + PUBLIC_KEY).hexdigest()[:32],
        "public_key_b64": public_key_b64,
        "min_policy_revision": 3,
        "minimum_safe_release_sequence": 1239,
    }
    trust = {"schema_version": 1, "enabled": True, "keys": [key]}
    _save(repo, trust, policy)
    return repo, trust, policy


def _save(repo: Path, trust: dict, policy: dict) -> None:
    (repo / "client/release/rollback-trust.json").write_text(
        json.dumps(trust), encoding="utf-8"
    )
    (repo / "backend/service1/clientflow_release_security_policy.json").write_text(
        json.dumps(policy), encoding="utf-8"
    )


def test_current_1241_is_backward_compatible() -> None:
    validate_release_rollback_trust(ROOT, 1241)


def test_next_release_needs_trust_before_any_build_output(tmp_path: Path) -> None:
    repo, trust, policy = _fixture(tmp_path)
    trust.update(enabled=False, keys=[])
    _save(repo, trust, policy)
    (repo / "client/VERSION").write_text("1.3.41", encoding="utf-8")
    (repo / "client/release/release-input.json").write_text(
        json.dumps({"release_sequence": 1242}), encoding="utf-8"
    )
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="aktiveret immutable rollback-trust"):
        build(repo, output, runtime_inputs=None, allow_dirty=True)
    assert not output.exists()


def test_valid_pinned_1242_trust(tmp_path: Path) -> None:
    repo, _, _ = _fixture(tmp_path)
    validate_release_rollback_trust(repo, 1242)


@pytest.mark.parametrize(
    "change",
    [
        "disabled",
        "missing",
        "no_keys",
        "bad_key_id",
        "duplicate",
        "old_policy",
        "weak_sequence",
        "bad_base64",
        "bool_floor",
        "bad_schema",
    ],
)
def test_future_release_rejects_unsafe_trust(tmp_path: Path, change: str) -> None:
    repo, trust, policy = _fixture(tmp_path)
    key = trust["keys"][0]
    if change == "disabled":
        trust.update(enabled=False, keys=[])
    elif change == "missing":
        (repo / "client/release/rollback-trust.json").unlink()
        with pytest.raises(ValueError):
            validate_release_rollback_trust(repo, 1242)
        return
    elif change == "no_keys":
        trust["keys"] = []
    elif change == "bad_key_id":
        key["key_id"] = "0" * 32
    elif change == "duplicate":
        trust["keys"].append(dict(key))
    elif change == "old_policy":
        key["min_policy_revision"] = 2
    elif change == "weak_sequence":
        key["minimum_safe_release_sequence"] = 1238
    elif change == "bad_base64":
        key["public_key_b64"] = "xyz"
    elif change == "bool_floor":
        key["minimum_safe_release_sequence"] = True
    elif change == "bad_schema":
        trust["unexpected"] = True
    _save(repo, trust, policy)
    with pytest.raises(ValueError):
        validate_release_rollback_trust(repo, 1242)


def test_future_release_rejects_unreviewed_backend_policy(tmp_path: Path) -> None:
    repo, trust, policy = _fixture(tmp_path)
    policy["revision"] = True
    _save(repo, trust, policy)
    with pytest.raises(ValueError, match="Central releasepolitik"):
        validate_release_rollback_trust(repo, 1242)


def test_future_release_rejects_noncanonical_trust_json(tmp_path: Path) -> None:
    repo, _, _ = _fixture(tmp_path)
    path = repo / "client/release/rollback-trust.json"
    path.write_text(
        '{"schema_version":1,"enabled":true,"enabled":false,"keys":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dubleret"):
        validate_release_rollback_trust(repo, 1242)


def test_future_version_cannot_reuse_legacy_sequence(tmp_path: Path) -> None:
    repo, _, _ = _fixture(tmp_path)
    (repo / "client/VERSION").write_text("1.3.41", encoding="utf-8")
    (repo / "client/release/release-input.json").write_text(
        json.dumps({"release_sequence": 1241}), encoding="utf-8"
    )
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="sekvensgrænsen"):
        build(repo, output, runtime_inputs=None, allow_dirty=True)
    assert not output.exists()
