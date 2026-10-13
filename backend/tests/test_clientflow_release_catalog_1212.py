from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1.clientflow_releases import (
    ClientFlowCatalogError,
    load_catalog,
    resolve_fresh_install_release,
    resolve_release,
)


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend/service1/clientflow_release_catalog.json"


def test_catalog_1237_promotes_exact_1336_fresh_install_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert data["catalog_sequence"] == 1237
    assert data["latest_stable"] == "1.3.36"
    assert data["default_install_version"] == "1.3.36"
    assert data["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }

    assert len(data["releases"]) == 1
    release = data["releases"][0]
    assert release["version"] == "1.3.36"
    assert release["client_version"] == "1.3.36"
    assert release["release_sequence"] == 1237
    assert release["release_id"] == "clientflow-1.3.36-seq-1237"
    assert release["revision"] == "clientflow-1.3.36-seq-1237"
    assert release["status"] == "stable"
    assert release["installable"] is True
    assert release["update_allowed"] is False
    assert release["rollback_allowed"] is False
    assert release["requires_reboot"] is True
    assert release["install_modes"] == ["fresh_install"]
    assert "min_current_version" not in release
    assert "ikke fysisk verificeret" in release["block_reason"]
    assert release["ubuntu_compatibility"] == {
        "policy": "ubuntu-desktop-lts-minimum",
        "minimum_lts_version": "26.04",
        "maximum_certified_version": "26.04",
        "certified_versions": ["26.04"],
        "architecture": "amd64",
        "desktop": "gnome",
        "display_stack": "wayland",
        "requires_platform_preflight": True,
    }


def test_catalog_1237_promoted_after_exact_approval_and_publication() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = data["releases"][0]

    source_version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads(
        (ROOT / "client/release/release-input.json").read_text(encoding="utf-8")
    )

    # Only exactly approved and published 1.3.36/1237 is selectable.
    # The old 1.3.35/1236 selector is removed; history is preserved as evidence.
    assert source_version == "1.3.37"
    assert release_input["release_sequence"] == 1238
    assert release_input["runtime_python"] == "3.13.14"
    assert data["catalog_sequence"] + 1 == release_input["release_sequence"]
    assert data["latest_stable"] == "1.3.36"
    assert data["default_install_version"] == "1.3.36"
    assert release["release_id"] == "clientflow-1.3.36-seq-1237"
    assert all(item["release_sequence"] != 1234 for item in data["releases"])
    assert all(item["release_sequence"] != 1228 for item in data["releases"])
    assert all(item["version"] != "1.3.27" for item in data["releases"])

    # SHA-256 and approval provenance belong to the immutable published bundle,
    # never to the catalog selector (which holds policy only).
    for field in (
        "bundle_sha256",
        "bundle_size",
        "approval_reference",
        "release_approval_reference",
        "candidate_sha256",
        "source_commit",
    ):
        assert field not in release


def test_catalog_1237_fresh_install_resolves_but_update_and_old_version_fail_closed() -> None:
    load_catalog.cache_clear()
    fresh = resolve_fresh_install_release()

    assert fresh["version"] == "1.3.36"
    assert fresh["release_id"] == "clientflow-1.3.36-seq-1237"
    assert fresh["release_sequence"] == 1237
    assert fresh["status"] == "stable"
    assert fresh["installable"] is True
    assert fresh["update_allowed"] is False
    assert fresh["install_modes"] == ["fresh_install"]

    with pytest.raises(ClientFlowCatalogError, match="kun frigivet til fresh install"):
        resolve_release("1.3.36")
    for legacy in ("1.3.35", "1.3.34", "1.3.33"):
        with pytest.raises(ClientFlowCatalogError, match="findes ikke"):
            resolve_release(legacy)


def test_1237_catalog_promotion_documents_exact_immutable_artifact_and_pending_physical_gate() -> None:
    record = (ROOT / "CLIENTFLOW_1.3.36_1237_FRESH_INSTALL_CATALOG_PROMOTION.md").read_text(
        encoding="utf-8"
    )
    assert "fb5daee53457e2f2145f42404f3595fd1df02627" in record
    assert "3d44274f79d0df899963edef4c93ada153f31d77d62692dbf3bb6a1c9799c856" in record
    assert "223498240 bytes" in record
    assert "RELEASE_STORE_POSTFLIGHT=PASS" in record
    assert "fresh-install-only" in record
    assert "physical acceptance is PENDING" in record
    assert "No automatic 1.3.35" in record
    # Previous published evidence is historical and must not be rewritten.
    previous = ROOT / "CLIENTFLOW_1.3.35_1236_FRESH_INSTALL_CATALOG_PROMOTION.md"
    assert previous.is_file()
    assert "94abdce02578a09d067397e7a2d9a9d86a0c20e696eb734a79ade8a483c713d4" in previous.read_text(encoding="utf-8")
    history = ROOT / "CLIENTFLOW_1.3.34_1235_FRESH_INSTALL_CATALOG_PROMOTION.md"
    assert history.is_file()
    assert "51e93dad8b1cffd43e03845ae0a7e2472d955a65" in history.read_text(encoding="utf-8")


def test_catalog_rejects_update_allowed_without_in_place_update_mode(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["releases"][0]["update_allowed"] = True
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="update_allowed uden in_place_update"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


@pytest.mark.parametrize("requested", [None, "", "   ", "latest", "LATEST", "stable", "StAbLe"])
def test_release_resolver_rejects_implicit_latest_aliases(requested: str | None) -> None:
    load_catalog.cache_clear()
    with pytest.raises(ClientFlowCatalogError, match="konkret katalogversion"):
        resolve_release(requested)


def test_catalog_requires_explicit_default_fresh_install_version(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data.pop("default_install_version", None)
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="mangler default_install_version"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


def test_catalog_rejects_default_fresh_install_version_that_is_not_in_catalog(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["default_install_version"] = "9.9.9"
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="findes ikke i releasekataloget"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


def test_catalog_rejects_default_that_is_not_fresh_installable(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["releases"][0]["installable"] = False
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="installérbar fresh-install release"):
            load_catalog()
    finally:
        load_catalog.cache_clear()
