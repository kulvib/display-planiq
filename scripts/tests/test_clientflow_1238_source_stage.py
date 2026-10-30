"""1.3.37 source stage cannot gain release authority before separate approval."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_source_identity_promoted_only_after_exact_release_approval():
    version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    source = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text(encoding="utf-8"))
    assert version == "1.3.41"
    assert source == {
        "schema_version": 1, "release_sequence": 1242,
        "minimum_ubuntu_lts": "26.04", "architecture": "amd64",
        "runtime_python": "3.13.14",
    }
    assert catalog["catalog_sequence"] == 1242
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert len(catalog["releases"]) == 3
    approved = catalog["releases"][0]
    assert approved["release_id"] == "clientflow-1.3.38-seq-1239"
    assert approved["install_modes"] == ["fresh_install"]
    assert approved["installable"] is True
    assert approved["update_allowed"] is False
    assert approved["rollback_allowed"] is False
    assert source["release_sequence"] == catalog["catalog_sequence"]
    pilot = catalog["releases"][1]
    assert pilot["release_id"] == "clientflow-1.3.40-seq-1241"
    assert pilot["release_sequence"] == 1241
    assert pilot["status"] == "supported"
    assert pilot["installable"] is False
    assert pilot["update_allowed"] is True
    assert pilot["rollback_allowed"] is False
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["min_current_version"] == pilot["max_current_version"] == "1.3.38"
    assert all(row["release_id"] != "clientflow-1.3.36-seq-1237" for row in catalog["releases"])

def test_historical_source_stage_made_no_premature_approval_claims():
    text = (ROOT / "CLIENTFLOW_1.3.37_1238_SOURCE_STAGE.md").read_text(encoding="utf-8")
    for token in ("STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published", "NOT catalog-promoted", "in-place update", "GitHub CI", "physical"): 
        assert token in text
