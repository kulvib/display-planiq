"""Exact 1242 source-stage authority boundary: no silent catalog or rollback escalation."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for library in (ROOT / "backend", ROOT / "client/release/lib", ROOT / "scripts"):
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))

from clientflow_1242_source_preflight import inspect_source  # noqa: E402
from clientflow_release.rollback_trust_build import validate_release_rollback_trust  # noqa: E402
from clientflow_release.rollback_verifier import _trust  # noqa: E402
from clientflow_release_format.rollback_permit import RollbackPermitError  # noqa: E402


def _json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_exact_source_identity_and_strict_1242_pilot_catalog() -> None:
    assert (ROOT / "client/VERSION").read_text(encoding="utf-8").strip() == "1.3.41"
    source = _json("client/release/release-input.json")
    assert source == {
        "schema_version": 1,
        "release_sequence": 1242,
        "minimum_ubuntu_lts": "26.04",
        "architecture": "amd64",
        "runtime_python": "3.13.14",
    }
    catalog = _json("backend/service1/clientflow_release_catalog.json")
    assert catalog["catalog_sequence"] == 1242
    assert source["release_sequence"] == catalog["catalog_sequence"]
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert catalog["retention_policy"] == {"max_installable_versions": 1, "keep_blocked_metadata": False}
    assert [x["release_id"] for x in catalog["releases"]] == [
        "clientflow-1.3.38-seq-1239", "clientflow-1.3.40-seq-1241",
        "clientflow-1.3.41-seq-1242",
    ]
    assert sum(x["release_sequence"] == 1242 for x in catalog["releases"]) == 1
    stable, pilot = catalog["releases"][:2]
    assert stable["status"] == "stable" and stable["installable"] is True
    assert stable["install_modes"] == ["fresh_install"]
    assert stable["update_allowed"] is False and stable["rollback_allowed"] is False
    assert pilot["status"] == "supported" and pilot["installable"] is False
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["min_current_version"] == pilot["max_current_version"] == "1.3.38"
    assert pilot["rollback_allowed"] is False
    new_pilot = catalog["releases"][2]
    assert new_pilot["release_id"] == "clientflow-1.3.41-seq-1242"
    assert new_pilot["install_modes"] == ["in_place_update"]
    assert new_pilot["installable"] is False and new_pilot["rollback_allowed"] is False
    assert new_pilot["min_current_version"] == new_pilot["max_current_version"] == "1.3.38"


def test_keyless_1242_source_preflight_is_not_publication_or_activation_approval() -> None:
    trust = _json("client/release/rollback-trust.json")
    assert trust == {"schema_version": 1, "enabled": False, "keys": []}
    assert _json("backend/service1/clientflow_release_security_policy.json") == {
        "schema_version": 1, "revision": 1,
        "minimum_safe_release_sequence": 1239, "revoked_release_ids": [],
    }
    validate_release_rollback_trust(ROOT, 1242)
    report = inspect_source(ROOT)
    assert report["source_stage_ready"] is True
    assert report["phase"] == "source_stage_only"
    assert report["manual_rollback_mode"] == "disabled"
    assert report["publish_authorized"] is False
    assert report["activation_authorized"] is False
    assert report["requires_operator_signer_identity_verification"] is False
    assert report["requires_physical_pilot"] is True


def test_1242_runtime_cannot_fall_back_to_unsigned_manual_rollback(tmp_path: Path) -> None:
    root = tmp_path / "releases"
    release_id = "clientflow-1.3.41-seq-1242"
    trust = root / release_id / "release/rollback-trust.json"
    trust.parent.mkdir(parents=True)
    trust.write_text(json.dumps({"schema_version": 1, "enabled": False, "keys": []}), encoding="utf-8")
    layout = SimpleNamespace(releases=root)
    with pytest.raises(RollbackPermitError, match="kræver aktiveret rollback-trust"):
        _trust(layout, release_id)
    trust.unlink()
    with pytest.raises(RollbackPermitError, match="mangler obligatorisk rollback-trust"):
        _trust(layout, release_id)


def test_release_workflows_and_operator_stage_limits_are_unchanged() -> None:
    release = (ROOT / ".github/workflows/release-build.yml").read_text(encoding="utf-8")
    approval = (ROOT / ".github/workflows/release-approve.yml").read_text(encoding="utf-8")
    assert "expected_source_sha" in release and "verify_github_ci_run.py" in release
    assert "matrix:" in release and "replica: [a, b]" in release
    assert "expected_candidate_sha256" in approval and "expected_installer_sha256" in approval
    assert "approve_release" in approval and 'test "$APPROVE_RELEASE" = "true"' in approval
    stage = (ROOT / "CLIENTFLOW_1.3.41_1242_SOURCE_STAGE.md").read_text(encoding="utf-8")
    for token in (
        "STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published", "NOT catalog-promoted",
        "exact-source", "manual rollback disabled", "automatic failed-activation recovery",
        "Ubuntu 26.04", "Heidi1", "Livestream", "Remote Desktop", "Do not auto-activate",
    ):
        assert token in stage, token
