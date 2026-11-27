"""63D-6: exact two-release active catalog, no accidental promotion or rollout.

All tests are offline and independent of Render, Neon and client machines.
"""
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

from clientflow_63d6_active_catalog_contract import (  # noqa: E402
    ActiveCatalogDenied, projected_stable_1245, verified_mode,
)
from service1 import clientflow_releases as releases  # noqa: E402
from service1.clientflow_pilot_1246 import (  # noqa: E402
    ClientFlowPilot1246Denied, require_pilot_1246,
)
from service1.clientflow_pilot_1248 import (  # noqa: E402
    APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
)
from service1.clientflow_release_pilot_stage_1248 import (  # noqa: E402
    staged_pilot_summary_1248,
)

FILES = (
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1246_pilot.stage.json",
    "backend/service1/clientflow_pilot_1246_approval.json",
    "backend/service1/clientflow_release_catalog_1247_pilot.stage.json",
    "backend/service1/clientflow_pilot_1247_approval.json",
    "backend/service1/clientflow_release_catalog_1248_pilot.stage.json",
    "backend/service1/clientflow_pilot_1248_approval.json",
)


def _clone(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for name in FILES:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / (FILES[5] if name == FILES[0] else name), target)
    return repo


def _mutate_json(repo: Path, name: str, action) -> None:
    path = repo / name
    data = json.loads(path.read_text(encoding="utf-8"))
    action(data)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def historical_1248_catalog(tmp_path, monkeypatch):
    repo = _clone(tmp_path)
    monkeypatch.setattr(releases, "CATALOG_PATH", repo / FILES[0])
    releases.load_catalog.cache_clear()
    yield repo
    releases.load_catalog.cache_clear()


def test_historical_catalog_is_exact_pilot_source_without_any_pilot_authority(historical_1248_catalog):
    assert verified_mode(historical_1248_catalog) == "update_only_1248_pilot_catalog"
    active = releases.load_catalog()
    assert active["catalog_sequence"] == 1248
    assert active["latest_stable"] == active["default_install_version"] == "1.3.44"
    assert [row["release_sequence"] for row in active["releases"]] == [1245, 1247, 1248]
    stable, pilot, latest = active["releases"]
    assert stable["status"] == "stable"
    assert stable["install_modes"] == ["fresh_install", "in_place_update"]
    assert pilot["status"] == "supported"
    assert pilot["installable"] is False
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["min_current_version"] == "1.3.45"
    assert pilot["max_current_version"] == "1.3.45"
    assert latest["release_id"] == "clientflow-1.3.47-seq-1248"
    assert latest["installable"] is False
    assert latest["install_modes"] == ["in_place_update"]
    assert releases.resolve_fresh_install_release()["release_id"] == stable["release_id"]
    assert releases.resolve_release("1.3.46")["release_id"] == pilot["release_id"]
    assert releases.resolve_release("1.3.47")["release_id"] == latest["release_id"]
    with pytest.raises(releases.ClientFlowCatalogError):
        releases.resolve_release("1.3.45")
    releases.validate_release_compatibility(pilot, current_version="1.3.45", ubuntu_version="26.04")
    releases.validate_release_compatibility(latest, current_version="1.3.46", ubuntu_version="26.04")
    info = staged_pilot_summary_1248(active_catalog=active)
    assert info["active_catalog_promoted"] is True
    assert info["active_release_id"] == stable["release_id"]
    assert info["approved_bundle_sha256"] == APPROVED_BUNDLE_SHA256
    assert info["approved_bundle_size"] == APPROVED_BUNDLE_SIZE
    for name in (
        "render_store_publication_verified", "deployment_authorized", "fleet_authorized",
        "fresh_install_authorized", "physical_pilot_accepted", "database_cutover_authorized",
    ):
        assert info[name] is False


