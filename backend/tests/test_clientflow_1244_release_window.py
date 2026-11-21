"""Future 1244+ catalog must never silently reopen retired release versions."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from service1 import clientflow_releases as releases

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "scripts/tests/fixtures/clientflow_1244_pre_1245_pilot_catalog.json"


def _future(*sequences: int) -> dict:
    # The exact 1244 reset is fresh-only. Later synthetic catalog examples
    # model independent future approvals, not a retroactive authorization.
    if sequences == (1244,):
        return json.loads(CATALOG.read_text())
    old = json.loads(CATALOG.read_text())
    base = deepcopy(old["releases"][0])
    rows = []
    for seq in sequences:
        version = f"1.3.{seq - 1201}"
        row = deepcopy(base)
        row.update({
            "version": version,
            "client_version": version,
            "release_sequence": seq,
            "release_id": f"clientflow-{version}-seq-{seq}",
            "revision": f"clientflow-{version}-seq-{seq}",
            "status": "supported",
            "installable": False,
            "update_allowed": True,
            "install_modes": ["in_place_update"],
            "min_current_version": "1.3.43",
            "max_current_version": "1.3.43",
        })
        rows.append(row)
    latest = rows[-1]
    latest.update({
        "status": "stable", "installable": True,
        "install_modes": ["fresh_install", "in_place_update"],
    })
    old.update({
        "catalog_sequence": sequences[-1],
        "latest_stable": latest["version"],
        "default_install_version": latest["version"],
        "retention_policy": {
            "max_installable_versions": 1,
            "max_selectable_versions": 3,
            "keep_blocked_metadata": False,
        },
        "releases": rows,
    })
    return old


def _load(tmp_path, monkeypatch, payload):
    p = tmp_path / "future-catalog.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(releases, "CATALOG_PATH", p)
    releases.load_catalog.cache_clear()
    try:
        return releases.load_catalog()
    finally:
        releases.load_catalog.cache_clear()


@pytest.mark.parametrize("sequences", [
    (1244,), (1245,),
])
def test_one_to_three_only_latest_stable(tmp_path, monkeypatch, sequences):
    # Future window policy can be exercised with synthetic catalogs, except
    # for 1246: that sequence now has a separately pinned, update-only source
    # identity and must not accept an invented stable/fresh-install variant.
    payload = _future(*sequences)
    actual = _load(tmp_path, monkeypatch, payload)
    assert [r["release_sequence"] for r in actual["releases"]] == list(sequences)
    assert actual["default_install_version"] == payload["releases"][-1]["version"]


@pytest.mark.parametrize("sequences", [
    (1246,), (1244, 1245, 1246),
])
def test_unapproved_synthetic_stable_1246_fails_closed(tmp_path, monkeypatch, sequences):
    # The former three-release synthetic fixture must NOT bypass the exact
    # 1246 source lock by turning 1246 into the fresh-install default.
    with pytest.raises(releases.ClientFlowCatalogError,
                       match="1246-katalogets godkendte autoritet"):
        _load(tmp_path, monkeypatch, _future(*sequences))


def test_unapproved_synthetic_stable_1247_fails_closed(tmp_path, monkeypatch):
    # Sequence 1247 now has an exact approved update-only, 1246->1247 identity.
    # Historical synthetic newest-stable shapes must never bypass it.
    with pytest.raises(releases.ClientFlowCatalogError,
                       match="1247-kataloget mangler præcist godkendt kildeautoritet"):
        _load(tmp_path, monkeypatch, _future(1245, 1246, 1247))


def test_exact_1247_update_only_pilot_stage_is_accepted(tmp_path, monkeypatch):
    from service1.clientflow_release_pilot_stage_1247 import load_staged_catalog_1247
    actual = _load(tmp_path, monkeypatch, load_staged_catalog_1247())
    assert [r["release_sequence"] for r in actual["releases"]] == [1245, 1247, 1248]
    assert actual["default_install_version"] == actual["latest_stable"] == "1.3.44"
    assert actual["releases"][2]["installable"] is False
    assert actual["releases"][2]["min_current_version"] == "1.3.45"
    tampered = deepcopy(actual)
    tampered["releases"][2]["update_allowed"] = False
    with pytest.raises(releases.ClientFlowCatalogError):
        _load(tmp_path, monkeypatch, tampered)


def test_exact_1246_update_only_pilot_catalog_is_accepted(tmp_path, monkeypatch):
    # Release-store retention remains three, but the active pilot catalog
    # intentionally selects only stable 1245 + approved update-only 1246.
    from service1.clientflow_release_pilot_stage_1246 import load_staged_catalog

    payload = load_staged_catalog()
    actual = _load(tmp_path, monkeypatch, payload)
    assert [r["release_sequence"] for r in actual["releases"]] == [1245, 1246]
    assert actual["latest_stable"] == actual["default_install_version"] == "1.3.44"
    assert actual["releases"][0]["installable"] is True
    assert actual["releases"][1]["installable"] is False
    assert actual["releases"][1]["update_allowed"] is True

    tampered = deepcopy(payload)
    tampered["releases"][1]["notes"][0] += " tampered"
    with pytest.raises(releases.ClientFlowCatalogError,
                       match="1246-katalogets godkendte autoritet"):
        _load(tmp_path, monkeypatch, tampered)


@pytest.mark.parametrize("mutate", [
    lambda d: d["retention_policy"].pop("max_selectable_versions"),
    lambda d: d["retention_policy"].update(max_selectable_versions=4),
    lambda d: d["retention_policy"].update(max_installable_versions=3),
    lambda d: d["releases"].insert(0, deepcopy(d["releases"][0])),
    lambda d: d["releases"].append(deepcopy(d["releases"][0])),
    lambda d: d["releases"][0].update(release_sequence=1243, release_id="clientflow-1.3.43-seq-1243"),
    lambda d: d.update(latest_stable="1.3.43"),
    lambda d: d.update(default_install_version="1.3.43"),
    lambda d: d["releases"][-1].update(installable=False),
    lambda d: d["releases"][-2].update(installable=True),
    lambda d: d["releases"][0].update(status="blocked"),
    lambda d: d["releases"][0].update(update_allowed=False),
])
def test_invalid_future_catalog_fails_closed(tmp_path, monkeypatch, mutate):
    payload = _future(1245, 1246, 1247)
    mutate(payload)
    with pytest.raises(releases.ClientFlowCatalogError):
        _load(tmp_path, monkeypatch, payload)


def test_frozen_catalog_is_exclusively_1244_after_reset():
    catalog = json.loads(CATALOG.read_text())
    assert catalog["catalog_sequence"] == 1244
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.43"
    assert [r["release_sequence"] for r in catalog["releases"]] == [1244]
    assert catalog["releases"][0]["installable"] is True
    assert catalog["releases"][0]["update_allowed"] is False
    assert catalog["releases"][0]["rollback_allowed"] is False


def test_1245_stable_rejects_two_active_catalog_targets(tmp_path, monkeypatch):
    # The pilot may temporarily have 1244 stable + 1245 supported, but
    # once 1245 is stable it must be the *only* selectable catalog entry.
    with pytest.raises(releases.ClientFlowCatalogError):
        _load(tmp_path, monkeypatch, _future(1244, 1245))
