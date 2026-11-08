"""Future 1244+ catalog must never silently reopen retired release versions."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from service1 import clientflow_releases as releases

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "backend/service1/clientflow_release_catalog.json"


def _future(*sequences: int) -> dict:
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
    (1244,), (1244, 1245), (1244, 1245, 1246), (1245, 1246, 1247),
])
def test_one_to_three_only_latest_stable(tmp_path, monkeypatch, sequences):
    payload = _future(*sequences)
    actual = _load(tmp_path, monkeypatch, payload)
    assert [r["release_sequence"] for r in actual["releases"]] == list(sequences)
    assert actual["default_install_version"] == payload["releases"][-1]["version"]


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


def test_current_catalog_remains_valid_and_1244_not_yet_selectable():
    catalog = json.loads(CATALOG.read_text())
    assert catalog["catalog_sequence"] == 1243
    assert all(r["release_sequence"] != 1244 for r in catalog["releases"])
