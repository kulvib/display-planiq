"""R2 exact-byte staging is read-only, fail-closed and does not enable deployment."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clientflow_1245_r2_pilot_preflight import inspect  # noqa: E402

FILES = (
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1245_pilot.stage.json",
    "backend/service1/clientflow_pilot_1245_approval.json",
    "backend/service1/clientflow_pilot_1245.py",
    "client/VERSION",
    "client/release/release-input.json",
    "client/release/rollback-trust.json",
)


def _copy(tmp_path):
    dest = tmp_path / "repo"
    for name in FILES:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    return dest


def _edit(dest, filename, change):
    target = dest / filename
    obj = json.loads(target.read_text(encoding="utf-8"))
    change(obj)
    target.write_text(json.dumps(obj), encoding="utf-8")


def test_r2_staged_source_passes_but_does_not_authorize_pilot():
    result = inspect(ROOT)
    assert result["ready"], result
    assert len(result["checks"]) == 9
    assert result["pilot_authorized"] is False
    assert result["catalog_promoted"] is False
    assert result["physical_recovery_verified"] is False


def test_preflight_is_read_only(tmp_path):
    dest = _copy(tmp_path)
    before = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    assert inspect(dest)["ready"]
    after = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize("name,value", [
    ("approved", True),
    ("approved", "false"),
    ("approved_bundle_sha256", "0" * 64),
    ("approved_bundle_size", 1),
    ("approval_reference", "wrong"),
    ("source_commit", "0" * 40),
    ("installer_sha256", "0" * 64),
    ("candidate_sha256", "0" * 64),
])
def test_r2_lock_tampering_fails(tmp_path, name, value):
    dest = _copy(tmp_path)
    _edit(dest, "backend/service1/clientflow_pilot_1245_approval.json", lambda x: x.update({name: value}))
    assert not inspect(dest)["ready"]
    assert not inspect(dest)["checks"]["approval_lock_r2_exact_but_disabled"]


@pytest.mark.parametrize("change", [
    lambda x: x.update(catalog_sequence=1245),
    lambda x: x.update(latest_stable="1.3.44"),
    lambda x: x.update(default_install_version="1.3.44"),
    lambda x: x["releases"].append({"release_id": "clientflow-1.3.44-seq-1245"}),
])
def test_live_catalog_must_stay_1244(tmp_path, change):
    dest = _copy(tmp_path)
    _edit(dest, "backend/service1/clientflow_release_catalog.json", change)
    assert not inspect(dest)["ready"]


@pytest.mark.parametrize("change", [
    lambda x: x.update(latest_stable="1.3.44"),
    lambda x: x.update(default_install_version="1.3.44"),
    lambda x: x["releases"][0].update(update_allowed=True),
    lambda x: x["releases"][0].update(rollback_allowed=True),
    lambda x: x["releases"][1].update(installable=True),
    lambda x: x["releases"][1].update(status="stable"),
    lambda x: x["releases"][1].update(update_allowed=False),
    lambda x: x["releases"][1].update(install_modes=["fresh_install", "in_place_update"]),
    lambda x: x["releases"][1].update(min_current_version="1.3.42"),
    lambda x: x["releases"][1].update(max_current_version="1.3.44"),
    lambda x: x["releases"][1].update(release_sequence=1246),
    lambda x: x["releases"].append({"release_id": "unapproved"}),
])
def test_staged_catalog_tampering_fails(tmp_path, change):
    dest = _copy(tmp_path)
    _edit(dest, "backend/service1/clientflow_release_catalog_1245_pilot.stage.json", change)
    assert not inspect(dest)["ready"]


def test_missing_stage_file_fails(tmp_path):
    dest = _copy(tmp_path)
    (dest / "backend/service1/clientflow_release_catalog_1245_pilot.stage.json").unlink()
    assert not inspect(dest)["ready"]


def test_pilot_guard_stays_disabled_with_real_record_even_when_env_is_three(monkeypatch):
    sys.path.insert(0, str(ROOT / "backend"))
    from service1 import clientflow_pilot_1245 as pilot

    monkeypatch.setenv(pilot.PILOT_FLAG, "3")
    release = json.loads(
        (ROOT / "backend/service1/clientflow_release_catalog_1245_pilot.stage.json").read_text(encoding="utf-8")
    )["releases"][1]
    with pytest.raises(pilot.ClientFlowPilot1245Denied, match="ikke særskilt godkendt"):
        pilot.require_pilot_1245(
            client_id=3, current_version="1.3.43", release=release,
            reason="Afgrænset pilot på Viborg1",
            pre_first_activation_repair=False, confirm_downgrade=False,
        )


def test_staged_catalog_passes_production_catalog_validator_only_in_isolation(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "backend"))
    from service1 import clientflow_releases

    stage = ROOT / "backend/service1/clientflow_release_catalog_1245_pilot.stage.json"
    monkeypatch.setattr(clientflow_releases, "CATALOG_PATH", stage)
    clientflow_releases.load_catalog.cache_clear()
    try:
        result = clientflow_releases.load_catalog()
        assert result["catalog_sequence"] == 1245
        assert result["latest_stable"] == result["default_install_version"] == "1.3.43"
        assert clientflow_releases.resolve_fresh_install_release()["release_id"] == "clientflow-1.3.43-seq-1244"
    finally:
        clientflow_releases.load_catalog.cache_clear()
