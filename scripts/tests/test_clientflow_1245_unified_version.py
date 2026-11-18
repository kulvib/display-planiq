"""Two-phase 1245 identity: pilot 1244 stable, promoted 1245 single stable."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
from clientflow_1245_unified_version_preflight import inspect  # noqa: E402
from service1 import clientflow_releases as releases  # noqa: E402

SOURCE_FILES = (
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1246_pilot.stage.json",
    "backend/service1/clientflow_pilot_1246_approval.json",
    "backend/service1/clientflow_release_catalog_1245_stable.stage.json",
    "backend/service1/clientflow_pilot_1245_approval.json",
    "backend/service1/clientflow_1245_fleet_acceptance.json",
    "backend/service1/clientflow_pilot_1245.py",
    "backend/service1/clientflow_stable_rollout.py",
    "backend/service1/clientflow_fresh_install_maintenance.py",
    "client/VERSION",
    "client/release/release-input.json",
    "client/release/rollback-trust.json",
)


def _copy(tmp_path):
    repo = tmp_path / "repo"
    for name in SOURCE_FILES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path)
    return repo


def _mutate(repo, name, change):
    p = repo / name
    d = json.loads(p.read_text())
    change(d)
    p.write_text(json.dumps(d), encoding="utf-8")


def test_pilot_stage_and_single_stable_are_distinct_read_only_phases():
    result = inspect(ROOT)
    assert result["ready"], result
    assert len(result["checks"]) == 13
    assert result["pilot_enabled_by_this_preflight"] is False
    assert result["stable_promotion_applied"] is True
    assert result["fresh_install_hold_changed"] is False


def test_preflight_never_writes_any_file(tmp_path):
    repo = _copy(tmp_path)
    old = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert inspect(repo)["ready"]
    assert old == {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}


def test_stable_template_passes_catalog_validator_and_resolves_both_routes(monkeypatch):
    stage = ROOT / "backend/service1/clientflow_release_catalog_1245_stable.stage.json"
    monkeypatch.setattr(releases, "CATALOG_PATH", stage)
    releases.load_catalog.cache_clear()
    try:
        catalog = releases.load_catalog()
        assert len(catalog["releases"]) == 1
        assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.44"
        assert releases.resolve_fresh_install_release()["release_id"] == "clientflow-1.3.44-seq-1245"
        assert releases.resolve_release("1.3.44")["release_id"] == "clientflow-1.3.44-seq-1245"
    finally:
        releases.load_catalog.cache_clear()


@pytest.mark.parametrize("change", [
    lambda d: d.update(default_install_version="1.3.43"),
    lambda d: d.update(latest_stable="1.3.43"),
    lambda d: d["releases"].append(deepcopy(d["releases"][0])),
    lambda d: d["releases"][0].update(status="supported"),
    lambda d: d["releases"][0].update(install_modes=["fresh_install"]),
    lambda d: d["releases"][0].update(install_modes=["in_place_update"]),
    lambda d: d["releases"][0].update(update_allowed=False),
    lambda d: d["releases"][0].update(installable=False),
    lambda d: d["releases"][0].update(rollback_allowed=True),
    lambda d: d["releases"][0].update(max_current_version="1.3.42"),
    lambda d: d["releases"][0].update(min_current_version="1.3.11"),
])
def test_single_stable_template_rejects_policy_mutations(tmp_path, monkeypatch, change):
    stage = json.loads((ROOT / "backend/service1/clientflow_release_catalog_1245_stable.stage.json").read_text())
    change(stage)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(stage))
    monkeypatch.setattr(releases, "CATALOG_PATH", path)
    releases.load_catalog.cache_clear()
    try:
        with pytest.raises(releases.ClientFlowCatalogError):
            releases.load_catalog()
    finally:
        releases.load_catalog.cache_clear()


@pytest.mark.parametrize("mutate_file,change", [
    ("backend/service1/clientflow_pilot_1245_approval.json", lambda d: d.update(approved_bundle_sha256="0" * 64)),
    ("backend/service1/clientflow_release_catalog.json", lambda d: d.update(latest_stable="1.3.43")),
    ("backend/service1/clientflow_release_catalog_1245_stable.stage.json", lambda d: d.update(default_install_version="1.3.43")),
    ("backend/service1/clientflow_release_catalog_1245_stable.stage.json", lambda d: d["releases"][0].update(install_modes=["fresh_install"])),
    ("backend/service1/clientflow_release_catalog_1245_stable.stage.json", lambda d: d["releases"][0].update(rollback_allowed=True)),
    ("backend/service1/clientflow_1245_fleet_acceptance.json", lambda d: d.update(physical_pilot_accepted=True)),
])
def test_preflight_fails_on_mutated_release_identity(tmp_path, mutate_file, change):
    repo = _copy(tmp_path)
    _mutate(repo, mutate_file, change)
    assert not inspect(repo)["ready"]
