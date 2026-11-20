"""No-production side effects: pure 63D release preconditions and gate matrix."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from service1.clientflow_release_readiness import assess_future_db_wave, planning_readiness

RELEASE = "clientflow-1.3.45-seq-1246"
SHA = "a" * 64
NOW = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)


def _ready_wave():
    return {
        "control": {
            "cutover_enabled": True, "fleet_open": True,
            "stable_release_id": RELEASE, "stable_bundle_sha256": SHA,
        },
        "wave": {
            "id": "wave-1", "kind": "controlled", "state": "approved",
            "release_id": RELEASE, "bundle_sha256": SHA,
            "source_version": "1.3.43", "approved_at": NOW,
            "approved_by_user_id": 2, "expires_at": NOW + timedelta(hours=2),
        },
        "target": {
            "wave_id": "wave-1", "client_id": 3, "state": "approved",
            "consumed_deployment_id": None, "expires_at": NOW + timedelta(hours=2),
        },
        "release": {
            "release_id": RELEASE, "version": "1.3.45", "status": "stable",
            "installable": True, "update_allowed": True, "rollback_allowed": False,
        },
        "artifact": {
            "target_release_id": RELEASE, "bundle_sha256": SHA,
            "bundle_size": 10000, "release_approval_reference": "verified approval",
            "release_candidate_sha256": "b"*64, "source_commit": "c"*40,
        },
        "client_id": 3,
        "current_version": "1.3.43",
        "active_status_credential": True,
        "physical_acceptance": {
            "decision": "accepted", "release_id": RELEASE, "bundle_sha256": SHA,
            "client_id": 3, "actor_user_id": 2,
            "evidence": {"physical_pilot_verified": True, "recovery_verified": True},
        },
        "now": NOW,
    }


def test_default_closed_readiness_never_licenses_deployment():
    report = planning_readiness(
        release_id="clientflow-1.3.44-seq-1245", bundle_sha256=SHA,
        catalog={"latest_stable": "1.3.44", "default_install_version": "1.3.44",
                 "releases": [{"release_id": "clientflow-1.3.44-seq-1245", "version": "1.3.44",
                               "release_sequence": 1245, "status": "stable"}]},
        approval_bundle_sha256=SHA, control_revision=1,
        cutover_enabled=False, fleet_open=False, fresh_install_open=False,
        physical_acceptance=False,
    )
    assert report["deployment_authorized"] is False
    assert report["automatic_rollout_authorized"] is False
    assert report["ready_for_fleet"] is False
    assert report["ready_for_fresh_install"] is False
    assert report["checks"][0] == {"id": "stable_catalog_binding", "ready": True, "reason": None}
    assert all(check["ready"] is False for check in report["checks"][1:])


@pytest.mark.parametrize("changed", [
    {"bundle_sha256": "bad"}, {"release_id": "clientflow-1.3.45-seq-1246"},
    {"approval_bundle_sha256": "b"*64}, {"control_revision": 0},
])
def test_malformed_catalog_binding_fails_readiness(changed):
    kwargs = dict(release_id="clientflow-1.3.44-seq-1245", bundle_sha256=SHA,
                  catalog={"latest_stable": "1.3.44", "default_install_version": "1.3.44",
                           "releases": [{"release_id": "clientflow-1.3.44-seq-1245", "version": "1.3.44",
                                         "release_sequence": 1245, "status": "stable"}]},
                  approval_bundle_sha256=SHA, control_revision=1, cutover_enabled=False,
                  fleet_open=False, fresh_install_open=False, physical_acceptance=False)
    kwargs.update(changed)
    assert planning_readiness(**kwargs)["checks"][0]["ready"] is False


def test_promoted_1247_inert_readiness_reports_stable_1245_binding():
    from service1.clientflow_release_pilot_stage_1247 import load_staged_catalog_1247

    catalog = load_staged_catalog_1247()
    report = planning_readiness(
        release_id="clientflow-1.3.44-seq-1245", bundle_sha256=SHA,
        catalog=catalog, approval_bundle_sha256=SHA, control_revision=1,
        cutover_enabled=False, fleet_open=False, fresh_install_open=False,
        physical_acceptance=False, exact_update_only_pilot_catalog=True,
    )
    assert report["checks"][0] == {"id": "stable_catalog_binding", "ready": True, "reason": None}
    assert all(not check["ready"] for check in report["checks"][1:])
    assert report["deployment_authorized"] is False
    assert report["automatic_rollout_authorized"] is False
    assert report["ready_for_fleet"] is False
    assert report["ready_for_fresh_install"] is False
    # Merely passing a three-entry catalog without the checked pilot context
    # must not imply that it is the single stable/default catalog.
    assert planning_readiness(
        release_id="clientflow-1.3.44-seq-1245", bundle_sha256=SHA,
        catalog=catalog, approval_bundle_sha256=SHA, control_revision=1,
        cutover_enabled=False, fleet_open=False, fresh_install_open=False,
        physical_acceptance=False,
    )["checks"][0]["ready"] is False


@pytest.mark.parametrize("change", [
    lambda c: c["releases"][2].update(installable=True),
    lambda c: c["releases"][2].update(rollback_allowed=True),
    lambda c: c["releases"][2].update(update_allowed=False),
    lambda c: c["releases"][2].update(min_current_version="1.3.44"),
    lambda c: c["releases"][2].update(max_current_version="1.3.46"),
    lambda c: c["releases"][1].update(install_modes=["fresh_install"]),
    lambda c: c.update(catalog_sequence=1248),
    lambda c: c["releases"].append(dict(c["releases"][2])),
])
def test_promoted_1247_readiness_refuses_widened_or_drifted_pilots(change):
    from service1.clientflow_release_pilot_stage_1247 import load_staged_catalog_1247

    catalog = deepcopy(load_staged_catalog_1247())
    change(catalog)
    report = planning_readiness(
        release_id="clientflow-1.3.44-seq-1245", bundle_sha256=SHA,
        catalog=catalog, approval_bundle_sha256=SHA, control_revision=1,
        cutover_enabled=False, fleet_open=False, fresh_install_open=False,
        physical_acceptance=False, exact_update_only_pilot_catalog=True,
    )
    assert report["checks"][0]["ready"] is False
    assert report["deployment_authorized"] is False


def test_synthetic_future_prerequisites_are_not_automatic_deployment_grant():
    ok, reason = assess_future_db_wave(**_ready_wave())
    assert ok and reason == "preconditions_only_not_deployment_authority"


@pytest.mark.parametrize("path,value", [
    (("control", "cutover_enabled"), False),
    (("control", "fleet_open"), False),
    (("wave", "state"), "paused"),
    (("wave", "kind"), "pilot"),
    (("wave", "approved_by_user_id"), None),
    (("wave", "approved_at"), None),
    (("wave", "release_id"), "clientflow-1.3.44-seq-1245"),
    (("wave", "bundle_sha256"), "d"*64),
    (("wave", "source_version"), "1.3.42"),
    (("wave", "expires_at"), NOW),
    (("target", "state"), "consumed"),
    (("target", "consumed_deployment_id"), "deployment-1"),
    (("target", "client_id"), 4),
    (("target", "wave_id"), "wave-2"),
    (("target", "expires_at"), NOW - timedelta(seconds=1)),
    (("release", "version"), "1.3.43"),
    (("release", "rollback_allowed"), True),
    (("release", "status"), "supported"),
    (("artifact", "target_release_id"), "wrong"),
    (("artifact", "bundle_sha256"), "d"*64),
    (("artifact", "release_candidate_sha256"), "wrong"),
    (("artifact", "source_commit"), "wrong"),
    (("artifact", "bundle_size"), 0),
    (("physical_acceptance", "decision"), "rejected"),
    (("physical_acceptance", "release_id"), "clientflow-1.3.44-seq-1245"),
    (("physical_acceptance", "bundle_sha256"), "d"*64),
    (("physical_acceptance", "actor_user_id"), None),
    (("physical_acceptance", "evidence"), {}),
])
def test_future_wave_rejects_changed_or_drifted_preconditions(path, value):
    data = deepcopy(_ready_wave())
    data[path[0]][path[1]] = value
    allowed, why = assess_future_db_wave(**data)
    assert allowed is False, why


def test_future_wave_rejects_missing_physical_acceptance_and_stale_status():
    data = _ready_wave()
    data["physical_acceptance"] = True
    assert assess_future_db_wave(**data)[0] is False
    data = _ready_wave()
    data["active_status_credential"] = False
    assert assess_future_db_wave(**data)[0] is False
    data = _ready_wave()
    data["current_version"] = "1.3.45"
    assert assess_future_db_wave(**data)[0] is False


def test_old_route_remains_inert_and_no_new_live_deployment_path():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    source = (root / "backend/service1/routers/clientflow_release_administration.py").read_text()
    assert 'wave.state = "approved"' not in source
    assert 'target.state = "approved"' not in source
    assert "create_authorized_deployment(" not in source
    assert '"authorization_active": False' in source
    deploy = (root / "backend/service1/routers/clientflow_deployments.py").read_text()
    assert "require_pilot_1245" in deploy
    assert "require_stable_rollout" in deploy
    assert "assess_future_db_wave" not in deploy
