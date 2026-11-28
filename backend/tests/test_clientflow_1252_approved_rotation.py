"""Exact source approval and resumable 1252 rotation; no live storage writes."""
from copy import deepcopy
import json

import pytest

from service1 import clientflow_pilot_1252 as pilot
from service1.clientflow_1252_transition import (
    CANDIDATE_ID, OLDEST_ID, PREDECESSOR_ID, Candidate1252Denied,
)
from service1.clientflow_pilot_1251 import BASELINE_ID, RETAINED_IDS, Pilot1251Denied
from service1.clientflow_closed_standard_1251 import closed_standard_catalog
from service1.clientflow_releases import load_catalog


def snapshot(ids):
    pins = pilot.rotation_inventory()
    rows = [dict(release_id=rid, size_bytes=pins[rid]["size"], sha256=pins[rid]["sha256"])
            for rid in sorted(ids)]
    return dict(protected_latest=rows, older_review_only=[], invalid_artifacts=[], approved_count=len(rows))


def test_exact_approved_source_and_candidate_are_separate_from_active_catalog():
    row = pilot.approval_lock_1252()
    assert row["release_build_run_id"] == 46139248741
    assert row["approval_run_id"] == 46139639652
    assert row["archive_run_id"] == 46139886409
    assert row["github_asset_id"] == 804314409
    assert row["source_commit"] == "d2f3516e8322720f8bf3aad8325db3a2bfd03a70"
    assert row["approved_bundle_sha256"] == "8ddabdb5429f116b93a4b3ee7433c09572bcc8d8cbeda18160ececb5dde130a1"
    assert load_catalog() == closed_standard_catalog()
    assert load_catalog()["catalog_sequence"] == 1251
    release = pilot.candidate_release()
    assert release["release_id"] == CANDIDATE_ID
    assert release["min_current_version"] == release["max_current_version"] == "1.4.1"
    assert release["installable"] is False and release["rollback_allowed"] is False
    assert release["install_modes"] == ["in_place_update"]
    pilot.match_candidate_artifact(pilot.candidate_snapshot())


def test_approval_lock_rejects_even_equivalent_rewritten_json(tmp_path, monkeypatch):
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(pilot.approval_lock_1252()))
    monkeypatch.setattr(pilot, "APPROVAL_PATH", path)
    with pytest.raises(Pilot1251Denied):
        pilot.approval_lock_1252()


@pytest.mark.parametrize("field", [
    "target_release_id", "target_version", "target_release_sequence", "bundle_sha256",
    "bundle_size", "release_approval_reference", "release_candidate_sha256", "source_commit",
])
def test_candidate_snapshot_rejects_any_mixed_identity_or_artifact(field):
    artifact = pilot.candidate_snapshot()
    artifact[field] = None
    with pytest.raises(Candidate1252Denied):
        pilot.match_candidate_artifact(artifact)


def test_manifest_pin_includes_installer_and_clean_source():
    row = pilot.approval_lock_1252()
    manifest = dict(release_id=CANDIDATE_ID, version="1.4.2", release_sequence=1252,
                    deployable=True, source={"commit": row["source_commit"], "dirty": False},
                    fresh_installer={"sha256": row["installer_sha256"]},
                    release_approval={"reference": row["approval_reference"],
                                      "candidate_sha256": row["candidate_sha256"]})
    def check(value):
        pilot.match_candidate_manifest(value, size=row["approved_bundle_size"],
                                       digest=row["approved_bundle_sha256"])
    check(manifest)
    for key, bad in [
        ("source", {"commit": row["source_commit"], "dirty": True}),
        ("deployable", False), ("fresh_installer", {"sha256": "0"*64}),
        ("release_approval", {"reference": row["approval_reference"], "candidate_sha256": "0"*64}),
    ]:
        with pytest.raises(Candidate1252Denied):
            check({**manifest, key: bad})


def test_only_exact_three_two_three_states_are_resumable():
    assert pilot.rotation_state(snapshot(RETAINED_IDS)) == "original"
    assert pilot.rotation_state(snapshot({BASELINE_ID, PREDECESSOR_ID})) == "pruned"
    assert pilot.rotation_state(snapshot(pilot.FINAL_IDS)) == "published"
    assert pilot.FINAL_IDS == {BASELINE_ID, PREDECESSOR_ID, CANDIDATE_ID}
    for ids in (RETAINED_IDS | {CANDIDATE_ID}, {PREDECESSOR_ID},
                {OLDEST_ID, PREDECESSOR_ID, CANDIDATE_ID}, {BASELINE_ID, CANDIDATE_ID}):
        with pytest.raises(Candidate1252Denied):
            pilot.rotation_state(snapshot(ids))


@pytest.mark.parametrize("attack", ["hash", "size", "duplicate", "count", "older", "invalid"])
def test_rotation_rejects_unsafe_inventory(attack):
    data = deepcopy(snapshot(RETAINED_IDS))
    rows = data["protected_latest"]
    if attack == "hash":
        rows[0]["sha256"] = "0"*64
    elif attack == "size":
        rows[0]["size_bytes"] += 1
    elif attack == "duplicate":
        rows[1] = rows[0]
    elif attack == "count":
        data["approved_count"] = True
    elif attack == "older":
        data["older_review_only"] = [rows[0]]
    else:
        data["invalid_artifacts"] = ["unknown"]
    with pytest.raises(Candidate1252Denied):
        pilot.rotation_state(data)


def test_rotation_entrypoint_is_not_an_authorization_or_catalog_rebind():
    from scripts import reconcile_clientflow_1252_store as rotation
    source = rotation.Path(rotation.__file__).read_text()
    assert "create_authorized_deployment" not in source
    assert "control.revision =" not in source.replace("control.revision ==", "")
    assert "verify_staged_candidate(bundle)" in source
    assert source.index("verify_staged_candidate(bundle)") < source.index("result = prune_one_oldest")
    assert "--confirm-viborg1-local-preflight" in source
    assert "DEPLOYMENT_AUTHORIZED=NO" in source
