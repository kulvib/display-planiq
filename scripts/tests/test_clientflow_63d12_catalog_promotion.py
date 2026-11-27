"""63D-12/19: source-only promotion of the EXACT approved 1248 pilot catalog.

No DB connection, client update, Render or network access.
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
from clientflow_63d6_active_catalog_contract import (  # noqa: E402
    ActiveCatalogDenied, verified_mode,
)

FILES = (
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1246_pilot.stage.json",
    "backend/service1/clientflow_release_catalog_1248_pilot.stage.json",
    "backend/service1/clientflow_pilot_1246_approval.json",
    "backend/service1/clientflow_pilot_1248_approval.json",
    "backend/service1/clientflow_release_catalog_1247_pilot.stage.json",
    "backend/service1/clientflow_pilot_1247_approval.json",
)


def _fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for name in FILES:
        dest = repo / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / (FILES[2] if name == FILES[0] else name), dest)
    return repo


def _put(repo: Path, name: str, data: dict) -> None:
    (repo / name).write_text(json.dumps(data), encoding="utf-8")


def test_promoted_catalog_is_exact_pinned_stage_and_does_not_open_rollout(tmp_path):
    repo = _fixture(tmp_path)
    live = (repo / FILES[0]).read_bytes()
    stage = (ROOT / FILES[2]).read_bytes()
    assert live == stage
    assert verified_mode(repo) == "update_only_1248_pilot_catalog"
    record = json.loads(live)
    assert record["catalog_sequence"] == 1248
    assert record["latest_stable"] == record["default_install_version"] == "1.3.44"
    assert [r["release_sequence"] for r in record["releases"]] == [1245, 1247, 1248]
    assert [r["installable"] for r in record["releases"]] == [True, False, False]
    assert [r["status"] for r in record["releases"]] == ["stable", "supported", "supported"]
    assert all(r["rollback_allowed"] is False for r in record["releases"])
    assert record["releases"][2]["install_modes"] == ["in_place_update"]
    assert record["releases"][2]["min_current_version"] == "1.3.46"
    assert record["releases"][2]["max_current_version"] == "1.3.46"


@pytest.mark.parametrize("attack", (
    lambda d: d.update(catalog_sequence=1249),
    lambda d: d.update(default_install_version="1.3.46"),
    lambda d: d.update(latest_stable="1.3.46"),
    lambda d: d["releases"][0].update(installable=False),
    lambda d: d["releases"][1].update(notes=["old record changed"]),
    lambda d: d["releases"][2].update(installable=True),
    lambda d: d["releases"][2].update(rollback_allowed=True),
    lambda d: d["releases"][2].update(install_modes=["fresh_install"]),
    lambda d: d["releases"][2].update(min_current_version="1.3.44"),
    lambda d: d["releases"].append(deepcopy(d["releases"][2])),
))
def test_rehashed_but_unapproved_catalog_rejected(tmp_path, attack):
    repo = _fixture(tmp_path)
    path = repo / FILES[0]
    content = json.loads(path.read_text())
    attack(content)
    _put(repo, FILES[0], content)
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


@pytest.mark.parametrize("name", (FILES[2], FILES[4]))
def test_modified_pinned_stage_or_approval_rejected(tmp_path, name):
    repo = _fixture(tmp_path)
    path = repo / name
    payload = json.loads(path.read_text())
    if name == FILES[2]:
        payload["releases"][2]["notes"] = ["unapproved stage"]
    else:
        payload["approved_bundle_sha256"] = "0" * 64
    _put(repo, name, payload)
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


@pytest.mark.parametrize("name", (FILES[0], FILES[2], FILES[4]))
def test_symlinked_catalog_stage_or_approval_rejected(tmp_path, name):
    repo = _fixture(tmp_path)
    path = repo / name
    data = path.read_bytes()
    path.unlink()
    external = tmp_path / "external.json"
    external.write_bytes(data)
    path.symlink_to(external)
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


def test_duplicate_active_json_field_rejected(tmp_path):
    repo = _fixture(tmp_path)
    path = repo / FILES[0]
    content = path.read_text()
    assert '"catalog_sequence": 1248,' in content
    path.write_text(content.replace(
        '"catalog_sequence": 1248,',
        '"catalog_sequence": 1248, "catalog_sequence": 1248,', 1,
    ))
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(repo)


def test_prior_baselines_still_allowed_as_historical_snapshots(tmp_path):
    repo = _fixture(tmp_path)
    stage = json.loads((repo / FILES[1]).read_text())
    _put(repo, FILES[0], stage)
    assert verified_mode(repo) == "update_only_1246_pilot_catalog"
    _put(repo, FILES[0], {
        **stage, "catalog_sequence": 1245, "releases": stage["releases"][:1],
    })
    assert verified_mode(repo) == "stable_1245_only"
