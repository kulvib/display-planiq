"""No broad release retention bypass: exact one-off 1243 inventory only."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import audit_clientflow_release_retention as audit
from scripts import clientflow_1243_transition_policy as policy


def _setup(tmp_path: Path, monkeypatch, *, after=False):
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    items = policy.VERIFIED_AFTER if after else policy.VERIFIED_BEFORE

    def fake_verified(path, *, require_deployable=True):
        assert require_deployable is True
        release_id = path.stem
        size, sha = policy.VERIFIED_AFTER[release_id]
        ver, seq = release_id.removeprefix("clientflow-").split("-seq-")
        return ({"release_id": release_id, "version": ver,
                 "release_sequence": int(seq),
                 "release_approval": {"reference": "approval"},
                 "source": {"commit": "a" * 40}},
                None, size, sha, path.open("rb"))

    for i, name in enumerate(items):
        (root / (name + ".tar")).write_bytes(f"approved source {i}".encode())
    monkeypatch.setattr(audit, "open_verified_bundle_structure", fake_verified)
    return root


def _publish(root, **kwargs):
    return audit.plan_publication(
        root,
        release_id=policy.TRANSITION_RELEASE_ID,
        size_bytes=policy.TRANSITION_APPROVED_SIZE,
        sha256=policy.TRANSITION_APPROVED_SHA256,
        **kwargs,
    )


def _post(root, **kwargs):
    return audit.verify_publication(
        root,
        release_id=policy.TRANSITION_RELEASE_ID,
        size_bytes=policy.TRANSITION_APPROVED_SIZE,
        sha256=policy.TRANSITION_APPROVED_SHA256,
        **kwargs,
    )


def test_default_three_cap_kept_even_for_correct_1243(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    with pytest.raises(audit.StoreAuditError, match="three-release cap"):
        _publish(root)
    assert len(list(root.iterdir())) == 4


def test_transition_requires_explicit_maintenance_and_disabled_pilots(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", raising=False)
    with pytest.raises(policy.ClientFlow1243TransitionDenied, match="suspended"):
        _publish(root, authorized_1243_transition=True)
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    monkeypatch.setenv("CLIENTFLOW_1243_PILOT_CLIENT_ID", "2")
    with pytest.raises(policy.ClientFlow1243TransitionDenied, match="pilot flags"):
        _publish(root, authorized_1243_transition=True)
    monkeypatch.delenv("CLIENTFLOW_1243_PILOT_CLIENT_ID")
    monkeypatch.setenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", "1")
    with pytest.raises(policy.ClientFlow1243TransitionDenied, match="pilot flags"):
        _publish(root, authorized_1243_transition=True)


def test_approved_four_to_five_only_then_postflight(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    for flag in ("CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
                 "CLIENTFLOW_1243_PILOT_CLIENT_ID"):
        monkeypatch.delenv(flag, raising=False)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    plan = _publish(root, authorized_1243_transition=True)
    assert plan["1243_transition"] is True
    assert plan["retention_target_unchanged"] == 3
    assert plan["cleanup_required_after_1243"] is True
    assert plan["protected_after_publication"] == [
        policy.TRANSITION_RELEASE_ID,
        "clientflow-1.3.41-seq-1242", "clientflow-1.3.40-seq-1241",
    ]
    assert set(plan["older_review_only"]) == {
        "clientflow-1.3.39-seq-1240", "clientflow-1.3.38-seq-1239",
    }
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    (root / (policy.TRANSITION_RELEASE_ID + ".tar")).write_bytes(b"approved transitional")
    with pytest.raises(audit.StoreAuditError, match="cap exceeded"):
        _post(root)
    verified = _post(root, authorized_1243_transition=True)
    assert verified["approved_count"] == 5
    assert verified["within_approved_limit"] is False
    assert verified["retention_target"] == 3
    assert verified["rollback_enabled"] is False


@pytest.mark.parametrize("failure", ["wrong_sha", "wrong_size", "wrong_release", "extra", "missing", "corrupt"])
def test_transition_rejects_modified_or_unexpected_inventory(tmp_path, monkeypatch, failure):
    root = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    for flag in ("CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
                 "CLIENTFLOW_1243_PILOT_CLIENT_ID"):
        monkeypatch.delenv(flag, raising=False)

    if failure == "extra":
        (root / (policy.TRANSITION_RELEASE_ID + ".tar")).write_bytes(b"another")
    elif failure == "missing":
        (root / "clientflow-1.3.39-seq-1240.tar").unlink()
    elif failure == "corrupt":
        (root / "clientflow-1.3.40-seq-1241.tar").unlink()
        (root / "clientflow-1.3.40-seq-1241.tar").symlink_to(root / "clientflow-1.3.38-seq-1239.tar")
    elif failure == "wrong_release":
        (root / "clientflow-1.3.41-seq-1242.tar").rename(root / "clientflow-1.3.37-seq-1238.tar")
    # Hash and size mutations on input are denied without touching store.
    before = {p.name for p in root.iterdir()}
    kw = {"authorized_1243_transition": True}
    if failure == "wrong_sha":
        with pytest.raises(policy.ClientFlow1243TransitionDenied, match="Only the exact"):
            audit.plan_publication(root, release_id=policy.TRANSITION_RELEASE_ID,
                                   size_bytes=policy.TRANSITION_APPROVED_SIZE,
                                   sha256="0" * 64, **kw)
    elif failure == "wrong_size":
        with pytest.raises(policy.ClientFlow1243TransitionDenied, match="Only the exact"):
            audit.plan_publication(root, release_id=policy.TRANSITION_RELEASE_ID,
                                   size_bytes=policy.TRANSITION_APPROVED_SIZE + 1,
                                   sha256=policy.TRANSITION_APPROVED_SHA256, **kw)
    else:
        with pytest.raises((policy.ClientFlow1243TransitionDenied, audit.StoreAuditError)):
            _publish(root, **kw)
    assert {p.name for p in root.iterdir()} == before


def test_transition_not_a_general_bypass_for_other_release(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    with pytest.raises(policy.ClientFlow1243TransitionDenied, match="Only the exact"):
        audit.plan_publication(root, release_id="clientflow-1.3.43-seq-1244",
                               size_bytes=policy.TRANSITION_APPROVED_SIZE,
                               sha256=policy.TRANSITION_APPROVED_SHA256,
                               authorized_1243_transition=True)


def test_transition_does_not_change_runtime_catalog_or_prune_policy(monkeypatch):
    import json
    from scripts import prune_clientflow_release_retention as prune

    historic_catalog = Path(__file__).resolve().parents[2] / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json"
    monkeypatch.setattr(prune, "CATALOG_PATH", historic_catalog)
    catalog = json.loads(historic_catalog.read_text())
    assert catalog["latest_stable"] == "1.3.38"
    assert catalog["default_install_version"] == "1.3.38"
    assert catalog["catalog_sequence"] == 1243
    assert len([row for row in catalog["releases"] if row["version"] == "1.3.42"]) == 1
    assert catalog["releases"][-1]["install_modes"] == ["in_place_update"]
    assert catalog["releases"][-1]["installable"] is False
    assert catalog["releases"][-1]["rollback_allowed"] is False
    assert audit.KEEP_LATEST_APPROVED == 3
    assert policy.TRANSITION_RELEASE_ID not in prune._catalog_pinned_release_ids()
    assert "clientflow-1.3.38-seq-1239" in prune._catalog_pinned_release_ids()
