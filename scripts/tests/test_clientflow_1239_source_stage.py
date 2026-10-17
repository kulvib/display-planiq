"""1.3.38/1239 source staging is not immutable release approval."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_1239_source_identity_matches_published_catalog_after_approval():
    version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    source = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text(encoding="utf-8"))

    assert version == "1.3.39"
    assert source == {
        "schema_version": 1,
        "release_sequence": 1240,
        "minimum_ubuntu_lts": "26.04",
        "architecture": "amd64",
        "runtime_python": "3.13.14",
    }
    assert catalog["catalog_sequence"] == 1240
    assert source["release_sequence"] == catalog["catalog_sequence"]
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert len(catalog["releases"]) == 2
    selected = catalog["releases"][0]
    assert selected["release_id"] == "clientflow-1.3.38-seq-1239"
    assert selected["release_sequence"] == 1239
    assert selected["installable"] is True
    assert selected["install_modes"] == ["fresh_install"]
    assert selected["update_allowed"] is False
    assert selected["rollback_allowed"] is False
    pilot = catalog["releases"][1]
    assert pilot["release_id"] == "clientflow-1.3.39-seq-1240"
    assert pilot["release_sequence"] == 1240
    assert pilot["status"] == "supported"
    assert pilot["installable"] is False
    assert pilot["update_allowed"] is True
    assert pilot["rollback_allowed"] is False
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["min_current_version"] == pilot["max_current_version"] == "1.3.38"
    assert all(row["release_sequence"] != 1238 for row in catalog["releases"])


def test_1239_source_stage_disclaims_publication_and_unauthorized_upgrades():
    stage = (ROOT / "CLIENTFLOW_1.3.38_1239_SOURCE_STAGE.md").read_text(encoding="utf-8")
    for token in (
        "STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published",
        "NOT catalog-promoted", "No in-place update", "physical",
        "exact-source CI", "source SHA", "approval",
    ):
        assert token in stage
    # Previous approved release and its actual hash must remain historically recorded.
    approval = (ROOT / "CLIENTFLOW_1.3.37_1238_FRESH_INSTALL_CATALOG_PROMOTION.md").read_text(encoding="utf-8")
    assert "911d59c45159fe41b85c96366c1d0bd84762cb81a042519d2b177da86339adfe" in approval
