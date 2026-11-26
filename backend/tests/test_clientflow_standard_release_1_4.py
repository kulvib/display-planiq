"""Synthetic baseline: no live catalog, physical acceptance, or permissions changed."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from service1 import clientflow_releases as releases
from service1 import clientflow_standard_release as policy
from service1 import clientflow_stable_rollout as legacy
from service1 import clientflow_fresh_install_maintenance as fresh
from fastapi import HTTPException


def catalog():
    row = deepcopy(releases.load_catalog()["releases"][-1])
    row.update(
        release_id=policy.BASELINE_ID, revision=policy.BASELINE_ID,
        version=policy.BASELINE_VERSION, client_version=policy.BASELINE_VERSION,
        release_sequence=1250, status="stable", installable=True, update_allowed=True,
        install_modes=["fresh_install", "in_place_update"], min_current_version="1.3.47",
        max_current_version="1.3.47", rollback_allowed=False, requires_explicit_downgrade=False,
    )
    return {"manifest_schema":4, "channel":"canonical-release-catalog", "catalog_sequence":1250,
            "latest_stable":"1.4.0", "default_install_version":"1.4.0",
            "retention_policy":{"max_selectable_versions":1,"max_installable_versions":1,
                                "keep_blocked_metadata":False}, "releases":[row]}


def args():
    sha = "a" * 64
    now = datetime.now(timezone.utc)
    return {
        "catalog": catalog(), "expected_revision": 2, "expected_release_id": policy.BASELINE_ID,
        "expected_bundle_sha256": sha, "now": now,
        "control": {"revision":2,"stable_release_id":policy.BASELINE_ID,"stable_bundle_sha256":sha,
                    "cutover_enabled":True,"fleet_open":True},
        "artifact": {"target_release_id":policy.BASELINE_ID,"bundle_sha256":sha,"bundle_size":100,
                     "release_approval_reference":"test-only-approved-reference",
                     "release_candidate_sha256":"b"*64,"source_commit":"c"*40},
        "acceptance": {"decision":"accepted","release_id":policy.BASELINE_ID,"bundle_sha256":sha,
                       "client_id":3,"actor_user_id":2,"created_at":now,
                       "evidence":{"physical_pilot_verified":True,"recovery_verified":True,
                                   "pilot_client_id":3,"release_id":policy.BASELINE_ID,"bundle_sha256":sha,
                                   "tested_by_user_id":1,"observed_version":"1.4.0",
                                   "pilot_reference":"test-pilot-reference","recovery_reference":"test-recovery-reference"}},
    }


def test_baseline_requires_one_release_and_exact_compatibility():
    data = catalog()
    assert policy.validate_baseline_catalog(data)["release_id"] == policy.BASELINE_ID
    for field, value in (("rollback_allowed", True), ("requires_reboot", False),
                         ("max_current_version", "1.4.1"), ("installable", False)):
        changed = deepcopy(data)
        changed["releases"][0][field] = value
        with pytest.raises(policy.StandardReleaseDenied):
            policy.validate_baseline_catalog(changed)
    data["releases"].append(deepcopy(data["releases"][0]))
    with pytest.raises(policy.StandardReleaseDenied):
        policy.validate_baseline_catalog(data)


def test_cutover_requires_exact_physical_evidence_and_current_artifact():
    valid = args()
    policy.require_cutover_authority(**valid)
    for section, field, value in (
        ("control","cutover_enabled",False), ("control","fleet_open",False),
        ("control","revision",3), ("artifact","bundle_sha256","d"*64),
        ("artifact","release_candidate_sha256","bad"), ("artifact","bundle_size",0),
        ("acceptance","decision","rejected"), ("acceptance","bundle_sha256","f"*64),
    ):
        changed = deepcopy(valid)
        changed[section][field] = value
        with pytest.raises(policy.StandardReleaseDenied):
            policy.require_cutover_authority(**changed)
    for field,value in (("recovery_verified",False),("tested_by_user_id",2),("observed_version","1.3.47")):
        changed = deepcopy(valid)
        changed["acceptance"]["evidence"][field] = value
        with pytest.raises(policy.StandardReleaseDenied):
            policy.require_cutover_authority(**changed)
    changed = deepcopy(valid)
    changed["acceptance"] = None
    with pytest.raises(policy.StandardReleaseDenied):
        policy.require_cutover_authority(**changed)


def test_selection_sorted_explicit_unique_and_bounded():
    assert policy.validate_selection([(7,"1.3.47"),(3,"1.3.47")]) == [(3,"1.3.47"),(7,"1.3.47")]
    for invalid in ([],[(3,"1.3.47"),(3,"1.3.47")],[(True,"1.3.47")],
                    [(3,"1.4.0")],[(3,"1.3.46")],[(i,"1.3.47") for i in range(1,27)]):
        with pytest.raises(policy.StandardReleaseDenied):
            policy.validate_selection(invalid)


def test_candidate_does_not_open_legacy_or_fresh_install_gates(monkeypatch, tmp_path):
    data = catalog()
    with pytest.raises(legacy.ClientFlowStableRolloutDenied, match="databasebundne"):
        legacy.require_stable_rollout(client_id=3, current_version="1.3.47",
            release=data["releases"][0], catalog=data, reason="test-only",
            pre_first_activation_repair=False, confirm_downgrade=False)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(releases, "CATALOG_PATH", path)
    monkeypatch.setenv(fresh.FRESH_INSTALL_SUSPENDED_FLAG, "0")
    releases.load_catalog.cache_clear()
    try:
        assert releases.load_catalog()["catalog_sequence"] == 1250
        with pytest.raises(HTTPException) as exc:
            fresh.require_fresh_install_not_suspended()
        assert exc.value.status_code == 503
    finally:
        releases.load_catalog.cache_clear()
