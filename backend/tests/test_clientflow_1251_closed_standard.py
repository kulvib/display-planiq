"""68M-A: the proposed 1251 selector is closed and requires exact evidence."""
from copy import deepcopy
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from service1 import clientflow_closed_standard_1251 as standard
from service1 import clientflow_pilot_1251 as pilot
from service1 import clientflow_releases as releases
from service1 import native_rdp_admission as admission
from service1.clientflow_fresh_install_maintenance import require_fresh_install_not_suspended
from service1.routers import clientflow_release_administration as administration
from scripts import clientflow_63d6_active_catalog_contract as source
from scripts.promote_clientflow_1251_closed_standard import transition_mode, RotationDenied

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def closed(monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    monkeypatch.setenv("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false")
    for flag in pilot.CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)


def control(*, bound=False):
    artifact = pilot.successor_snapshot() if bound else standard.baseline_snapshot()
    return dict(stable_release_id=artifact["target_release_id"], stable_bundle_sha256=artifact["bundle_sha256"],
                revision=3 if bound else 2, cutover_enabled=False, fleet_open=False, fresh_install_open=False)


def completed(artifact, *, previous, **changes):
    values = dict(artifact, id="fixture", client_id=3, state="succeeded", completed_at=object(),
                  allow_downgrade=False, observed_release_id=artifact["target_release_id"],
                  observed_release_sequence=artifact["target_release_sequence"],
                  observed_previous_release_id=previous)
    values.update(changes)
    return SimpleNamespace(**values)


def predecessor():
    return completed(standard.baseline_snapshot(), previous="clientflow-1.3.47-seq-1248")


def successor(**changes):
    return completed(pilot.successor_snapshot(), previous=pilot.BASELINE_ID, **changes)


def test_active_standard_is_exact_and_historical_catalog_remains_closed():
    catalog = standard.closed_standard_catalog()
    assert catalog["catalog_sequence"] == 1251
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.4.1"
    assert len(catalog["releases"]) == 1
    assert catalog["releases"][0]["min_current_version"] == catalog["releases"][0]["max_current_version"] == "1.4.0"
    assert catalog["releases"][0]["rollback_allowed"] is False
    assert releases.load_catalog() == catalog
    assert (ROOT / source.ACTIVE_PATH).read_bytes() == standard.STAGE_PATH.read_bytes()
    assert source.verified_mode(ROOT) == "closed_1251_standard"
    with pytest.raises(pilot.Pilot1251Denied):
        standard.validate_closed_standard_catalog(pilot.closed_baseline_catalog())
    standard.validate_closed_standard_catalog(catalog)
    for field, value in (("notes", []), ("rollback_allowed", True), ("min_current_version", "1.3.47"),
                         ("install_modes", ["in_place_update"]), ("installable", 1)):
        altered = deepcopy(catalog)
        altered["releases"][0][field] = value
        with pytest.raises(pilot.Pilot1251Denied):
            standard.validate_closed_standard_catalog(altered)


def test_closed_control_requires_exact_binding_and_flags(closed, monkeypatch):
    catalog = standard.closed_standard_catalog()
    assert standard.require_closed_standard_control(catalog, control(), allow_predecessor=True) == "pending"
    assert standard.require_closed_standard_control(catalog, control(bound=True)) == "bound"
    with pytest.raises(pilot.Pilot1251Denied):
        standard.require_closed_standard_control(catalog, control())
    for field, value in (("revision", 2), ("stable_release_id", pilot.BASELINE_ID),
                         ("stable_bundle_sha256", "0"*64), ("fleet_open", True),
                         ("cutover_enabled", True), ("fresh_install_open", True),
                         ("fleet_open", 0)):
        with pytest.raises(pilot.Pilot1251Denied):
            standard.require_closed_standard_control(catalog, {**control(bound=True), field: value},
                                                     allow_predecessor=True)
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED")
    with pytest.raises(pilot.Pilot1251Denied):
        standard.require_closed_standard_control(catalog, control(bound=True))


def test_exact_completed_chain_and_negative_evidence():
    standard.require_completed_successor(successor(), predecessor(), client_id=3)
    for field, value in (("state", "rolled_back"), ("state", "recovery_failed"),
                         ("completed_at", None), ("observed_release_sequence", 1250),
                         ("observed_previous_release_id", "clientflow-1.3.47-seq-1248"),
                         ("source_commit", "0"*40), ("allow_downgrade", True),
                         ("client_id", 4), ("bundle_sha256", "0"*64)):
        with pytest.raises(pilot.Pilot1251Denied):
            standard.require_completed_successor(successor(**{field:value}), predecessor(), client_id=3)
    with pytest.raises(pilot.Pilot1251Denied):
        standard.require_completed_successor(successor(), None, client_id=3)
    with pytest.raises(pilot.Pilot1251Denied):
        standard.require_completed_successor(successor(), predecessor(), client_id=4)


