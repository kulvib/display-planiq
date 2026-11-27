"""68K-E3: pinned staged authority; no live catalog, storage or client mutation."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from service1 import clientflow_pilot_1251 as policy
from service1 import clientflow_pilot_1250 as baseline
from service1 import clientflow_releases as releases
from service1 import native_rdp_admission as admission


def closed_control():
    return dict(stable_release_id=baseline.BASELINE_ID,
        stable_bundle_sha256=baseline.approval_lock_1250()["approved_bundle_sha256"],
        revision=2, cutover_enabled=False, fleet_open=False, fresh_install_open=False)


def set_closed_flags(monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    monkeypatch.setenv("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false")
    for flag in policy.CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)


def baseline_artifact():
    data = baseline.approval_lock_1250()
    return dict(target_release_id=baseline.BASELINE_ID, target_version="1.4.0",
        target_release_sequence=1250, bundle_sha256=data["approved_bundle_sha256"],
        bundle_size=data["approved_bundle_size"], release_approval_reference=data["approval_reference"],
        release_candidate_sha256=data["candidate_sha256"], source_commit=data["source_commit"])


def deployment(artifact, **changes):
    values = dict(artifact, id="fixture", client_id=3, state="succeeded", completed_at=object(),
        allow_downgrade=False, observed_release_id=artifact["target_release_id"],
        observed_release_sequence=artifact["target_release_sequence"],
        observed_previous_release_id=baseline.BASELINE_ID)
    values.update(changes)
    return SimpleNamespace(**values)


def test_promoted_catalog_is_exact_but_does_not_authorize_historical_control(monkeypatch):
    set_closed_flags(monkeypatch)
    catalog = policy.closed_baseline_catalog()
    policy.require_closed_baseline(catalog, closed_control(), 2)
    # The historical pilot must not regain authority after the standard promotion.
    from service1.clientflow_closed_standard_1251 import closed_standard_catalog
    assert releases.load_catalog() == closed_standard_catalog()
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_closed_baseline(releases.load_catalog(), closed_control(), 2)
    from service1.clientflow_release_pilot_stage_1248 import load_staged_catalog_1248
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_closed_baseline(load_staged_catalog_1248(), closed_control(), 2)
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_closed_baseline(catalog, {**closed_control(), "stable_release_id": "clientflow-1.3.44-seq-1245"}, 2)
    for field, value in [("fleet_open", True), ("fresh_install_open", True), ("cutover_enabled", True),
                         ("stable_release_id", "clientflow-1.3.44-seq-1245"),
                         ("stable_bundle_sha256", "0"*64), ("revision", 3)]:
        with pytest.raises(policy.Pilot1251Denied):
            policy.require_closed_baseline(catalog, {**closed_control(), field: value}, 2)
    changed = deepcopy(catalog)
    changed["releases"][0]["notes"] = []
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_closed_baseline(changed, closed_control(), 2)
    monkeypatch.setenv("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "true")
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_closed_baseline(catalog, closed_control(), 2)


def test_exact_1251_pin_and_no_other_client():
    approval = policy.approval_lock_1251()
    assert approval["approval_run_id"] == 46039991574
    assert approval["source_commit"] == "16bfb850aea148894b6d1cb28a09c7e6e188323c"
    assert approval["approved_bundle_sha256"] == "835610b0a59510b2119601468ad47c0aa1fb418b96c4cfaaa8cdd81042dc1ab6"
    assert approval["approved_bundle_size"] == 223897600
    artifact = policy.successor_snapshot()
    policy.match_successor_artifact(artifact)
    for key in artifact:
        with pytest.raises(policy.Pilot1251Denied):
            policy.match_successor_artifact({**artifact, key: None})
    assert policy.match_successor_order(deployment(artifact), client_id=3)
    assert not policy.match_successor_order(deployment(artifact, client_id=4), client_id=4)
    assert not policy.match_successor_order(deployment(artifact, allow_downgrade=True), client_id=3)
    assert policy.successor_release()["install_modes"] == ["in_place_update"]
    assert policy.successor_release()["min_current_version"] == "1.4.0"
    assert policy.successor_release()["max_current_version"] == "1.4.0"
    assert policy.successor_release()["rollback_allowed"] is False


def test_exact_retention_plan_never_publishes_a_fourth():
    rows = [dict(release_id=key, size_bytes=value["size"], sha256=value["sha256"])
            for key, value in policy.archive_inventory().items() if key != policy.SUCCESSOR_ID]
    state = dict(protected_latest=rows[-3:], older_review_only=rows[:-3],
                 approved_count=5, invalid_artifacts=[])
    plan = policy.plan_archive_rotation(state)
    assert plan["projected_counts"] == [5, 4, 3, 2, 3]
    assert plan["remove_oldest_first"] == ["clientflow-1.3.44-seq-1245",
        "clientflow-1.3.45-seq-1246", "clientflow-1.3.46-seq-1247"]
    assert set(plan["retain_after_publication"]) == policy.RETAINED_IDS
    assert plan["destructive_action_authorized"] is False
    assert plan["deployment_authorized"] is False
    for changes in ({"approved_count": 4}, {"invalid_artifacts": ["bad"]},
                    {"older_review_only": [rows[0], rows[0]]}):
        with pytest.raises(policy.Pilot1251Denied):
            policy.plan_archive_rotation({**state, **changes})


def test_retention_rejects_missing_or_extra_files_before_hashing(monkeypatch, tmp_path):
    from service1 import clientflow_release_artifacts as artifacts
    monkeypatch.setattr(artifacts, "_artifact_root", lambda: tmp_path)
    for identifier in policy.RETAINED_IDS - {policy.SUCCESSOR_ID}:
        (tmp_path / (identifier + ".tar")).write_bytes(b"fixture")
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_retained_store()
    (tmp_path / (policy.SUCCESSOR_ID + ".tar")).write_bytes(b"fixture")
    (tmp_path / "clientflow-1.3.44-seq-1245.tar").write_bytes(b"fixture")
    with pytest.raises(policy.Pilot1251Denied):
        policy.require_retained_store()


def test_closed_native_rdp_only_exact_successor_and_recovery(monkeypatch):
    set_closed_flags(monkeypatch)
    catalog = policy.closed_baseline_catalog()
    control_data = closed_control()
    control = SimpleNamespace(revision=2, model_dump=lambda: control_data)
    client = SimpleNamespace(id=3, name="Viborg1", ubuntu_version="26.04")
    prior = deployment(baseline_artifact())
    successor = deployment(policy.successor_snapshot())
    monkeypatch.setattr(admission, "canonical_baseline_artifact", lambda **_: baseline_artifact())
    monkeypatch.setattr(admission, "canonical_successor_artifact", policy.successor_snapshot)

    class Results:
        def __init__(self):
            self.rows = [[prior], [SimpleNamespace(credential_id="fixture", payload={
                "failed_release_id": policy.SUCCESSOR_ID, "restored_release_id": baseline.BASELINE_ID})]]
        def exec(self, _query):
            rows = self.rows.pop(0)
            return SimpleNamespace(all=lambda: rows)

    def check(version, row, device=client):
        return admission._closed_baseline_eligibility(Results(), client=device,
            catalog=catalog, control=control, latest=row, version=version)

    assert check("1.4.0", prior) == "physical_test_eligible"
    assert check("1.4.1", successor) == "physical_test_eligible"
    assert check("1.4.1", deployment(policy.successor_snapshot(), observed_previous_release_id=None)) == "update_evidence_mismatch"
    assert check("1.4.1", deployment(policy.successor_snapshot(), bundle_sha256="0"*64)) == "update_evidence_mismatch"
    assert check("1.4.1", successor, SimpleNamespace(id=4, name="Other", ubuntu_version="26.04")) == "cutover_closed"
    assert check("1.4.0", deployment(policy.successor_snapshot(), state="rolled_back")) == "physical_test_eligible"
    assert check("1.4.0", deployment(policy.successor_snapshot(), state="recovery_failed")) == "update_evidence_mismatch"
