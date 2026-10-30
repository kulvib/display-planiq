"""Exact 1.3.38/1239 promotion is an immutable, fresh-install-only selector."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "clientflow-1.3.38-seq-1239"
SOURCE = "abbd8d673a350b6beca5d9e58ddb02fa2edd1c08"
CANDIDATE_SHA = "d4d091c2865437582ce5ad7c0edb437ca37626bd75fd02b17f64442e8b0e5f86"
INSTALLER_SHA = "2ee4ad5fb87d3ba420742c74e2956f816258e9991b95865dd67c3400c6642f75"
APPROVED_SHA = "02c3d4261eabdac4b9967a3aad4419453f61ca483ef4eb34dacf284d3af16a11"
REFERENCE = "clientflow-1.3.38-seq-1239/abbd8d673a350b6beca5d9e58ddb02fa2edd1c08/d4d091c2865437582ce5ad7c0edb437ca37626bd75fd02b17f64442e8b0e5f86"


def test_exact_promotion_preserves_no_update_no_rollback_and_historical_evidence() -> None:
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text(encoding="utf-8"))
    source = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    assert (ROOT / "client/VERSION").read_text(encoding="utf-8").strip() == "1.3.41"
    assert source["release_sequence"] == 1242
    assert catalog["catalog_sequence"] == 1241
    assert source["release_sequence"] == catalog["catalog_sequence"] + 1
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert catalog["retention_policy"] == {"max_installable_versions": 1, "keep_blocked_metadata": False}
    assert len(catalog["releases"]) == 2
    release = catalog["releases"][0]
    assert release["release_id"] == release["revision"] == RELEASE
    assert release["version"] == release["client_version"] == "1.3.38"
    assert release["release_sequence"] == 1239
    assert release["status"] == "stable" and release["installable"] is True
    assert release["install_modes"] == ["fresh_install"]
    assert release["update_allowed"] is False and release["rollback_allowed"] is False
    assert release["requires_reboot"] is True
    assert "min_current_version" not in release
    assert all(key not in release for key in ("bundle_sha256", "bundle_size", "approval_reference", "source_commit"))
    assert release["ubuntu_compatibility"]["display_stack"] == "wayland"
    pilot = catalog["releases"][1]
    assert pilot["release_id"] == "clientflow-1.3.40-seq-1241"
    assert pilot["release_sequence"] == 1241
    assert pilot["status"] == "supported"
    assert pilot["installable"] is False
    assert pilot["update_allowed"] is True
    assert pilot["rollback_allowed"] is False
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["min_current_version"] == pilot["max_current_version"] == "1.3.38"
    assert (ROOT / "CLIENTFLOW_1.3.37_1238_FRESH_INSTALL_CATALOG_PROMOTION.md").is_file()


def test_exact_approval_and_render_publication_are_documented_not_inferred() -> None:
    text = (ROOT / "CLIENTFLOW_1.3.38_1239_FRESH_INSTALL_CATALOG_PROMOTION.md").read_text(encoding="utf-8")
    for token in (SOURCE, CANDIDATE_SHA, INSTALLER_SHA, APPROVED_SHA, REFERENCE,
                  "223498240", "RELEASE_STORE_POSTFLIGHT=PASS", "IMMUTABLE_STORE=PASS",
                  "fresh-install-only", "Physical acceptance", "pending", "No in-place update"):
        assert token in text
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text(encoding="utf-8"))
    notes = " ".join(catalog["releases"][0]["notes"])
    for token in (SOURCE, APPROVED_SHA, REFERENCE, "223498240", "Physical acceptance pending"):
        assert token in notes
