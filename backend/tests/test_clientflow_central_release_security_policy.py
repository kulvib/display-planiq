"""Regression gates for code-reviewed central release safety policy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1 import clientflow_release_security_policy as policy


def _set_policy(monkeypatch, tmp_path, *, floor=1239, revoked=(), revision=1):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "revision": revision,
        "minimum_safe_release_sequence": floor,
        "revoked_release_ids": list(revoked),
    }))
    monkeypatch.setattr(policy, "POLICY_PATH", path)
    return path


def test_default_policy_preserves_existing_pilot():
    policy.require_centrally_eligible_release(
        release_id="clientflow-1.3.38-seq-1239", release_sequence=1239,
    )
    policy.require_centrally_eligible_release(
        release_id="clientflow-1.3.40-seq-1241", release_sequence=1241,
    )


def test_floor_prevents_old_release_and_preserves_new(monkeypatch, tmp_path):
    _set_policy(monkeypatch, tmp_path, floor=1241)
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied, match="minimumssikkerhedssekvens"):
        policy.require_centrally_eligible_release(
            release_id="clientflow-1.3.38-seq-1239", release_sequence=1239,
        )
    policy.require_centrally_eligible_release(
        release_id="clientflow-1.3.40-seq-1241", release_sequence=1241,
    )


def test_revocation_blocks_exact_release_even_above_floor(monkeypatch, tmp_path):
    _set_policy(monkeypatch, tmp_path, revoked=["clientflow-1.3.40-seq-1241"])
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied, match="tilbagekaldt"):
        policy.require_centrally_eligible_release(
            release_id="clientflow-1.3.40-seq-1241", release_sequence=1241,
        )
    policy.require_centrally_eligible_release(
        release_id="clientflow-1.3.38-seq-1239", release_sequence=1239,
    )


@pytest.mark.parametrize("release_id,sequence", [
    ("clientflow-1.3.40-seq-1241", 1239),
    ("clientflow-1.3.40-seq-1241", True),
    ("clientflow-1.3.40-seq-1241", "1241"),
    ("clientflow-1.3.40-seq-0", 0),
    ("clientflow-1.3.40-seq-1241/../../x", 1241),
    ("clientflow-1.3.40-seq-01241", 1241),
    ("clientflow-1.3.40-seq-" + "1" * 200, 1241),
    (None, 1241),
])
def test_identity_mismatch_rejected(release_id, sequence):
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied):
        policy.require_centrally_eligible_release(
            release_id=release_id, release_sequence=sequence,
        )


@pytest.mark.parametrize("invalid", [
    {},
    {"schema_version": 2},
    {"schema_version": True, "revision": 1, "minimum_safe_release_sequence": 1239, "revoked_release_ids": []},
    {"schema_version": 1, "revision": True, "minimum_safe_release_sequence": 1239, "revoked_release_ids": []},
    {"schema_version": 1, "revision": 0, "minimum_safe_release_sequence": 1239, "revoked_release_ids": []},
    {"schema_version": 1, "revision": 1, "minimum_safe_release_sequence": False, "revoked_release_ids": []},
    {"schema_version": 1, "revision": 1, "minimum_safe_release_sequence": 1, "revoked_release_ids": ["bad-id"]},
    {"schema_version": 1, "revision": 1, "minimum_safe_release_sequence": 1, "revoked_release_ids": ["clientflow-1.3.40-seq-1241"] * 2},
    {"schema_version": 1, "revision": 1, "minimum_safe_release_sequence": 1, "revoked_release_ids": [], "bypass": True},
])
def test_invalid_policy_fails_closed(monkeypatch, tmp_path, invalid):
    path = _set_policy(monkeypatch, tmp_path)
    path.write_text(json.dumps(invalid))
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied, match="ugyldig"):
        policy.require_centrally_eligible_release(
            release_id="clientflow-1.3.40-seq-1241", release_sequence=1241,
        )


def test_missing_and_oversize_policy_fail_closed(monkeypatch, tmp_path):
    path = _set_policy(monkeypatch, tmp_path)
    path.unlink()
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied):
        policy.read_release_security_policy()
    path.write_bytes(b"X" * 16385)
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied):
        policy.read_release_security_policy()


def test_revocation_takes_effect_at_each_read_without_restart(monkeypatch, tmp_path):
    path = _set_policy(monkeypatch, tmp_path)
    policy.require_centrally_eligible_release(
        release_id="clientflow-1.3.40-seq-1241", release_sequence=1241,
    )
    path.write_text(json.dumps({"schema_version": 1, "revision": 2,
        "minimum_safe_release_sequence": 1239,
        "revoked_release_ids": ["clientflow-1.3.40-seq-1241"]}))
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied):
        policy.require_centrally_eligible_release(
            release_id="clientflow-1.3.40-seq-1241", release_sequence=1241,
        )


def test_boundary_contracts_wired_into_all_three_stages():
    root = Path(__file__).resolve().parents[2] / "backend/service1"
    for module, boundary in (
        ("clientflow_releases.py", "def resolve_release"),
        ("clientflow_releases.py", "def resolve_fresh_install_release"),
        ("clientflow_artifact_auth.py", "def _require_downloadable"),
        ("clientflow_deployments.py", "def authorize_activation"),
    ):
        source = (root / module).read_text()
        scoped = source.split(boundary, 1)[1].split("\ndef ", 1)[0]
        assert "require_centrally_eligible_release" in scoped, (module, boundary)


def test_preexisting_fresh_install_proofs_cannot_bypass_central_revocation():
    root = Path(__file__).resolve().parents[2] / "backend/service1/routers"
    source = (root / "enrollment.py").read_text()
    for boundary in (
        "def fresh_install_bootstrap",
        "def download_fresh_install_artifact",
        "def _verify_initial_fresh_install_authorization",
    ):
        scoped = source.split(boundary, 1)[1].split("\ndef ", 1)[0]
        assert "_enforce_fresh_install_security" in scoped, boundary


def test_revoked_pilot_blocked_by_real_catalog_resolution(monkeypatch, tmp_path):
    from service1.clientflow_releases import resolve_release

    _set_policy(monkeypatch, tmp_path, revoked=["clientflow-1.3.40-seq-1241"])
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied, match="tilbagekaldt"):
        resolve_release("1.3.40")


def test_floor_blocks_real_fresh_install_catalog_target(monkeypatch, tmp_path):
    from service1.clientflow_releases import resolve_fresh_install_release

    _set_policy(monkeypatch, tmp_path, floor=1241)
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied, match="minimumssikkerhedssekvens"):
        resolve_fresh_install_release()


def test_later_policy_update_rejects_previously_selectable_target(monkeypatch, tmp_path):
    from service1.clientflow_releases import resolve_release

    path = _set_policy(monkeypatch, tmp_path)
    assert resolve_release("1.3.40")["release_id"] == "clientflow-1.3.40-seq-1241"
    path.write_text(json.dumps({"schema_version": 1, "revision": 2,
        "minimum_safe_release_sequence": 1239,
        "revoked_release_ids": ["clientflow-1.3.40-seq-1241"]}))
    with pytest.raises(policy.ClientFlowReleaseSecurityDenied):
        resolve_release("1.3.40")