def test_source_gate_accepts_only_complete_pinned_baseline_or_pilot(tmp_path):
    repo = _clone(tmp_path)
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert verified_mode(repo) == "update_only_1248_pilot_catalog"
    baseline = projected_stable_1245(repo)
    assert baseline["catalog_sequence"] == 1245
    assert len(baseline["releases"]) == 1
    (repo / FILES[0]).write_text(json.dumps(baseline), encoding="utf-8")
    assert verified_mode(repo) == "stable_1245_only"
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert set(after) == set(before)
    assert all(before[name] == after[name] for name in before if str(name) != FILES[0])


@pytest.mark.parametrize("attack", (
    lambda d: d.update(catalog_sequence=1249),
    lambda d: d.update(default_install_version="1.3.45"),
    lambda d: d.update(latest_stable="1.3.45"),
    lambda d: d["releases"][0].update(notes=["unreviewed"]),
    lambda d: d["releases"][1].update(notes=["unreviewed"]),
    lambda d: d["releases"][1].update(status="stable"),
    lambda d: d["releases"][1].update(installable=True),
    lambda d: d["releases"][1].update(update_allowed=False),
    lambda d: d["releases"][1].update(install_modes=["fresh_install", "in_place_update"]),
    lambda d: d["releases"][1].update(rollback_allowed=True),
    lambda d: d["releases"][1].update(min_current_version="1.3.42"),
    lambda d: d["releases"].append(deepcopy(d["releases"][1])),
))
def test_modified_active_catalog_fails_even_when_json_is_valid(tmp_path, attack):
    repo = _clone(tmp_path)
    _mutate_json(repo, FILES[0], attack)
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


@pytest.mark.parametrize("name,attack", (
    (FILES[1], lambda d: d["releases"][1].update(notes=["unreviewed"])),
    (FILES[2], lambda d: d.update(approved_bundle_sha256="0" * 64)),
    (FILES[2], lambda d: d.update(approved=False)),
    (FILES[2], lambda d: d.update(approval_reference="unreviewed")),
))
def test_pinned_stage_and_approval_must_not_change(tmp_path, name, attack):
    repo = _clone(tmp_path)
    _mutate_json(repo, name, attack)
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


def test_symlink_stage_or_approval_is_rejected(tmp_path):
    repo = _clone(tmp_path)
    for name in (FILES[1], FILES[2]):
        dst = repo / name
        original = dst.read_bytes()
        dst.unlink()
        other = tmp_path / "external.json"
        other.write_bytes(original)
        dst.symlink_to(other)
        with pytest.raises(ActiveCatalogDenied):
            verified_mode(repo)
        dst.unlink()
        dst.write_bytes(original)


def test_duplicate_json_fields_cannot_replace_release_identity(tmp_path):
    repo = _clone(tmp_path)
    path = repo / FILES[0]
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace('"catalog_sequence": 1248,', '"catalog_sequence": 1248, "catalog_sequence": 1248,', 1))
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


def test_generic_runtime_loader_fails_closed_on_mutated_pilot(tmp_path, monkeypatch):
    repo = _clone(tmp_path)
    _mutate_json(repo, FILES[0], lambda d: d["releases"][1].update(notes=["altered"] ))
    with monkeypatch.context() as patch:
        patch.setattr(releases, "CATALOG_PATH", repo / FILES[0])
        releases.load_catalog.cache_clear()
        try:
            with pytest.raises(releases.ClientFlowCatalogError):
                releases.load_catalog()
        finally:
            releases.load_catalog.cache_clear()


def test_catalog_does_not_arm_exact_client_bound_pilot(monkeypatch):
    for flag in ("CLIENTFLOW_1246_PILOT_CLIENT_ID", "CLIENTFLOW_1246_PILOT_ARM_REFERENCE"):
        monkeypatch.delenv(flag, raising=False)
    with pytest.raises(ClientFlowPilot1246Denied, match="særskilt klientbundet"):
        require_pilot_1246(
            client_id=3,
            current_version="1.3.43",
            release=json.loads((ROOT / "backend/service1/clientflow_release_catalog_1246_pilot.stage.json").read_text())["releases"][1],
            reason="Fysisk Viborg1-test efter separat godkendelse",
            pre_first_activation_repair=False,
            confirm_downgrade=False,
        )
