"""The permanent release evidence is deliberately distinct from pilot admission."""
from types import SimpleNamespace
import pytest

from service1.native_rdp_admission import matches_completed_update, matches_completed_enrollment, release_eligibility
from service1.remote_desktop_v2 import native_rdp_client_admitted


ARTIFACT = {"target_release_id": "clientflow-1.4.0-seq-1250", "target_version": "1.4.0",
            "target_release_sequence": 1250, "bundle_sha256": "a"*64, "bundle_size": 123,
            "release_approval_reference": "approved", "release_candidate_sha256": "b"*64,
            "source_commit": "c"*40}


def update(**changes):
    values = dict(ARTIFACT, client_id=37, state="succeeded", completed_at=object(),
                  observed_release_id=ARTIFACT["target_release_id"], observed_release_sequence=1250)
    values.update(changes)
    return SimpleNamespace(**values)


def test_verified_update_evidence_does_not_itself_open_transport():
    assert matches_completed_update(update(), client_id=37, artifact=ARTIFACT)
    assert not native_rdp_client_admitted(37)


@pytest.mark.parametrize("field,value", [
    ("client_id", 3), ("state", "rolled_back"), ("completed_at", None),
    ("observed_release_id", None), ("observed_release_sequence", 1248),
    ("bundle_sha256", "d"*64), ("bundle_size", 124), ("source_commit", "d"*40),
    ("release_candidate_sha256", "d"*64), ("release_approval_reference", "other"),
])
def test_incomplete_or_different_update_evidence_denied(field, value):
    assert not matches_completed_update(update(**{field: value}), client_id=37, artifact=ARTIFACT)


def test_enrollment_requires_exact_completed_identity_and_release():
    client = SimpleNamespace(id=37, enrollment_token_id=12)
    token = SimpleNamespace(id=12, used_by_client_id=37, used_at=object(), revoked_at=None,
        fresh_install_release_id=ARTIFACT["target_release_id"], fresh_install_version=ARTIFACT["target_version"],
        fresh_install_release_sequence=1250, fresh_install_bundle_sha256=ARTIFACT["bundle_sha256"],
        fresh_install_bundle_size=123, fresh_install_approval_reference="approved",
        fresh_install_candidate_sha256=ARTIFACT["release_candidate_sha256"], fresh_install_source_commit=ARTIFACT["source_commit"])
    receipt = SimpleNamespace(client_id=37, completed_at=object())
    assert matches_completed_enrollment(token, receipt, client=client, artifact=ARTIFACT)
    receipt.completed_at = None
    assert not matches_completed_enrollment(token, receipt, client=client, artifact=ARTIFACT)
    receipt.completed_at = object()
    token.fresh_install_bundle_sha256 = "d"*64
    assert not matches_completed_enrollment(token, receipt, client=client, artifact=ARTIFACT)


def test_invalid_identity_never_queries_database():
    class NoDatabase:
        def get(self, *args):
            pytest.fail("invalid identity queried database")
    for value in (0, -1, True, "37"):
        assert release_eligibility(NoDatabase(), client_id=value) == "invalid_identity"


def test_fleet_admission_bounded_and_revocation_clears_decision(monkeypatch):
    from service1 import remote_desktop_v2 as policy
    clock = [100.0]
    calls = []
    decisions = ["eligible", "cutover_closed"]
    monkeypatch.setattr(policy, "_FLEET_ADMITTED_AT", {})
    monkeypatch.setattr(policy.time, "monotonic", lambda: clock[0])
    def check(client_id):
        calls.append(client_id)
        return decisions[0]
    monkeypatch.setattr(policy, "_load_native_release_eligibility", check)
    assert not policy.native_rdp_client_admitted(37)
    assert policy.authorize_native_rdp_client(37, force=True)
    for _ in range(500):
        assert policy.native_rdp_transport_allowed(37, "agent", "wss")
        assert policy.native_rdp_transport_allowed(37, "browser", "wss")
    assert calls == [37]
    assert not policy.native_rdp_transport_allowed(37, "unknown", "wss")
    clock[0] += 13
    decisions.pop(0)
    assert not policy.authorize_native_rdp_client(37)
    assert not policy.native_rdp_client_admitted(37)
    assert calls == [37, 37]


def test_fleet_transport_decision_expires_without_database_call(monkeypatch):
    from service1 import remote_desktop_v2 as policy
    monkeypatch.setattr(policy, "_FLEET_ADMITTED_AT", {37: 100.0})
    monkeypatch.setattr(policy.time, "monotonic", lambda: 131.0)
    monkeypatch.setattr(policy, "_load_native_release_eligibility", lambda _: pytest.fail("hot-path DB read"))
    assert not policy.native_rdp_client_admitted(37)
    assert not policy.native_rdp_transport_allowed(37, "browser", "wss")


def test_actual_artifact_snapshot_shape_and_cache_invalidation(monkeypatch, tmp_path):
    from service1 import native_rdp_admission as admission
    artifact = tmp_path / "approved.tar"
    artifact.write_bytes(b"fixture")
    calls = []
    monkeypatch.setattr(admission, "_artifact_path", lambda _: artifact)
    monkeypatch.setattr(admission, "resolve_release", lambda _: {
        "release_id": ARTIFACT["target_release_id"], "version": "1.4.0", "release_sequence": 1250})
    def verified(_release):
        calls.append(1)
        return {key: value for key, value in ARTIFACT.items()
                if key not in {"target_version", "target_release_sequence"}}
    monkeypatch.setattr(admission, "deployment_release_snapshot", verified)
    admission._verified_baseline_artifact.cache_clear()
    try:
        for _ in range(10):
            assert admission.canonical_baseline_artifact() == ARTIFACT
        assert calls == [1]
        artifact.write_bytes(b"changed")
        assert admission.canonical_baseline_artifact() == ARTIFACT
        assert calls == [1, 1]
    finally:
        admission._verified_baseline_artifact.cache_clear()
