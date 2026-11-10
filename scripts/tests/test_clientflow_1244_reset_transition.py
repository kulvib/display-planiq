"""A single pinned 1244 sixth-bundle bridge followed by explicit oldest-first cleanup."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import audit_clientflow_release_retention as audit
from scripts import clientflow_1244_transition_policy as policy
from scripts import prune_clientflow_release_retention as cleanup


@pytest.fixture(autouse=True)
def _historic_staged_publication_isolation(monkeypatch):
    historic = Path(__file__).resolve().parents[2] / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json"
    monkeypatch.setattr(policy, "CATALOG_PATH", historic)
    monkeypatch.setattr(cleanup, "CATALOG_PATH", historic)


def store(tmp_path: Path, monkeypatch, *, after=False):
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    for rid in (policy.EXPECTED_AFTER if after else policy.PREVIOUS_FIVE):
        (root / f"{rid}.tar").write_bytes(rid.encode())

    def fake_verified(path, *, require_deployable=True):
        assert require_deployable
        rid = path.stem
        size, sha = policy.EXPECTED_AFTER[rid]
        ver, seq = rid.removeprefix("clientflow-").split("-seq-")
        return (
            {"release_id": rid, "version": ver, "release_sequence": int(seq),
             "release_approval": {"reference": policy.APPROVAL_REFERENCE},
             "source": {"commit": policy.SOURCE_COMMIT}},
            None, size, sha, path.open("rb"),
        )

    monkeypatch.setattr(audit, "open_verified_bundle_structure", fake_verified)
    return root


def clean_env(monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    for name in ("CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
                 "CLIENTFLOW_1243_PILOT_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)


def request(root, **kwargs):
    return audit.plan_publication(
        root, release_id=policy.RELEASE_ID, size_bytes=policy.APPROVED_SIZE,
        sha256=policy.APPROVED_SHA256, **kwargs,
    )


def new_catalog(tmp_path: Path, monkeypatch):
    target = tmp_path / "catalog.json"
    catalog = {
        "catalog_sequence": 1244,
        "latest_stable": "1.3.43", "default_install_version": "1.3.43",
        "releases": [{"version": "1.3.43", "release_id": policy.RELEASE_ID,
                      "installable": True, "install_modes": ["fresh_install", "in_place_update"]}],
    }
    target.write_text(json.dumps(catalog))
    monkeypatch.setattr(cleanup, "CATALOG_PATH", target)
    return target


def test_pinned_sixth_admission_requires_explicit_flag(tmp_path, monkeypatch):
    root = store(tmp_path, monkeypatch)
    clean_env(monkeypatch)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(audit.StoreAuditError, match="three-release cap"):
        request(root)
    result = request(root, authorized_1244_reset=True)
    assert result["1244_reset_admission"] is True
    assert result["retention_target_unchanged"] == 3
    assert result["cleanup_required_after_1244"] is True
    assert result["automatic_deletion_enabled"] is False
    assert result["rollback_enabled"] is False
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_1244_requires_quiescence_and_exact_provenance(tmp_path, monkeypatch):
    root = store(tmp_path, monkeypatch)
    clean_env(monkeypatch)
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED")
    with pytest.raises(policy.ClientFlow1244ResetDenied, match="suspended"):
        request(root, authorized_1244_reset=True)
    clean_env(monkeypatch)
    monkeypatch.setenv("CLIENTFLOW_1243_PILOT_CLIENT_ID", "2")
    with pytest.raises(policy.ClientFlow1244ResetDenied, match="pilot"):
        request(root, authorized_1244_reset=True)
    clean_env(monkeypatch)
    with pytest.raises(policy.ClientFlow1244ResetDenied, match="exact approved"):
        audit.plan_publication(root, release_id=policy.RELEASE_ID, size_bytes=policy.APPROVED_SIZE,
                               sha256="0" * 64, authorized_1244_reset=True)
    with pytest.raises(audit.StoreAuditError, match="Only one pinned transition"):
        request(root, authorized_1244_reset=True, authorized_1243_transition=True)


@pytest.mark.parametrize("invalid", ["remove", "extra", "replace", "symlink", "wrong_catalog"])
def test_1244_bridge_fails_closed_on_modified_store_or_catalog(tmp_path, monkeypatch, invalid):
    root = store(tmp_path, monkeypatch)
    clean_env(monkeypatch)
    name = "clientflow-1.3.38-seq-1239.tar"
    if invalid == "remove":
        (root / name).unlink()
    elif invalid == "extra":
        (root / "clientflow-1.3.44-seq-1245.tar").write_bytes(b"not-approved")
    elif invalid == "replace":
        (root / name).rename(root / "clientflow-1.3.37-seq-1238.tar")
    elif invalid == "symlink":
        (root / name).unlink()
        (root / name).symlink_to(root / "clientflow-1.3.39-seq-1240.tar")
    else:
        t = tmp_path / "wrong.json"
        t.write_text('{"catalog_sequence":1244,"latest_stable":"1.3.43"}')
        monkeypatch.setattr(policy, "CATALOG_PATH", t)
    with pytest.raises((policy.ClientFlow1244ResetDenied, audit.StoreAuditError)):
        request(root, authorized_1244_reset=True)


def test_six_bundle_postflight_only_under_exact_pinned_flag(tmp_path, monkeypatch):
    root = store(tmp_path, monkeypatch, after=True)
    clean_env(monkeypatch)
    with pytest.raises(audit.StoreAuditError, match="cap exceeded"):
        audit.verify_publication(root, release_id=policy.RELEASE_ID,
                                 size_bytes=policy.APPROVED_SIZE, sha256=policy.APPROVED_SHA256)
    accepted = audit.verify_publication(
        root, release_id=policy.RELEASE_ID, size_bytes=policy.APPROVED_SIZE,
        sha256=policy.APPROVED_SHA256, authorized_1244_reset=True,
    )
    assert accepted["approved_count"] == 6
    assert accepted["within_approved_limit"] is False
    assert accepted["automatic_deletion_enabled"] is False


def test_1244_cleanup_blocked_until_catalog_promoted(tmp_path, monkeypatch):
    root = store(tmp_path, monkeypatch, after=True)
    clean_env(monkeypatch)
    with pytest.raises(cleanup.PruneDenied, match="1244-only"):
        cleanup.plan_cleanup(root)
    new_catalog(tmp_path, monkeypatch)
    plan = cleanup.plan_cleanup(root)
    assert plan["prune_candidate"]["release_id"] == "clientflow-1.3.38-seq-1239"
    assert plan["catalog_pinned_release_ids"] == [policy.RELEASE_ID]
    assert plan["catalog_pin_blocks_cleanup"] is False
    assert plan["approved_count_after"] == 5


def test_1244_cleanup_requires_staged_pause_after_catalog_promotion(tmp_path, monkeypatch):
    root = store(tmp_path, monkeypatch, after=True)
    new_catalog(tmp_path, monkeypatch)
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", raising=False)
    with pytest.raises(policy.ClientFlow1244ResetDenied, match="suspended"):
        cleanup.plan_cleanup(root)
    clean_env(monkeypatch)
    plan = cleanup.plan_cleanup(root)
    assert plan["prune_candidate"]["release_sequence"] == 1239
    assert plan["deleted"] is False
    assert len(list(root.iterdir())) == 6


def test_1244_admission_rejected_after_store_already_contains_1244(tmp_path, monkeypatch):
    root = store(tmp_path, monkeypatch, after=True)
    clean_env(monkeypatch)
    with pytest.raises(policy.ClientFlow1244ResetDenied, match="(?i)exact pinned"):
        request(root, authorized_1244_reset=True)


def test_1244_policy_is_bound_to_original_release_identity():
    assert policy.RELEASE_ID == "clientflow-1.3.43-seq-1244"
    assert policy.APPROVED_SHA256 == "d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b"
    assert policy.APPROVED_SIZE == 223610880
    assert policy.SOURCE_COMMIT == "7ead8cf250b7d9b7c0d1bff5b70f574e76c11f41"
    assert len(policy.PREVIOUS_FIVE) == 5


def test_preflight_does_not_mutate_store(tmp_path, monkeypatch, capsys):
    from scripts import preflight_clientflow_1244_reset_publication as preflight

    root = store(tmp_path, monkeypatch)
    clean_env(monkeypatch)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    assert preflight.main(["--artifact-dir", str(root)]) == 0
    output = capsys.readouterr().out
    assert "CLIENTFLOW_1244_PUBLICATION_PREFLIGHT=READ_ONLY_PASS" in output
    assert "STORE_CLEANUP=NOT_AUTHORIZED_HERE" in output
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_oldest_first_cleanup_can_reach_one_and_protect_last(tmp_path, monkeypatch):
    import os

    root = store(tmp_path, monkeypatch, after=True)
    clean_env(monkeypatch)
    new_catalog(tmp_path, monkeypatch)
    originals = dict(policy.EXPECTED_AFTER)

    def verified_sha(fd, **_kwargs):
        rid = Path(os.readlink(f"/proc/self/fd/{fd}")).stem
        assert rid in originals
        return originals[rid]

    monkeypatch.setattr(cleanup, "sha256_fd", verified_sha)
    removed = []
    while len(list(root.glob("*.tar"))) > 1:
        plan = cleanup.plan_cleanup(root)
        candidate = plan["prune_candidate"]
        result = cleanup.prune_one_oldest(
            root,
            expected_release_id=candidate["release_id"],
            expected_sha256=candidate["sha256"],
            confirm_prune=True,
            confirm_no_dependencies=True,
        )
        assert result["deleted"] is True
        removed.append(result["removed_release_id"])
        assert audit.inspect_store(root)["approved_count"] == len(originals) - len(removed)
    assert removed == list(policy.PREVIOUS_FIVE)
    assert [p.stem for p in root.glob("*.tar")] == [policy.RELEASE_ID]
    assert audit.inspect_store(root)["retention_ready"] is True
    with pytest.raises(cleanup.PruneDenied, match="sole approved"):
        cleanup.plan_cleanup(root)
