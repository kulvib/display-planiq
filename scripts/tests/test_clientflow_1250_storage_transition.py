"""Exercise exact temporary storage admission without real release bytes."""
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import audit_clientflow_release_retention as audit
from scripts import clientflow_1250_storage_transition as policy


def snapshot(records):
    rows = sorted(
        [dict(release_id=key, size_bytes=value[0], sha256=value[1],
              release_sequence=int(key.rsplit("-", 1)[1]), version=key.split("-")[1])
         for key, value in records.items()],
        key=lambda row: row["release_sequence"], reverse=True,
    )
    return dict(approved_count=len(rows), invalid_artifacts=[], protected_latest=rows[:3],
                older_review_only=rows[3:], within_approved_limit=len(rows) <= 3,
                disk_available_bytes=640745472)


def plan():
    return audit.plan_publication(Path("/unused"), release_id=policy.RELEASE_ID,
                                  size_bytes=policy.SIZE, sha256=policy.SHA256,
                                  authorized_1250_baseline_storage=True)


def test_exact_transition_and_idempotent_postflight(monkeypatch):
    state = snapshot(policy.PREDECESSORS)
    monkeypatch.setattr(audit, "inspect_store", lambda *a, **k: state)
    result = plan()
    assert result["disposition"] == "ready_to_publish"
    assert result["retention_target_unchanged"] == 3
    assert result["automatic_deletion_enabled"] is False
    assert result["required_available_bytes"] == policy.SIZE + audit.RESERVED_FREE_BYTES
    with pytest.raises(audit.StoreAuditError, match="three-release cap"):
        audit.plan_publication(Path("/unused"), release_id=policy.RELEASE_ID,
                               size_bytes=policy.SIZE, sha256=policy.SHA256)
    state = snapshot(policy.FINAL)
    assert plan()["disposition"] == "already_published"
    assert audit.verify_publication(Path("/unused"), release_id=policy.RELEASE_ID,
                                    size_bytes=policy.SIZE, sha256=policy.SHA256,
                                    authorized_1250_baseline_storage=True)["approved_count"] == 5


@pytest.mark.parametrize("change", ["missing", "extra", "modified", "duplicate", "invalid", "disk"])
def test_changed_inventory_fails_closed(monkeypatch, change):
    state = deepcopy(snapshot(policy.PREDECESSORS))
    if change == "missing":
        state["protected_latest"].pop()
        state["approved_count"] -= 1
    elif change == "extra":
        state["older_review_only"].append(dict(release_id="clientflow-1.3.43-seq-1244",
            size_bytes=100, sha256="d"*64, release_sequence=1244, version="1.3.43"))
        state["approved_count"] += 1
    elif change == "modified":
        state["protected_latest"][0]["sha256"] = "0"*64
    elif change == "duplicate":
        state["protected_latest"][0] = dict(state["protected_latest"][1])
    elif change == "invalid":
        state["invalid_artifacts"] = ["bad"]
    elif change == "disk":
        state["disk_available_bytes"] = policy.SIZE + audit.RESERVED_FREE_BYTES - 1
    monkeypatch.setattr(audit, "inspect_store", lambda *a, **k: state)
    with pytest.raises(audit.StoreAuditError):
        plan()


@pytest.mark.parametrize("release,size,digest", [
    ("clientflow-1.4.1-seq-1251", policy.SIZE, policy.SHA256),
    (policy.RELEASE_ID, policy.SIZE+1, policy.SHA256),
    (policy.RELEASE_ID, policy.SIZE, "0"*64),
])
def test_no_other_bundle_or_combined_override(monkeypatch, release, size, digest):
    monkeypatch.setattr(audit, "inspect_store", lambda *a, **k: snapshot(policy.PREDECESSORS))
    with pytest.raises(audit.StoreAuditError):
        audit.plan_publication(Path("/unused"), release_id=release, size_bytes=size, sha256=digest,
                               authorized_1250_baseline_storage=True)
    with pytest.raises(audit.StoreAuditError, match="Only one"):
        audit.plan_publication(Path("/unused"), release_id=policy.RELEASE_ID,
                               size_bytes=policy.SIZE, sha256=policy.SHA256,
                               authorized_1250_baseline_storage=True, authorized_1248_viborg1_fourth=True)


def test_exact_provenance_and_approval_lock():
    import json
    from pathlib import Path
    approval = json.loads((Path(__file__).resolve().parents[2] /
                           "backend/service1/clientflow_pilot_1250_approval.json").read_text())
    assert (policy.RELEASE_ID, policy.SIZE, policy.SHA256, policy.SOURCE, policy.REFERENCE,
            policy.CANDIDATE, policy.INSTALLER) == (
        approval["release_id"], approval["approved_bundle_size"], approval["approved_bundle_sha256"],
        approval["source_commit"], approval["approval_reference"], approval["candidate_sha256"],
        approval["installer_sha256"])
    manifest = dict(release_id=policy.RELEASE_ID, release_approval=dict(
        reference=policy.REFERENCE, candidate_sha256=policy.CANDIDATE), source=dict(commit=policy.SOURCE))
    policy.require_provenance(manifest, policy.SIZE, policy.SHA256)
    for section, key in (("release_approval", "reference"), ("release_approval", "candidate_sha256"),
                         ("source", "commit")):
        wrong = deepcopy(manifest)
        wrong[section][key] = "wrong"
        with pytest.raises(ValueError):
            policy.require_provenance(wrong, policy.SIZE, policy.SHA256)
