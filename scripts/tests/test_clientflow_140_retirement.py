"""Synthetic retirement evidence; no live Render access, writes or deletion."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta

from scripts import audit_clientflow_140_retirement as audit
from service1.clientflow_releases import load_catalog


def evidence():
    row = deepcopy(load_catalog()["releases"][-1])
    row.update(release_id=audit.BASELINE, revision=audit.BASELINE, version="1.4.0", client_version="1.4.0",
               release_sequence=1250, status="stable", installable=True, update_allowed=True,
               install_modes=["fresh_install","in_place_update"], min_current_version="1.3.47",
               max_current_version="1.3.47", rollback_allowed=False, requires_explicit_downgrade=False)
    catalog = {"manifest_schema":4, "channel":"canonical-release-catalog", "catalog_sequence":1250,
               "latest_stable":"1.4.0", "default_install_version":"1.4.0",
               "retention_policy":{"max_selectable_versions":1,"max_installable_versions":1,
                                   "keep_blocked_metadata":False}, "releases":[row]}
    now = datetime.now(timezone.utc)
    return dict(catalog=catalog, now=now,
                store={"protected_latest":[{"release_id":audit.BASELINE,"release_sequence":1250,
                       "sha256":"a"*64,"size_bytes":200},{"release_id":"clientflow-1.3.47-seq-1248",
                       "release_sequence":1248,"sha256":"b"*64,"size_bytes":100}],
                       "older_review_only":[],"invalid_artifacts":[]},
                control={"stable_release_id":audit.BASELINE,"stable_bundle_sha256":"a"*64,
                         "cutover_enabled":True,"fresh_install_open":False,"fleet_open":False},
                clients=[{"id":3,"status":"approved","agent_version":"1.4.0","observed_state":"online",
                          "active_status_credential_id":"synthetic","reported_at":now}],
                dependencies={key:0 for key in audit.DEPENDENCY_QUERIES}, physical_acceptance_verified=True)


def test_clear_snapshot_is_not_deletion_or_rollback_authority():
    values = evidence()
    before = deepcopy(values)
    result = audit.assess(**values)
    assert result["database_and_store_snapshot_clear"] is True
    assert result["potential_store_reclaim_bytes"] == 100
    assert result["old_artifacts_review_only"][0]["release_id"] == "clientflow-1.3.47-seq-1248"
    assert result["deletion_authorized"] is False
    assert result["rollback_authorized"] is False
    assert result["local_recovery_inventory_required"] is True
    assert values == before


def test_retirement_blocked_by_any_unverified_dependency():
    for key in audit.DEPENDENCY_QUERIES:
        values = evidence()
        values["dependencies"][key] = 1
        assert key in audit.assess(**values)["blockers"]
    values = evidence()
    values["control"]["fleet_open"] = True
    assert "baseline_control_not_bound_and_quiesced" in audit.assess(**values)["blockers"]
    values = evidence()
    values["physical_acceptance_verified"] = False
    assert "physical_acceptance_not_verified" in audit.assess(**values)["blockers"]
    for change in ({"agent_version":"1.3.47"},{"active_status_credential_id":None},
                   {"observed_state":"offline"},{"status":"pending"},
                   {"reported_at":datetime.now(timezone.utc)-timedelta(minutes=1)}):
        values = evidence()
        values["clients"][0].update(change)
        assert audit.assess(**values)["clients_not_confirmed"] == [3]
    values = evidence()
    values["clients"] = []
    assert "client_inventory_incomplete" in audit.assess(**values)["blockers"]
    values = evidence()
    values["catalog"] = deepcopy(load_catalog())
    values["catalog"]["catalog_sequence"] = 1248
    assert "active_catalog_not_1250_only" in audit.assess(**values)["blockers"]
