from dataclasses import replace
from types import SimpleNamespace

import pytest

from service1 import clientflow_managed_rollout as managed
from service1.clientflow_deployments import create_authorized_deployment, ClientFlowDeploymentConflict


def target(client_id, version="1.4.1"):
    return SimpleNamespace(client_id=client_id, expected_source_version=version)


def test_current_registration_is_exact_and_default_closed():
    policy = managed.current_policy()
    assert policy.enabled is False
    assert policy.target["target_release_sequence"] == 1252
    assert policy.source["target_release_sequence"] == 1251
    assert policy.target["bundle_sha256"] == "8ddabdb5429f116b93a4b3ee7433c09572bcc8d8cbeda18160ececb5dde130a1"
    with pytest.raises(managed.ManagedRolloutDenied):
        managed.require_control(None, policy)


def test_selection_accepts_arbitrary_compatible_client_ids():
    policy = managed.current_policy()
    assert [row.client_id for row in managed.select_targets(policy, [target(80), target(7)])] == [7,80]
    assert len(managed.select_targets(policy, [target(i) for i in range(1,26)])) == 25
    for invalid in ([], [target(7),target(7)], [target(True)], [target(0)], [target(7,"1.4.0")],
                    [target(i) for i in range(1,27)]):
        with pytest.raises(managed.ManagedRolloutDenied):
            managed.select_targets(policy, invalid)


def test_managed_target_cannot_use_ordinary_creation_or_mixed_identity():
    policy = managed.current_policy()
    for change in ({}, {"target_release_id":policy.source["target_release_id"]},
                   {"target_version":policy.source["target_version"]}):
        with pytest.raises(ClientFlowDeploymentConflict):
            create_authorized_deployment(None, client_id=7, requested_by_user_id=1,
                **{**policy.target, **change}, allow_downgrade=False, reason="fixture")


def test_exact_order_evidence_rejects_missing_or_mixed_snapshot():
    policy = replace(managed.current_policy(), enabled=True)
    row = SimpleNamespace(**policy.target, id="fixture", requested_by_user_id=1, allow_downgrade=False)
    event = SimpleNamespace(credential_id=None, payload=managed.authorization_payload(policy))
    events = [event]
    session = SimpleNamespace(exec=lambda query: SimpleNamespace(all=lambda:events))
    managed.require_order_evidence(session, row, policy)
    events.append(event)
    with pytest.raises(managed.ManagedRolloutDenied):
        managed.require_order_evidence(session, row, policy)
    events.pop()
    event.payload = {"authority":managed.MANAGED_AUTHORITY}
    with pytest.raises(managed.ManagedRolloutDenied):
        managed.require_order_evidence(session, row, policy)
