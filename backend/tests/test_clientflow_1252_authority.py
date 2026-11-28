"""1252 exact evidence boundaries; no production writes."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from service1 import clientflow_1252_authority as authority
from service1 import native_rdp_admission as admission
from service1.clientflow_1252_transition import Candidate1252Denied, CANDIDATE_ID, PREDECESSOR_ID
from service1.clientflow_pilot_1252 import candidate_snapshot
from service1.clientflow_pilot_1251 import successor_snapshot
from service1.clientflow_deployments import create_authorized_deployment, ClientFlowDeploymentConflict


def candidate(**changes):
    now = datetime(2026, 11, 28)
    return SimpleNamespace(**{**candidate_snapshot(), "id": "test-order", "client_id": 3,
        "allow_downgrade": False, "state": "succeeded", "requested_at": now,
        "completed_at": now + timedelta(seconds=1), "observed_release_id": CANDIDATE_ID,
        "observed_release_sequence": 1252, "observed_previous_release_id": PREDECESSOR_ID, **changes})


@pytest.mark.parametrize("changes", [{"client_id": 4}, {"allow_downgrade": True},
    {"bundle_sha256": "0"*64}, {"release_candidate_sha256": "0"*64},
    {"source_commit": "0"*40}, {"target_release_sequence": 1251}])
def test_exact_order_pin_rejects_aliases(changes):
    authority.require_exact_order(candidate())
    with pytest.raises(Candidate1252Denied):
        authority.require_exact_order(candidate(**changes))


def test_generic_create_cannot_authorize_candidate():
    with pytest.raises(ClientFlowDeploymentConflict, match="særskilt"):
        create_authorized_deployment(None, client_id=3, requested_by_user_id=1,
            **candidate_snapshot(), allow_downgrade=False, reason="fixture")


def test_access_requires_one_exact_order_and_closed_control(monkeypatch):
    row = candidate()
    monkeypatch.setattr(authority, "require_control", lambda session: None)
    monkeypatch.setattr(authority, "candidate_orders", lambda session: [row])
    authority.require_candidate_access(None, row)
    monkeypatch.setattr(authority, "candidate_orders", lambda session: [row, row])
    with pytest.raises(Candidate1252Denied):
        authority.require_candidate_access(None, row)
    with pytest.raises(Candidate1252Denied):
        authority.require_candidate_access(None, candidate(bundle_sha256="0"*64))


def test_rdp_success_and_restoration_are_not_inferred_from_version(monkeypatch):
    monkeypatch.setattr(authority, "require_candidate_access", lambda *args: None)
    monkeypatch.setattr(authority, "require_candidate_history", lambda *args: None)
    monkeypatch.setattr(admission, "canonical_1252_artifact", candidate_snapshot)
    monkeypatch.setattr(admission, "canonical_successor_artifact", successor_snapshot)
    def check(row, version):
        return admission._candidate_1252_eligibility(None, latest=row, version=version)
    assert check(candidate(), "1.4.2") == "physical_test_eligible"
    assert check(candidate(observed_previous_release_id=None), "1.4.2") == "update_evidence_mismatch"
    assert check(candidate(state="recovery_failed"), "1.4.1") == "update_evidence_mismatch"
    assert check(candidate(), "1.4.1") == "update_evidence_mismatch"
    row = candidate(state="rolled_back")
    monkeypatch.setattr(authority, "recovery_events", lambda *args: [])
    assert check(row, "1.4.1") == "update_evidence_mismatch"
    event = SimpleNamespace(credential_id=None, payload=authority.RECOVERY_PAYLOAD,
                            received_at=row.completed_at)
    monkeypatch.setattr(authority, "recovery_events", lambda *args: [event])
    assert check(row, "1.4.1") == "physical_test_eligible"
    event.payload = {"verified_local_state": True}
    assert check(row, "1.4.1") == "update_evidence_mismatch"


def test_recovery_requires_matching_terminal_chain():
    row = candidate(state="rolled_back")
    expected = {"failed_release_id": CANDIDATE_ID, "restored_release_id": PREDECESSOR_ID}
    def event(kind, payload, credential="cred"):
        return SimpleNamespace(event_type=kind, payload=payload, credential_id=credential, received_at=row.completed_at)
    events = [event("activation_started", {}), event("rollback_started", expected), event("rolled_back", expected)]
    session = SimpleNamespace(exec=lambda _: SimpleNamespace(all=lambda: events),
                              get=lambda *_: SimpleNamespace(client_id=3, revoked_at=None))
    assert authority.recovery_events(session, row) == []
    events[-1].credential_id = "other"
    with pytest.raises(Candidate1252Denied):
        authority.recovery_events(session, row)
    events[-1].credential_id = "cred"
    events[-1].payload = {"restored_release_id": PREDECESSOR_ID}
    with pytest.raises(Candidate1252Denied):
        authority.recovery_events(session, row)
    events[:] = [event("failed", {}), event("activation_started", {})]
    with pytest.raises(Candidate1252Denied):
        authority.recovery_events(session, candidate(state="failed"))
