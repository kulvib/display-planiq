"""Exact-source 1242 one-device authorization and two-phase locking tests."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from service1.clientflow_pilot_1242 import (
    ClientFlowPilot1242Denied, PILOT_FLAG, OLD_PILOT_FLAG,
    PILOT_APPROVED_BUNDLE_SHA256, PILOT_APPROVED_BUNDLE_SIZE,
    PILOT_APPROVAL_REFERENCE, PILOT_CANDIDATE_SHA256, PILOT_SOURCE_COMMIT,
    require_pilot_1242,
)
from service1.clientflow_releases import (
    ClientFlowCatalogError, load_catalog, resolve_fresh_install_release,
    resolve_release, validate_release_compatibility,
)
from service1.routers import clientflow_deployments as router

ROOT = Path(__file__).resolve().parents[2]


def _release():
    load_catalog.cache_clear()
    return resolve_release("1.3.41")


def _artifact():
    return dict(
        target_release_id="clientflow-1.3.41-seq-1242",
        bundle_sha256=PILOT_APPROVED_BUNDLE_SHA256,
        bundle_size=PILOT_APPROVED_BUNDLE_SIZE,
        release_approval_reference=PILOT_APPROVAL_REFERENCE,
        release_candidate_sha256=PILOT_CANDIDATE_SHA256,
        source_commit=PILOT_SOURCE_COMMIT,
    )


def _require(**kwargs):
    args = dict(
        client_id=17, current_version="1.3.38", release=_release(),
        reason="Reserved onsite Ubuntu 26.04 physical pilot", pre_first_activation_repair=False,
        confirm_downgrade=False, artifact=_artifact(),
    )
    args.update(kwargs)
    return require_pilot_1242(**args)


@pytest.mark.parametrize("flag", [None, "", "0", "1", "01", "00017", "+17", " 17", "17 ",
                                  "17,18", "*", "all", "true", "-17", "2e1", "١٧", "99999999999999999999999"])
def test_disabled_or_malformed_flag_fails_closed(monkeypatch, flag):
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    if flag is None:
        monkeypatch.delenv(PILOT_FLAG, raising=False)
    else:
        monkeypatch.setenv(PILOT_FLAG, flag)
    with pytest.raises(ClientFlowPilot1242Denied):
        _require()


def test_only_explicit_non_heidi_reserve_client_can_update(monkeypatch):
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    monkeypatch.setenv(PILOT_FLAG, "17")
    assert _require() is None
    for other in [1, 0, -1, 2, 18, 17.0, True, "17", None]:
        with pytest.raises(ClientFlowPilot1242Denied):
            _require(client_id=other)
    monkeypatch.setenv(PILOT_FLAG, "1")
    with pytest.raises(ClientFlowPilot1242Denied):
        _require(client_id=1)


def test_never_run_two_pilot_authorities_at_once(monkeypatch):
    monkeypatch.setenv(PILOT_FLAG, "17")
    monkeypatch.setenv(OLD_PILOT_FLAG, "1")
    with pytest.raises(ClientFlowPilot1242Denied, match="1241-piloten"):
        _require()
    from service1.clientflow_pilot_1241 import ClientFlowPilotDenied, require_pilot_1241
    with pytest.raises(ClientFlowPilotDenied, match="1242-piloten"):
        require_pilot_1241(client_id=1, current_version="1.3.38", release=resolve_release("1.3.40"),
                           reason="old pilot", pre_first_activation_repair=False, confirm_downgrade=False)


@pytest.mark.parametrize("source_version", ["1.3.37", "1.3.39", "1.3.40", "1.3.41", "", "v1.3.38", None])
def test_only_1338_is_supported_source(monkeypatch, source_version):
    monkeypatch.setenv(PILOT_FLAG, "17")
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    with pytest.raises(ClientFlowPilot1242Denied):
        _require(current_version=source_version)


@pytest.mark.parametrize("key,value", [
    ("version", "1.3.40"), ("release_sequence", 1241), ("release_sequence", "1242"),
    ("release_sequence", True), ("release_id", "clientflow-1.3.40-seq-1241"),
    ("status", "stable"), ("installable", True), ("update_allowed", False),
    ("rollback_allowed", True), ("requires_explicit_downgrade", True),
    ("requires_reboot", False), ("install_modes", ["fresh_install", "in_place_update"]),
    ("min_current_version", "1.3.11"), ("max_current_version", "1.3.40"),
])
def test_broadened_release_is_rejected(monkeypatch, key, value):
    monkeypatch.setenv(PILOT_FLAG, "17")
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    altered = _release()
    altered[key] = value
    with pytest.raises(ClientFlowPilot1242Denied):
        _require(release=altered)


@pytest.mark.parametrize("key,value", [
    ("target_release_id", "clientflow-1.3.40-seq-1241"),
    ("bundle_sha256", "0"*64), ("bundle_size", 223610881),
    ("release_approval_reference", "other"), ("release_candidate_sha256", "0"*64),
    ("source_commit", "0"*40),
])
def test_mutated_approved_bytes_fail_closed(monkeypatch, key, value):
    monkeypatch.setenv(PILOT_FLAG, "17")
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    artifact = _artifact()
    artifact[key] = value
    with pytest.raises(ClientFlowPilot1242Denied, match="artifact matcher ikke"):
        _require(artifact=artifact)


@pytest.mark.parametrize("kwargs", [
    {"reason": None}, {"reason": "  "},
    {"pre_first_activation_repair": True}, {"confirm_downgrade": True},
])
def test_requires_reason_and_rejects_repair_or_downgrade(monkeypatch, kwargs):
    monkeypatch.setenv(PILOT_FLAG, "17")
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    with pytest.raises(ClientFlowPilot1242Denied):
        _require(**kwargs)


def test_catalog_is_separate_from_fresh_install_and_manual_rollback():
    data = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())
    assert data["catalog_sequence"] == 1242
    assert data["latest_stable"] == data["default_install_version"] == "1.3.38"
    assert [x["release_sequence"] for x in data["releases"]] == [1239, 1241, 1242]
    assert resolve_fresh_install_release()["release_id"] == "clientflow-1.3.38-seq-1239"
    candidate = _release()
    assert candidate["install_modes"] == ["in_place_update"]
    assert candidate["installable"] is False and candidate["rollback_allowed"] is False
    validate_release_compatibility(candidate, current_version="1.3.38", ubuntu_version="26.04")
    for source in ("1.3.37", "1.3.40", "1.3.41"):
        with pytest.raises(ClientFlowCatalogError):
            validate_release_compatibility(candidate, current_version=source, ubuntu_version="26.04")
    for implicit in ("", "latest", "stable"):
        with pytest.raises(ClientFlowCatalogError):
            resolve_release(implicit)
    with pytest.raises(ClientFlowCatalogError):
        resolve_release("1.3.39")


def test_http_pilot_rejected_before_artifact_lookup(monkeypatch):
    monkeypatch.delenv(PILOT_FLAG, raising=False)
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    client = SimpleNamespace(id=17, status="approved", deleted_at=None, ubuntu_version="26.04.1")
    monkeypatch.setattr(router, "_client_or_404", lambda *_: client)
    monkeypatch.setattr(router, "_require_deployable_client", lambda *_: None)
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: "1.3.38")
    monkeypatch.setattr(router, "deployment_release_snapshot", lambda *_: pytest.fail("preflight must fail first"))
    with pytest.raises(HTTPException) as exc:
        router.create_clientflow_deployment(17, router.ClientFlowDeploymentCreate(target_version="1.3.41", reason="test"),
                                            object(), object(), SimpleNamespace(id=4))
    assert exc.value.status_code == 409


def test_http_exact_artifact_and_locked_status_second_check(monkeypatch):
    monkeypatch.setenv(PILOT_FLAG, "17")
    monkeypatch.delenv(OLD_PILOT_FLAG, raising=False)
    client = SimpleNamespace(id=17, status="approved", deleted_at=None, ubuntu_version="26.04.1",
                             organization_id=7, name="Reserve1")
    monkeypatch.setattr(router, "_client_or_404", lambda *_: client)
    monkeypatch.setattr(router, "_require_deployable_client", lambda *_: None)
    monkeypatch.setattr(router, "lock_system_client", lambda *_: None)
    monkeypatch.setattr(router, "add_audit_log", lambda *_a, **_k: None)
    monkeypatch.setattr(router, "deployment_release_snapshot", lambda *_: _artifact())
    class Session:
        def __init__(self): self.committed = False
        def commit(self): self.committed = True
        def rollback(self): pass
        def refresh(self, _row): pass
    session = Session()
    calls = []
    def create_authorized(_session, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(**kwargs, id="deployment-1242")
    monkeypatch.setattr(router, "create_authorized_deployment", create_authorized)
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: "1.3.38")
    result = router.create_clientflow_deployment(17, router.ClientFlowDeploymentCreate(target_version="1.3.41", reason="physical pilot"),
                                                 object(), session, SimpleNamespace(id=4))
    assert result.target_release_id == "clientflow-1.3.41-seq-1242"
    assert result.bundle_sha256 == PILOT_APPROVED_BUNDLE_SHA256
    assert session.committed and len(calls) == 1
    assert calls[0]["allow_downgrade"] is False
    # Status changes across lock: no authorization may be issued.
    session.committed = False
    calls.clear()
    versions = iter(("1.3.38", "1.3.40"))
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: next(versions))
    with pytest.raises(HTTPException) as exc:
        router.create_clientflow_deployment(17, router.ClientFlowDeploymentCreate(target_version="1.3.41", reason="physical pilot"),
                                             object(), session, SimpleNamespace(id=4))
    assert exc.value.status_code == 409
    assert not session.committed and not calls
    # Immutable artifact mismatch cannot pass after lock.
    wrong = _artifact()
    wrong["bundle_sha256"] = "0"*64
    monkeypatch.setattr(router, "deployment_release_snapshot", lambda *_: wrong)
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: "1.3.38")
    with pytest.raises(HTTPException) as exc:
        router.create_clientflow_deployment(17, router.ClientFlowDeploymentCreate(target_version="1.3.41", reason="physical pilot"),
                                             object(), session, SimpleNamespace(id=4))
    assert exc.value.status_code == 409
    assert not session.committed and not calls


def test_1242_authorization_is_always_checked_twice():
    source = (ROOT / "backend/service1/routers/clientflow_deployments.py").read_text()
    create = source[source.index("def create_clientflow_deployment("):source.index("@router.get(", source.index("def create_clientflow_deployment("))]
    assert create.count("_require_exact_scoped_pilot(") == 2
    assert create.index("_require_exact_scoped_pilot(") < create.index("deployment_release_snapshot(release)")
    assert create.index("lock_system_client(") < create.rindex("_require_exact_scoped_pilot(")
    assert create.rindex("_require_exact_scoped_pilot(") < create.index("create_authorized_deployment(")
    assert "artifact=artifact" in create
    assert "locked_version = _canonical_runtime_version" in create