def test_loader_checks_exact_source_bytes_and_fresh_install_remains_closed(monkeypatch, tmp_path):
    with monkeypatch.context() as patch:
        patch.setattr(releases, "CATALOG_PATH", standard.STAGE_PATH)
        releases.load_catalog.cache_clear()
        try:
            assert releases.load_catalog() == standard.closed_standard_catalog()
            assert releases.resolve_release("1.4.1")["release_id"] == pilot.SUCCESSOR_ID
            with pytest.raises(releases.ClientFlowCatalogError):
                releases.resolve_release("1.4.0")
            patch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", raising=False)
            with pytest.raises(HTTPException, match="1.4 nyinstallation"):
                require_fresh_install_not_suspended()
            path = tmp_path / "altered.json"
            path.write_bytes(standard.STAGE_PATH.read_bytes() + b"\n")
            patch.setattr(releases, "CATALOG_PATH", path)
            releases.load_catalog.cache_clear()
            with pytest.raises(releases.ClientFlowCatalogError):
                releases.load_catalog()
        finally:
            releases.load_catalog.cache_clear()


def test_runtime_bridge_is_exact_and_does_not_open_fleet(closed, monkeypatch):
    catalog = standard.closed_standard_catalog()
    monkeypatch.setattr(admission, "canonical_successor_artifact", pilot.successor_snapshot)
    client = SimpleNamespace(id=3, name="Viborg1", ubuntu_version="26.04")
    session = SimpleNamespace(exec=lambda _: SimpleNamespace(all=lambda: [predecessor()]))
    for bound in (False, True):
        data = control(bound=bound)
        row = SimpleNamespace(model_dump=lambda: data)
        def check(device=client, version="1.4.1", latest=None):
            return admission._closed_standard_eligibility(session, client=device, catalog=catalog,
                control=row, latest=latest or successor(), version=version)
        assert check() == "physical_test_eligible"
        assert check(version="1.4.0") == "cutover_closed"
        assert check(device=SimpleNamespace(id=4, name="Other", ubuntu_version="26.04")) == "cutover_closed"
        with pytest.raises(pilot.Pilot1251Denied):
            check(latest=successor(state="recovery_failed"))


def test_admin_status_and_operator_transition_are_closed(closed, monkeypatch):
    catalog = standard.closed_standard_catalog()
    monkeypatch.setattr(administration, "_release_inventory", lambda _: {"available_clients": []})
    for bound in (False, True):
        data = control(bound=bound)
        session = SimpleNamespace(get=lambda *_: SimpleNamespace(model_dump=lambda: data, revision=data["revision"]))
        result = administration._closed_1251_status(session, catalog)
        assert result["stable_release_id"] == pilot.SUCCESSOR_ID
        assert result["closed_standard_transition_pending"] is not bound
        assert result["revision"] == (3 if bound else 2)
        for key in ("fleet_open", "fresh_install_open", "cutover_enabled", "rollback_available",
                    "standard_order_review_available", "successor_pilot_review_available", "authorization_active"):
            assert result[key] is False
        assert transition_mode(catalog, data, apply=True) == ("bound" if bound else "pending")
    assert transition_mode(pilot.closed_baseline_catalog(), control(), apply=False) == "staged"
    with pytest.raises(RotationDenied, match="ACTIVE_1251_CATALOG_REQUIRED"):
        transition_mode(pilot.closed_baseline_catalog(), control(), apply=True)


def test_source_gate_accepts_exact_1251_only_in_isolated_activation_fixture(tmp_path):
    paths = [source.STAGE_PATH, source.APPROVAL_PATH, source.STAGE_1247_PATH, source.APPROVAL_1247_PATH,
             source.STAGE_1248_PATH, source.APPROVAL_1248_PATH,
             "backend/service1/clientflow_release_catalog_1250_closed.stage.json",
             "backend/service1/clientflow_pilot_1250_approval.json",
             "backend/service1/clientflow_pilot_1251_approval.json",
             str(standard.STAGE_PATH.relative_to(ROOT))]
    for path in paths:
        dst = tmp_path / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, dst)
    active = tmp_path / source.ACTIVE_PATH
    shutil.copy2(standard.STAGE_PATH, active)
    assert source.verified_mode(tmp_path) == "closed_1251_standard"
    assert source.projected_stable_1245(tmp_path)["catalog_sequence"] == 1245
    active.write_bytes(active.read_bytes() + b"\n")
    with pytest.raises(source.ActiveCatalogDenied):
        source.verified_mode(tmp_path)
