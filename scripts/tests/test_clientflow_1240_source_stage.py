"""The 1240 source-stage cannot silently authorize update, downgrade or rollout."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_1240_history_survives_1241_successor_without_reauthorizing_1240():
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
    assert catalog["catalog_sequence"] == 1241
    assert source["release_sequence"] == catalog["catalog_sequence"] + 1
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert catalog["retention_policy"] == {"max_installable_versions": 1, "keep_blocked_metadata": False}
    assert len(catalog["releases"]) == 2
    old, pilot = catalog["releases"]
    assert old["release_id"] == "clientflow-1.3.38-seq-1239"
    assert old["install_modes"] == ["fresh_install"]
    assert old["update_allowed"] is False and old["rollback_allowed"] is False
    assert old["installable"] is True
    assert pilot["release_id"] == "clientflow-1.3.40-seq-1241"
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["installable"] is False
    assert pilot["status"] == "supported"
    assert pilot["update_allowed"] is True and pilot["rollback_allowed"] is False
    assert pilot["min_current_version"] == pilot["max_current_version"] == "1.3.38"


def test_new_pilot_selector_does_not_authorize_downgrade_or_fleet_update(monkeypatch):
    from service1.clientflow_releases import (
        ClientFlowCatalogError, load_catalog, resolve_release, resolve_fresh_install_release,
    )
    from service1.clientflow_pilot_1240 import ClientFlowPilotDenied, require_pilot_1240

    load_catalog.cache_clear()
    assert resolve_fresh_install_release()["release_id"] == "clientflow-1.3.38-seq-1239"
    with pytest.raises(ClientFlowCatalogError, match="findes ikke"):
        resolve_release("1.3.39")
    release = resolve_release("1.3.40")
    monkeypatch.setenv("CLIENTFLOW_1240_PILOT_CLIENT_ID", "1")
    with pytest.raises(ClientFlowPilotDenied, match="permanent lukket"):
        require_pilot_1240(client_id=1, current_version="1.3.38", release=release,
            reason="physical test", pre_first_activation_repair=False, confirm_downgrade=False)
    with pytest.raises(ClientFlowCatalogError, match="kun frigivet til fresh install"):
        resolve_release("1.3.38")
    for implicit in ("", "latest", "stable"):
        with pytest.raises(ClientFlowCatalogError, match="konkret katalogversion"):
            resolve_release(implicit)


def test_stage_documents_all_release_and_physical_upgrade_gates():
    stage = (ROOT / "CLIENTFLOW_1.3.39_1240_SOURCE_STAGE.md").read_text(encoding="utf-8")
    for required in (
        "STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published", "NOT catalog-promoted",
        "1.3.38", "1.3.39", "1240", "source SHA", "exact-source CI",
        "in_place_update", "min_current_version=1.3.38", "rollback_release()",
        "Control Room", "Chrome/Wayland", "SHA", "Heidi1", "no Linux reinstall",
        "PostgreSQL", "backup", "immutable", "reproducible", "health",
        "cookie", "clipboard", "Remote Desktop", "Terminal", "Livestream",
    ):
        assert required in stage, required


def test_local_and_remote_rollback_authorities_are_not_confused():
    local = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    remote = (ROOT / "backend/service1/routers/clientflow_deployments.py").read_text(encoding="utf-8")
    resolver = (ROOT / "backend/service1/clientflow_releases.py").read_text(encoding="utf-8")
    assert "def rollback_release(" in local
    assert 'if target not in (state.get("installed") or {}):' in local
    assert "_canonical_activation_approval(" in local
    assert "rollback_health_verified" in local
    assert "automatic_rollback_completed" in local
    assert "automatic_rollback_failed" in local
    assert 'if release.get("rollback_allowed") is not True:' in remote
    assert "confirm_downgrade" in remote
    assert "requires_downgrade" in remote
    assert "deployment_release_snapshot(release)" in remote
    assert 'if status not in SELECTABLE_STATUSES or release.get("update_allowed") is not True:' in resolver


def test_prospective_139_catalog_allows_only_explicitly_scoped_update_source(monkeypatch, tmp_path):
    """Model later promotion without changing production's fresh-only selector."""
    from service1 import clientflow_releases as releases

    catalog = _json("backend/service1/clientflow_release_catalog.json")
    original = dict(catalog["releases"][0])
    target = dict(original)
    target.update({
        "version": "1.3.39",
        "client_version": "1.3.39",
        "release_sequence": 1240,
        "revision": "clientflow-1.3.39-seq-1240",
        "release_id": "clientflow-1.3.39-seq-1240",
        "install_modes": ["fresh_install", "in_place_update"],
        "update_allowed": True,
        "rollback_allowed": False,
        "min_current_version": "1.3.38",
        "max_current_version": "1.3.38",
        "block_reason": None,
    })
    catalog.update({
        "catalog_sequence": 1240,
        "latest_stable": "1.3.39",
        "default_install_version": "1.3.39",
        "retention_policy": {"max_installable_versions": 2, "keep_blocked_metadata": True},
        "releases": [dict(original, status="supported"), target],
    })
    future_path = tmp_path / "future-policy-not-for-production.json"
    future_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(releases, "CATALOG_PATH", future_path)
    releases.load_catalog.cache_clear()
    try:
        future = releases.load_catalog()
        assert len(future["releases"]) == 2
        selected = releases.resolve_release("1.3.39")
        assert selected["release_id"] == "clientflow-1.3.39-seq-1240"
        releases.validate_release_compatibility(
            selected, current_version="1.3.38", ubuntu_version="26.04.1"
        )
        for source in ("1.3.37", "1.3.39"):
            with pytest.raises(releases.ClientFlowCatalogError):
                releases.validate_release_compatibility(
                    selected, current_version=source, ubuntu_version="26.04"
                )
        with pytest.raises(releases.ClientFlowCatalogError):
            releases.validate_release_compatibility(
                selected, current_version="1.3.38", ubuntu_version="25.10"
            )
        # An approved old fresh-only selector cannot suddenly serve as a remote downgrade.
        with pytest.raises(releases.ClientFlowCatalogError, match="kun frigivet til fresh install"):
            releases.resolve_release("1.3.38")
    finally:
        releases.load_catalog.cache_clear()
