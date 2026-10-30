"""The 1241 pilot is exact-byte, exact-source, single-client, fail-closed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1.clientflow_pilot_1241 import (
    ClientFlowPilotDenied,
    PILOT_APPROVED_BUNDLE_SHA256,
    PILOT_APPROVED_BUNDLE_SIZE,
    PILOT_APPROVAL_REFERENCE,
    PILOT_CANDIDATE_SHA256,
    PILOT_FLAG,
    PILOT_SOURCE_COMMIT,
    require_pilot_1241,
)
from service1.clientflow_releases import (
    ClientFlowCatalogError,
    load_catalog,
    resolve_fresh_install_release,
    resolve_release,
    validate_release_compatibility,
)

ROOT = Path(__file__).resolve().parents[2]


def _pilot():
    load_catalog.cache_clear()
    return resolve_release("1.3.40")


def _artifact():
    return {
        "target_release_id": "clientflow-1.3.40-seq-1241",
        "bundle_sha256": PILOT_APPROVED_BUNDLE_SHA256,
        "bundle_size": PILOT_APPROVED_BUNDLE_SIZE,
        "release_approval_reference": PILOT_APPROVAL_REFERENCE,
        "release_candidate_sha256": PILOT_CANDIDATE_SHA256,
        "source_commit": PILOT_SOURCE_COMMIT,
    }


def _require(**overrides):
    args = {
        "client_id": 1,
        "current_version": "1.3.38",
        "release": _pilot(),
        "reason": "Manual, physically observed Viborg1 update pilot",
        "pre_first_activation_repair": False,
        "confirm_downgrade": False,
        "artifact": _artifact(),
    }
    args.update(overrides)
    return require_pilot_1241(**args)


def test_1241_pilot_is_disabled_by_default_and_not_an_implicit_fleet_allowlist(monkeypatch):
    for value in (None, "", "true", "yes", "0", "2", "1,2", "*", "01", " 1 "):
        if value is None:
            monkeypatch.delenv(PILOT_FLAG, raising=False)
        else:
            monkeypatch.setenv(PILOT_FLAG, value)
        with pytest.raises(ClientFlowPilotDenied, match="ikke aktiveret"):
            _require()


def test_retired_flag_cannot_authorize_successor_pilot(monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_1240_PILOT_CLIENT_ID", "1")
    monkeypatch.delenv(PILOT_FLAG, raising=False)
    with pytest.raises(ClientFlowPilotDenied, match="ikke aktiveret"):
        _require()


def test_1241_pilot_allows_exact_authorized_request_and_pinned_bundle(monkeypatch):
    monkeypatch.setenv(PILOT_FLAG, "1")
    assert _require() is None
    candidate = _pilot()
    validate_release_compatibility(candidate, current_version="1.3.38", ubuntu_version="26.04.1")


@pytest.mark.parametrize("unauthorized", [0, 2, 3, 999, -1, True, "1"])
def test_1241_pilot_rejects_every_other_client_even_when_enabled(monkeypatch, unauthorized):
    monkeypatch.setenv(PILOT_FLAG, "1")
    with pytest.raises(ClientFlowPilotDenied):
        _require(client_id=unauthorized)


@pytest.mark.parametrize("version", ["1.3.37", "1.3.39", "1.3.40", "", "v1.3.38"])
def test_1241_pilot_only_updates_exact_1338_source(monkeypatch, version):
    monkeypatch.setenv(PILOT_FLAG, "1")
    with pytest.raises(ClientFlowPilotDenied):
        _require(current_version=version)


@pytest.mark.parametrize("field,value", [
    ("version", "1.3.38"), ("release_sequence", 1239), ("release_sequence", "1241"),
    ("release_id", "clientflow-1.3.38-seq-1239"),
    ("status", "stable"), ("update_allowed", False), ("rollback_allowed", True),
    ("installable", True), ("install_modes", ["fresh_install", "in_place_update"]),
    ("min_current_version", "1.3.11"), ("max_current_version", "1.3.40"),
])
def test_1241_pilot_rejects_broadened_catalog_permissions(monkeypatch, field, value):
    monkeypatch.setenv(PILOT_FLAG, "1")
    modified = _pilot()
    modified[field] = value
    with pytest.raises(ClientFlowPilotDenied):
        _require(release=modified)


@pytest.mark.parametrize("field,value", [
    ("bundle_sha256", "0" * 64), ("bundle_size", 223518721),
    ("target_release_id", "clientflow-1.3.39-seq-1240"),
    ("release_approval_reference", "other-approval"),
    ("release_candidate_sha256", "0" * 64),
    ("source_commit", "0" * 40),
])
def test_1241_pilot_rejects_altered_immutable_artifact_identity(monkeypatch, field, value):
    monkeypatch.setenv(PILOT_FLAG, "1")
    artifact = _artifact()
    artifact[field] = value
    with pytest.raises(ClientFlowPilotDenied, match="artifact matcher ikke approval"):
        _require(artifact=artifact)


@pytest.mark.parametrize("kwargs", [
    {"reason": None}, {"reason": "  "},
    {"pre_first_activation_repair": True}, {"confirm_downgrade": True},
])
def test_1241_pilot_rejects_repair_downgrade_and_unreasoned_authority(monkeypatch, kwargs):
    monkeypatch.setenv(PILOT_FLAG, "1")
    with pytest.raises(ClientFlowPilotDenied):
        _require(**kwargs)


def test_1241_catalog_and_fresh_install_are_separate_authorities():
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())
    assert catalog["catalog_sequence"] == 1242
    assert all(item["release_sequence"] != 1240 for item in catalog["releases"])
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert len(catalog["releases"]) == 3
    assert catalog["releases"][2]["release_id"] == "clientflow-1.3.41-seq-1242"
    assert resolve_fresh_install_release()["release_id"] == "clientflow-1.3.38-seq-1239"
    pilot = _pilot()
    assert pilot["install_modes"] == ["in_place_update"]
    assert pilot["installable"] is False and pilot["rollback_allowed"] is False
    for bad in ("1.3.37", "1.3.38", "1.3.39"):
        with pytest.raises(ClientFlowCatalogError):
            resolve_release(bad)
    with pytest.raises(ClientFlowCatalogError):
        validate_release_compatibility(pilot, current_version="1.3.37", ubuntu_version="26.04")
    with pytest.raises(ClientFlowCatalogError):
        validate_release_compatibility(pilot, current_version="1.3.40", ubuntu_version="26.04")


def test_1241_guard_is_exercised_twice_on_each_deployment_authorization():
    source = (ROOT / "backend/service1/routers/clientflow_deployments.py").read_text()
    create = source[source.index("def create_clientflow_deployment("):source.index("@router.get(",source.index("def create_clientflow_deployment("))]
    assert create.count("_require_exact_scoped_pilot(") == 2
    assert create.index("_require_exact_scoped_pilot(") < create.index("deployment_release_snapshot(release)")
    assert create.index("lock_system_client(") < create.rindex("_require_exact_scoped_pilot(")
    assert create.rindex("_require_exact_scoped_pilot(") < create.index("create_authorized_deployment(")
    assert "locked_version = _canonical_runtime_version" in create
    assert "artifact=artifact" in create


def test_http_deployment_authority_is_denied_for_nonpilot_client(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from service1.routers import clientflow_deployments as router

    monkeypatch.setenv(PILOT_FLAG, "1")
    client = SimpleNamespace(id=2, status="approved", deleted_at=None, ubuntu_version="26.04.1")
    monkeypatch.setattr(router, "_client_or_404", lambda *_: client)
    monkeypatch.setattr(router, "_require_deployable_client", lambda *_: None)
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: "1.3.38")
    monkeypatch.setattr(router, "deployment_release_snapshot", lambda *_: pytest.fail("must deny before artifact"))
    with pytest.raises(HTTPException) as exc:
        router.create_clientflow_deployment(
            client_id=2,
            body=router.ClientFlowDeploymentCreate(target_version="1.3.40", reason="test"),
            request=object(), session=object(), user=SimpleNamespace(id=5),
        )
    assert exc.value.status_code == 409
    assert "pilotklient 1" in str(exc.value.detail)


def test_http_deployment_pins_artifact_and_rechecks_locked_status(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from service1.routers import clientflow_deployments as router

    monkeypatch.setenv(PILOT_FLAG, "1")
    client = SimpleNamespace(id=1, status="approved", deleted_at=None, ubuntu_version="26.04.1",
                             organization_id=7, name="Viborg1")
    monkeypatch.setattr(router, "_client_or_404", lambda *_: client)
    monkeypatch.setattr(router, "_require_deployable_client", lambda *_: None)
    monkeypatch.setattr(router, "lock_system_client", lambda *_: None)
    monkeypatch.setattr(router, "deployment_release_snapshot", lambda *_: _artifact())
    monkeypatch.setattr(router, "add_audit_log", lambda *_args, **_kw: None)

    class Session:
        def __init__(self):
            self.committed = False
        def commit(self):
            self.committed = True
        def refresh(self, _obj):
            pass

    session = Session()
    calls = []
    def create_authorized(_session, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(**kwargs, id="deployment-1")
    monkeypatch.setattr(router, "create_authorized_deployment", create_authorized)
    body = router.ClientFlowDeploymentCreate(target_version="1.3.40", reason="Heidi1 manual acceptance")
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: "1.3.38")
    result = router.create_clientflow_deployment(client_id=1, body=body, request=object(),
                                                  session=session, user=SimpleNamespace(id=5))
    assert result.target_release_id == "clientflow-1.3.40-seq-1241"
    assert session.committed and len(calls) == 1
    assert calls[0]["bundle_sha256"] == PILOT_APPROVED_BUNDLE_SHA256
    assert calls[0]["client_id"] == 1
    assert calls[0]["allow_downgrade"] is False

    # If Status changed between the first check and lock, no new order is issued.
    session.committed = False
    calls.clear()
    observations = iter(("1.3.38", "1.3.40"))
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: next(observations))
    with pytest.raises(HTTPException) as exc:
        router.create_clientflow_deployment(client_id=1, body=body, request=object(),
                                            session=session, user=SimpleNamespace(id=5))
    assert exc.value.status_code == 409
    assert not session.committed and not calls

    # An approved-format bundle with a different identity must also fail after lock.
    session.committed = False
    calls.clear()
    monkeypatch.setattr(router, "_canonical_runtime_version", lambda *_: "1.3.38")
    tampered = _artifact()
    tampered["bundle_sha256"] = "0" * 64
    monkeypatch.setattr(router, "deployment_release_snapshot", lambda *_: tampered)
    with pytest.raises(HTTPException) as exc:
        router.create_clientflow_deployment(client_id=1, body=body, request=object(),
                                            session=session, user=SimpleNamespace(id=5))
    assert exc.value.status_code == 409
    assert not session.committed and not calls
