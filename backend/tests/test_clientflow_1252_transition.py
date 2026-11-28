"""1252 outcome/retention contracts: isolated fixtures, no real authorization."""
from copy import deepcopy
from types import SimpleNamespace
import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from service1 import clientflow_1252_transition as transition
from service1 import clientflow_pilot_1251 as prior
from service1.clientflow_closed_standard_1251 import closed_standard_catalog
from service1.clientflow_deployments import (
    ClientFlowDeploymentConflict, report_updater_event, utcnow,
)
from service1.clientflow_update_models import ClientFlowDeployment, ClientFlowDeploymentEvent
from service1.models import Client

TARGET = transition.CANDIDATE_ID
PREVIOUS = transition.PREDECESSOR_ID
ROLLBACK = {"failed_release_id": TARGET, "restored_release_id": PREVIOUS}
SUCCESS = {"observed_release_id": TARGET, "observed_release_sequence": 1252,
           "observed_previous_release_id": PREVIOUS}


@pytest.fixture
def baseline(monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    monkeypatch.setenv("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false")
    for flag in prior.CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    control = dict(stable_release_id=PREVIOUS,
                   stable_bundle_sha256=prior.approval_lock_1251()["approved_bundle_sha256"],
                   revision=3, cutover_enabled=False, fleet_open=False, fresh_install_open=False)
    pins = prior.archive_inventory()
    rows = [dict(release_id=rid, size_bytes=pins[rid]["size"], sha256=pins[rid]["sha256"])
            for rid in sorted(prior.RETAINED_IDS)]
    snapshot = dict(protected_latest=rows, older_review_only=[], invalid_artifacts=[], approved_count=3)
    return closed_standard_catalog(), control, snapshot


def test_rotation_plan_preserves_1250_and_1251_and_grants_nothing(baseline):
    original = deepcopy(baseline)
    result = transition.plan_rotation(*baseline)
    assert baseline == original
    assert result["projected_counts"] == [3, 2, 3]
    assert set(result["retain_before_publication"]) == {prior.BASELINE_ID, PREVIOUS}
    assert set(result["retain_after_publication"]) == {prior.BASELINE_ID, PREVIOUS, TARGET}
    assert result["verify_offsite_archive_before_removal"] == {
        transition.OLDEST_ID: prior.archive_inventory()[transition.OLDEST_ID]}
    assert all(result[key] is False for key in (
        "candidate_artifact_verified", "offsite_archive_verified", "destructive_action_authorized",
        "deployment_authorized", "fleet_authorized", "fresh_install_authorized", "manual_rollback_authorized"))


@pytest.mark.parametrize("attack", ["revision", "fleet", "catalog", "duplicate", "missing",
                                   "wrong_hash", "wrong_size", "invalid", "older", "fourth"])
def test_rotation_plan_rejects_bad_inputs(baseline, attack):
    catalog, control, snapshot = baseline
    rows = snapshot["protected_latest"]
    if attack == "revision":
        control["revision"] = 2
    elif attack == "fleet":
        control["fleet_open"] = True
    elif attack == "catalog":
        catalog["catalog_sequence"] = 1252
    elif attack == "duplicate":
        rows[-1] = rows[0]
    elif attack == "missing":
        rows.pop()
    elif attack == "wrong_hash":
        rows[0]["sha256"] = "0" * 64
    elif attack == "wrong_size":
        rows[0]["size_bytes"] += 1
    elif attack == "invalid":
        snapshot["invalid_artifacts"] = ["bad"]
    elif attack == "older":
        snapshot["older_review_only"] = [rows[0]]
    elif attack == "fourth":
        snapshot["approved_count"] = 4
    with pytest.raises((transition.Candidate1252Denied, prior.Pilot1251Denied)):
        transition.plan_rotation(catalog, control, snapshot)


@pytest.mark.parametrize("changes", [
    {"client_id": 0}, {"allow_downgrade": True}, {"target_release_sequence": 1251},
    {"target_release_id": PREVIOUS}, {"target_version": "1.4.1"},
])
def test_mixed_identity_or_wrong_client_does_not_bypass_contract(changes):
    fields = dict(client_id=3, allow_downgrade=False, target_release_id=TARGET,
                  target_release_sequence=1252, target_version="1.4.2")
    fields.update(changes)
    row = SimpleNamespace(**fields)
    assert transition.is_candidate_order(row)
    with pytest.raises(transition.Candidate1252Denied):
        transition.require_candidate_observation(row, "succeeded", SUCCESS)


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    identifier = str(uuid.uuid4())
    now = utcnow()
    with Session(engine) as session:
        session.add(Client(id=3, name="CI-Viborg1-fixture", status="approved"))
        # Explicit synthetic row, not create_authorized_deployment and not a
        # real approval. Exercise the real backend state machine in isolation.
        session.add(ClientFlowDeployment(
            id=identifier, client_id=3, target_release_id=TARGET,
            target_version="1.4.2", target_release_sequence=1252,
            bundle_sha256="a"*64, bundle_size=1, release_approval_reference="synthetic-only",
            release_candidate_sha256="b"*64, source_commit="c"*40,
            allow_downgrade=False, requested_at=now, state_updated_at=now, state="health_check",
        ))
        session.commit()
        yield session, identifier
    engine.dispose()


def report(database, event_type, payload, *, credential="fixture-update-identity", event_id=None):
    session, identifier = database
    return report_updater_event(session, deployment_id=identifier, credential_id=credential,
                                event_id=event_id or str(uuid.uuid4()),
                                event_type=event_type, payload=payload)


@pytest.mark.parametrize("wrong", [None, "clientflow-1.4.0-seq-1250", TARGET])
def test_success_without_exact_predecessor_cannot_terminalize(database, wrong):
    session, identifier = database
    with pytest.raises(ClientFlowDeploymentConflict, match="1251"):
        report(database, "succeeded", {**SUCCESS, "observed_previous_release_id": wrong})
    assert session.get(ClientFlowDeployment, identifier).state == "health_check"
    assert session.exec(select(ClientFlowDeploymentEvent)).all() == []


def test_exact_success_and_identical_replay(database):
    event_id = str(uuid.uuid4())
    row, event, replayed = report(database, "succeeded", SUCCESS, event_id=event_id)
    assert row.state == "succeeded" and row.observed_previous_release_id == PREVIOUS
    assert row.completed_at is not None and not replayed
    assert report(database, "succeeded", SUCCESS, event_id=event_id)[2] is True
    with pytest.raises(ClientFlowDeploymentConflict, match="replay"):
        report(database, "succeeded", {**SUCCESS, "extra": "different"}, event_id=event_id)
    assert event.payload == SUCCESS


def test_rollback_requires_exact_matching_authenticated_event_chain(database):
    session, identifier = database
    with pytest.raises(ClientFlowDeploymentConflict, match="1251"):
        report(database, "rollback_started", {**ROLLBACK, "restored_release_id": prior.BASELINE_ID})
    assert session.get(ClientFlowDeployment, identifier).state == "health_check"
    row, _, _ = report(database, "rollback_started", ROLLBACK)
    assert row.state == "rolling_back"
    with pytest.raises(ClientFlowDeploymentConflict, match="1251"):
        report(database, "rolled_back", {**ROLLBACK, "restored_release_id": TARGET})
    with pytest.raises(ClientFlowDeploymentConflict, match="rollback-start"):
        report(database, "rolled_back", ROLLBACK, credential="other-identity")
    assert row.state == "rolling_back" and row.completed_at is None
    row, _, _ = report(database, "rolled_back", ROLLBACK)
    assert row.state == "rolled_back" and row.completed_at is not None
    assert row.observed_release_id is None  # not a successful 1252 deployment
    events = session.exec(select(ClientFlowDeploymentEvent)).all()
    assert len(events) == 2 and {event.event_type for event in events} == {"rollback_started", "rolled_back"}


@pytest.mark.parametrize("client_id", [3, 7, 100, 101])
def test_outcome_contract_is_independent_of_client_identity(client_id):
    row = SimpleNamespace(client_id=client_id, allow_downgrade=False, target_release_id=TARGET,
                          target_release_sequence=1252, target_version="1.4.2")
    transition.require_candidate_observation(row, "succeeded", SUCCESS)
    transition.require_candidate_observation(row, "rolled_back", ROLLBACK)
