"""1244-only fresh install catalog, historical retirement, and read-only post-deploy gate."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from service1 import clientflow_releases as releases
from scripts import clientflow_1244_transition_policy as pinned
from scripts import preflight_clientflow_1244_catalog_promotion as preflight

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "backend/service1/clientflow_release_catalog.json"
HISTORY = ROOT / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json"


def actual() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_current_production_catalog_has_exact_one_fresh_only_1244():
    cat = actual()
    assert cat["catalog_sequence"] == 1244
    assert cat["latest_stable"] == cat["default_install_version"] == "1.3.43"
    assert cat["retention_policy"] == {
        "max_selectable_versions": 3,
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }
    assert len(cat["releases"]) == 1
    selected = cat["releases"][0]
    assert selected["release_id"] == pinned.RELEASE_ID
    assert selected["revision"] == pinned.RELEASE_ID
    assert selected["version"] == selected["client_version"] == "1.3.43"
    assert selected["release_sequence"] == 1244
    assert selected["artifact_type"] == "runtime_release"
    assert selected["status"] == "stable"
    assert selected["install_modes"] == ["fresh_install"]
    assert selected["installable"] is True
    assert selected["update_allowed"] is False
    assert selected["rollback_allowed"] is False
    assert selected["requires_explicit_downgrade"] is False
    assert selected["requires_reboot"] is True
    assert "min_current_version" not in selected
    assert "max_current_version" not in selected
    assert selected["ubuntu_compatibility"]["minimum_lts_version"] == "26.04"
    assert selected["ubuntu_compatibility"]["architecture"] == "amd64"
    note = " ".join(selected["notes"])
    for proof in (
        pinned.APPROVED_SHA256, pinned.APPROVAL_REFERENCE,
        pinned.SOURCE_COMMIT, str(pinned.APPROVED_SIZE),
        "2243141d87cc43cfce6b8a8f839827d76996968e04808332d6c5e4614a351bfe",
        "897eec852e45fea4423edd379df361132d79222a278c8d37adf554f8a96da7ce",
    ):
        assert proof in note
    # No release authorization is inferred from human-facing notes.
    for field in ("bundle_sha256", "bundle_size", "source_commit", "approval_reference"):
        assert field not in selected


def test_original_1243_catalog_is_immutable_historical_test_evidence():
    frozen = HISTORY.read_bytes()
    assert hashlib.sha256(frozen).hexdigest() == (
        "fc512eb735b4fc3cc3eda32e3151ea03f598efda128b54b97e81fe8836513668"
    )
    historic = json.loads(frozen)
    assert historic["catalog_sequence"] == 1243
    assert historic["latest_stable"] == historic["default_install_version"] == "1.3.38"
    assert [x["release_sequence"] for x in historic["releases"]] == [1239, 1241, 1242, 1243]
    assert len(actual()["releases"]) == 1  # The frozen fixture is never the production catalog.


def test_runtime_fresh_only_policy_and_retired_versions_are_not_selectable():
    releases.load_catalog.cache_clear()
    assert releases.load_catalog()["catalog_sequence"] == 1244
    assert releases.resolve_fresh_install_release()["release_id"] == pinned.RELEASE_ID
    assert [r["release_id"] for r in releases.public_catalog()["releases"]] == [pinned.RELEASE_ID]
    for version in ("1.3.38", "1.3.39", "1.3.40", "1.3.41", "1.3.42"):
        with pytest.raises(releases.ClientFlowCatalogError, match="findes ikke"):
            releases.resolve_release(version)
    with pytest.raises(releases.ClientFlowCatalogError, match="kan ikke installeres"):
        releases.resolve_release("1.3.43")
    for value in (None, "", "stable", "latest"):
        with pytest.raises(releases.ClientFlowCatalogError, match="konkret katalogversion"):
            releases.resolve_release(value)


@pytest.mark.parametrize("mutation", [
    lambda c: c["retention_policy"].update(max_selectable_versions=4),
    lambda c: c["retention_policy"].update(max_installable_versions=2),
    lambda c: c["retention_policy"].update(keep_blocked_metadata=True),
    lambda c: c["releases"][0].update(release_sequence=1243),
    lambda c: c["releases"][0].update(installable=False),
    lambda c: c["releases"][0].update(update_allowed=True),
    lambda c: c["releases"][0].update(rollback_allowed=True),
    lambda c: c["releases"][0].update(status="blocked"),
    lambda c: c["releases"][0].update(install_modes=["in_place_update"]),
    lambda c: c["releases"].append(deepcopy(c["releases"][0])),
    lambda c: c.update(default_install_version="1.3.38"),
])
def test_tampered_1244_catalog_fails_closed(tmp_path, monkeypatch, mutation):
    payload = actual()
    mutation(payload)
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(releases, "CATALOG_PATH", target)
    releases.load_catalog.cache_clear()
    try:
        with pytest.raises(releases.ClientFlowCatalogError):
            releases.load_catalog()
    finally:
        releases.load_catalog.cache_clear()


def test_postdeploy_gate_requires_pause_and_verifies_pinned_six(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    for flag in ("CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
                 "CLIENTFLOW_1243_PILOT_CLIENT_ID"):
        monkeypatch.delenv(flag, raising=False)
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    paths = []
    for release_id in pinned.EXPECTED_AFTER:
        path = root / f"{release_id}.tar"
        path.write_bytes(release_id.encode())
        paths.append(path)

    def fake_verified(path, *, require_deployable=True):
        assert require_deployable and path in paths
        size, digest = pinned.EXPECTED_AFTER[path.stem]
        version, sequence = path.stem.removeprefix("clientflow-").split("-seq-")
        return ({"release_id": path.stem, "version": version, "release_sequence": int(sequence),
                 "release_approval": {"reference": pinned.APPROVAL_REFERENCE},
                 "source": {"commit": pinned.SOURCE_COMMIT}}, None, size, digest, path.open("rb"))

    from scripts import audit_clientflow_release_retention as audit
    monkeypatch.setattr(audit, "open_verified_bundle_structure", fake_verified)
    before = {p.name: p.read_bytes() for p in paths}
    report = preflight.inspect_catalog_and_store(root)
    assert report["catalog_sequence"] == 1244
    assert report["verified_store_count"] == 6
    assert report["automatic_deletion_enabled"] is False
    assert report["rollback_enabled"] is False
    assert before == {p.name: p.read_bytes() for p in paths}
    assert preflight.main(["--artifact-dir", str(root)]) == 0
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED")
    assert preflight.main(["--artifact-dir", str(root)]) == 1
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    paths[0].unlink()
    assert preflight.main(["--artifact-dir", str(root)]) == 1


def test_promotion_postflight_script_cannot_publish_or_prune():
    source = (ROOT / "scripts/preflight_clientflow_1244_catalog_promotion.py").read_text()
    assert "inspect_store(artifact_dir)" in source
    assert "require_exact_store(snapshot, after=True)" in source
    assert "require_quiesced()" in source
    assert "prune_one_oldest(" not in source
    assert "publish_clientflow_release" not in source
