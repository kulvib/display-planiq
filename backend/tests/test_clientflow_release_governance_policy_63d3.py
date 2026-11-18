"""Dependency-free, default-deny 63D-3 governance preconditions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from service1.clientflow_release_governance_policy import (
    GovernanceDenied, physical_evidence_payload,
    require_approved_physical_evidence, require_revisions, require_wave_action,
)

NOW = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)
RID = 'clientflow-1.3.45-seq-1246'
SHA = 'a' * 64
WAVE = {
    'id': 'wave-1', 'kind': 'controlled', 'state': 'draft',
    'release_id': RID, 'bundle_sha256': SHA,
    'created_by_user_id': 1, 'approved_by_user_id': 2,
    'approved_at': NOW - timedelta(minutes=5), 'expires_at': NOW + timedelta(hours=2),
    'revision': 2,
}
TARGETS = [
    {'wave_id': 'wave-1', 'client_id': i, 'state': 'draft',
     'expires_at': NOW + timedelta(hours=2), 'consumed_deployment_id': None}
    for i in (3, 4)
]
POLICY = {'revision': 7, 'stable_release_id': RID, 'stable_bundle_sha256': SHA}


def _gate(action='approve', wave=None, targets=None, actor=2, now=NOW):
    return require_wave_action(action=action, wave=wave or deepcopy(WAVE),
                               targets=targets or deepcopy(TARGETS), now=now,
                               actor_id=actor)


def test_valid_two_person_review_and_bound_policy():
    require_revisions(control=POLICY, wave=WAVE, control_revision=7, wave_revision=2,
                      release_id=RID, bundle_sha256=SHA)
    _gate()


@pytest.mark.parametrize('modify', [
    lambda p,w: p.update(revision=8),
    lambda p,w: w.update(revision=3),
    lambda p,w: p.update(stable_bundle_sha256='b'*64),
    lambda p,w: w.update(release_id='clientflow-1.3.44-seq-1245'),
])
def test_revision_sha_and_release_binding_fail_closed(modify):
    policy, wave = deepcopy(POLICY), deepcopy(WAVE)
    modify(policy, wave)
    with pytest.raises(GovernanceDenied):
        require_revisions(control=policy, wave=wave, control_revision=7,
                          wave_revision=2, release_id=RID, bundle_sha256=SHA)


@pytest.mark.parametrize('modify', [
    lambda w,t: w.update(kind='pilot'),
    lambda w,t: w.update(state='approved'),
    lambda w,t: w.update(approved_at=None),
    lambda w,t: w.update(approved_by_user_id=None),
    lambda w,t: w.update(created_by_user_id=2),
    lambda w,t: w.update(expires_at=NOW),
    lambda w,t: t[0].update(expires_at=NOW),
    lambda w,t: t[0].update(state='approved'),
    lambda w,t: t[1].update(consumed_deployment_id='deployment'),
    lambda w,t: t[1].update(wave_id='other'),
    lambda w,t: t[1].update(client_id=3),
])
def test_approval_denies_invalid_review_targets_and_expiry(modify):
    wave, targets = deepcopy(WAVE), deepcopy(TARGETS)
    modify(wave, targets)
    with pytest.raises(GovernanceDenied):
        _gate(wave=wave, targets=targets)


def test_paused_wave_stops_consume_but_can_resume_with_fresh_gate():
    wave = deepcopy(WAVE)
    wave['state'] = 'approved'
    _gate('pause', wave=wave)
    wave['state'] = 'paused'
    _gate('resume', wave=wave)
    with pytest.raises(GovernanceDenied):
        _gate('approve', wave=wave)
    with pytest.raises(GovernanceDenied):
        _gate('resume', wave={**wave, 'expires_at': NOW})


def test_stop_can_revoke_expired_wave_without_waiting_for_recovery():
    wave = {**WAVE, 'state': 'running', 'expires_at': NOW - timedelta(seconds=1)}
    _gate('stop', wave=wave)
    with pytest.raises(GovernanceDenied):
        _gate('pause', wave=wave)


def test_evidence_requires_two_distinct_humans_and_bounded_refs():
    evidence = physical_evidence_payload(
        client_id=3, release_id=RID, bundle_sha256=SHA, tested_by_user_id=1,
        reviewer_user_id=2, observed_version='1.3.45',
        pilot_reference='pilot-viborg1-20261118', recovery_reference='recovery-viborg1-20261118',
    )
    assert not any('password' in key or 'token' in key for key in evidence)
    acceptance = {'decision': 'accepted', 'release_id': RID, 'bundle_sha256': SHA,
                  'client_id': 3, 'actor_user_id': 2, 'evidence': evidence,
                  'created_at': NOW - timedelta(minutes=1)}
    require_approved_physical_evidence(
        acceptance=acceptance, release_id=RID, bundle_sha256=SHA, now=NOW)
    for changed in (dict(evidence, recovery_verified=False),
                    dict(evidence, tested_by_user_id=2),
                    dict(evidence, pilot_client_id=4),
                    dict(evidence, pilot_reference='too-short')):
        with pytest.raises(GovernanceDenied):
            require_approved_physical_evidence(
                acceptance=dict(acceptance, evidence=changed),
                release_id=RID, bundle_sha256=SHA, now=NOW)


@pytest.mark.parametrize('changed', [
    {'tested_by_user_id': 2}, {'pilot_reference': 'short'},
    {'recovery_reference': 'pilot-viborg1-20261118'},
    {'bundle_sha256': 'x'*64}, {'observed_version': '1.3.44'},
    {'release_id': 'clientflow-1.3.45-seq-0'},
])
def test_physical_evidence_payload_never_normalizes_invalid_input(changed):
    payload = dict(client_id=3, release_id=RID, bundle_sha256=SHA,
                   tested_by_user_id=1, reviewer_user_id=2,
                   observed_version='1.3.45',
                   pilot_reference='pilot-viborg1-20261118',
                   recovery_reference='recovery-viborg1-20261118')
    payload.update(changed)
    with pytest.raises(GovernanceDenied):
        physical_evidence_payload(**payload)
