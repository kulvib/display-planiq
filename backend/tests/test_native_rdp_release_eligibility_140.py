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
    monkeypatch.setattr(policy, "_NATIVE_ADMISSION_DECISIONS", {})
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
    monkeypatch.setattr(policy, "_NATIVE_ADMISSION_DECISIONS", {37: (100.0, "eligible")})
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



def test_all_identities_require_fresh_admission_and_only_legacy_allows_unmanaged(monkeypatch):
    from service1 import remote_desktop_v2 as policy
    clock = [100.0]
    decision = ["legacy_pilot_eligible"]
    monkeypatch.setattr(policy, "_NATIVE_ADMISSION_DECISIONS", {})
    monkeypatch.setattr(policy.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(policy, "_load_native_release_eligibility", lambda _: decision[0])
    assert not policy.native_rdp_client_admitted(3)
    assert not policy.native_rdp_pilot_admitted(3)
    assert policy.authorize_native_rdp_client(3, force=True)
    assert policy.native_rdp_pilot_admitted(3)
    for mode in ("physical_test_eligible", "eligible"):
        decision[0] = mode
        assert policy.authorize_native_rdp_client(3, force=True)
        assert not policy.native_rdp_pilot_admitted(3)
        assert policy.native_rdp_transport_allowed(3, "browser", "wss")
    decision[0] = "cutover_closed"
    assert not policy.authorize_native_rdp_client(3, force=True)
    assert not policy.native_rdp_client_admitted(3)


def test_admission_capacity_and_packet_gate_at_100_clients(monkeypatch):
    from service1 import remote_desktop_v2 as policy
    clock = [100.0]
    calls = []
    monkeypatch.setattr(policy, "_NATIVE_ADMISSION_DECISIONS", {})
    monkeypatch.setattr(policy.time, "monotonic", lambda: clock[0])
    def check(client_id):
        calls.append(client_id)
        return "eligible"
    monkeypatch.setattr(policy, "_load_native_release_eligibility", check)
    for cid in range(1, 129):
        assert policy.authorize_native_rdp_client(cid, force=True)
    assert len(calls) == 128
    assert not policy.authorize_native_rdp_client(129, force=True)
    for cid in range(1, 101):
        for _ in range(100):
            assert policy.native_rdp_transport_allowed(cid, "browser", "wss")
            assert policy.native_rdp_transport_allowed(cid, "agent", "wss")
    assert len(calls) == 128
    clock[0] += 31
    assert not policy.native_rdp_client_admitted(3)
    assert policy.authorize_native_rdp_client(129, force=True)
    assert len(policy._NATIVE_ADMISSION_DECISIONS) == 1


def test_preacceptance_and_standard_admission_use_real_deployment_rows(monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4
    from sqlmodel import SQLModel, Session, create_engine
    from service1 import native_rdp_admission as admission
    from service1.clientflow_update_models import ClientFlowDeployment, ClientFlowDeploymentEvent
    from service1.clientflow_release_admin_models import ClientFlowReleaseControl, ClientFlowPhysicalAcceptance
    from service1.models import Client, User, Organization
    from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[
        Organization.__table__, User.__table__, Client.__table__,
        ClientFlowReleaseControl.__table__, ClientFlowPhysicalAcceptance.__table__,
        ClientFlowDeployment.__table__, ClientFlowDeploymentEvent.__table__,
        RemoteDesktopClient.__table__, RemoteDesktopCredential.__table__,
    ])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    versions = {3: "1.3.47", 37: "1.4.0"}
    monkeypatch.setattr(admission, "load_client_presence", lambda _db, client:
        SimpleNamespace(status=SimpleNamespace(is_online=True, agent_version=versions[client.id])))
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    from service1.clientflow_pilot_1250 import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setattr(admission, "load_catalog", lambda: {
        "catalog_sequence": 1248, "latest_stable": "1.3.44", "default_install_version": "1.3.44"})
    approved = {"approved_bundle_sha256": ARTIFACT["bundle_sha256"],
        "approved_bundle_size": ARTIFACT["bundle_size"], "approval_reference": ARTIFACT["release_approval_reference"],
        "candidate_sha256": ARTIFACT["release_candidate_sha256"], "source_commit": ARTIFACT["source_commit"]}
    monkeypatch.setattr(admission, "approval_lock_1250", lambda: approved)
    monkeypatch.setattr(admission, "canonical_baseline_artifact", lambda **_: dict(ARTIFACT))
    with Session(engine) as db:
        control = ClientFlowReleaseControl(id=1, stable_release_id="clientflow-1.3.44-seq-1245",
            stable_bundle_sha256="28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5",
            revision=1, updated_at=now)
        db.add(control)
        for cid, name in ((3, "Viborg1"), (37, "Other")):
            db.add(Client(id=cid, name=name, status="approved", ubuntu_version="26.04"))
            db.add(RemoteDesktopClient(id=cid, status="approved", created_at=now))
            db.add(RemoteDesktopCredential(id=str(uuid4()), client_id=cid, secret_hash="fixture", created_at=now))
        db.commit()
        assert admission.release_eligibility(db, client_id=3) == "legacy_pilot_eligible"
        assert admission.release_eligibility(db, client_id=37) == "cutover_closed"
        versions[3] = "1.4.0"
        assert admission.release_eligibility(db, client_id=3) == "update_evidence_mismatch"
        deployment = ClientFlowDeployment(id=str(uuid4()), client_id=3, **ARTIFACT,
            requested_at=now, state_updated_at=now, state="succeeded", completed_at=now,
            observed_release_id=ARTIFACT["target_release_id"], observed_release_sequence=1250)
        db.add(deployment)
        db.commit()
        assert admission.release_eligibility(db, client_id=3) == "physical_test_eligible"
        approved["approved_bundle_size"] += 1
        assert admission.release_eligibility(db, client_id=3) == "release_evidence_unavailable"
        approved["approved_bundle_size"] -= 1
        deployment.observed_release_sequence = 1248
        db.add(deployment)
        db.commit()
        assert admission.release_eligibility(db, client_id=3) == "update_evidence_mismatch"
        deployment.observed_release_sequence = 1250
        db.add(deployment)
        db.commit()
        control.stable_release_id = ARTIFACT["target_release_id"]
        control.stable_bundle_sha256 = ARTIFACT["bundle_sha256"]
        control.cutover_enabled = True
        control.fleet_open = True
        db.add(control)
        db.commit()
        assert admission.release_eligibility(db, client_id=3) == "physical_acceptance_unavailable"
        control.fleet_open = False
        db.add(control)
        db.commit()
        assert admission.release_eligibility(db, client_id=3) == "cutover_closed"
    engine.dispose()
