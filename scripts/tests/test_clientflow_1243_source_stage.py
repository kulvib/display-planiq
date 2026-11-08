"""1243 identity staging is not publication, backend authority, or physical proof."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
from clientflow_1243_source_preflight import inspect_source  # noqa: E402

REQUIRED = (
    "client/VERSION",
    "client/release/release-input.json",
    "client/release/rollback-trust.json",
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_security_policy.json",
    "backend/service1/routers/clientflow_deployments.py",
    "backend/service1/clientflow_pilot_1243.py",
    "client/systemd/clientflow-update-controller.service",
    "client/release/lib/clientflow_release/transaction.py",
    "scripts/clientflow_1338_controller_bridge.sh",
    "scripts/clientflow_controller_sandbox_probe.sh",
    ".github/workflows/release-approve.yml",
    ".github/workflows/release-build.yml",
)


def fixture(tmp_path: Path) -> Path:
    target = tmp_path / "source"
    for name in REQUIRED:
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dst)
    return target


def json_at(repo: Path, name: str) -> dict:
    return json.loads((repo / name).read_text(encoding="utf-8"))


def test_source_stage_identity_and_no_new_backend_authority() -> None:
    actual = inspect_source(ROOT)
    assert actual["target"] == "clientflow-1.3.42-seq-1243"
    assert actual["source_stage_ready"] is True
    assert actual["phase"] == "source_stage_only"
    assert actual["publish_authorized"] is False
    assert actual["activation_authorized"] is False
    assert actual["pilot_enabled"] is False
    assert actual["manual_rollback_mode"] == "disabled"
    assert actual["requires_physical_pilot"] is True
    assert all(x["passed"] for x in actual["checks"])
    catalog = json_at(ROOT, "backend/service1/clientflow_release_catalog.json")
    assert catalog["catalog_sequence"] == 1242
    assert all(x["release_id"] != "clientflow-1.3.42-seq-1243" for x in catalog["releases"])
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert json_at(ROOT, "client/release/rollback-trust.json") == {"schema_version": 1, "enabled": False, "keys": []}


def test_exact_bad_source_version_or_sequence_deny_stage(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    (repo / "client/VERSION").write_text("1.3.41\n")
    assert not inspect_source(repo)["source_stage_ready"]
    (repo / "client/VERSION").write_text("1.3.42\n")
    release = json_at(repo, "client/release/release-input.json")
    release["release_sequence"] = 1242
    (repo / "client/release/release-input.json").write_text(json.dumps(release))
    assert not inspect_source(repo)["source_stage_ready"]


def test_unapproved_catalog_promotion_and_default_changes_deny_stage(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    catalog = json_at(repo, "backend/service1/clientflow_release_catalog.json")
    catalog["catalog_sequence"] = 1243
    (repo / "backend/service1/clientflow_release_catalog.json").write_text(json.dumps(catalog))
    assert not inspect_source(repo)["source_stage_ready"]
    catalog["catalog_sequence"] = 1242
    catalog["latest_stable"] = "1.3.42"
    (repo / "backend/service1/clientflow_release_catalog.json").write_text(json.dumps(catalog))
    assert not inspect_source(repo)["source_stage_ready"]
    catalog["latest_stable"] = "1.3.38"
    catalog["releases"].append(dict(catalog["releases"][-1], release_id="clientflow-1.3.42-seq-1243", release_sequence=1243))
    (repo / "backend/service1/clientflow_release_catalog.json").write_text(json.dumps(catalog))
    assert not inspect_source(repo)["source_stage_ready"]


def test_unauthorized_1243_pilot_guard_and_sandbox_regression_deny_stage(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    router = repo / "backend/service1/routers/clientflow_deployments.py"
    contents = router.read_text()
    router.write_text(contents.replace('if release.get("release_id") == "clientflow-1.3.42-seq-1243":',
                                       'if release.get("release_id") == "clientflow-1.3.43-seq-1244":'))
    assert not inspect_source(repo)["source_stage_ready"]
    router.write_text(contents)
    controller = repo / "client/systemd/clientflow-update-controller.service"
    contents = controller.read_text()
    controller.write_text(contents.replace("ProtectHome=tmpfs", "ProtectHome=yes"))
    assert not inspect_source(repo)["source_stage_ready"]


def test_public_trust_rollback_escalation_fails_closed(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    (repo / "client/release/rollback-trust.json").write_text(json.dumps({
        "schema_version": 1, "enabled": True, "keys": [],
    }))
    result = inspect_source(repo)
    assert not result["source_stage_ready"]
    assert result["publish_authorized"] is False
    assert result["activation_authorized"] is False


def test_preflight_is_read_only_and_failure_reports_no_secrets(tmp_path: Path) -> None:
    repo = fixture(tmp_path)
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert inspect_source(repo)["source_stage_ready"]
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert after == before
    (repo / "client/VERSION").write_text("1.3.41")
    result = inspect_source(repo)
    assert result["source_stage_ready"] is False
    assert "keys" not in str(result)
    assert result["pilot_enabled"] is False


def test_pilot_1243_cannot_be_ordered_before_publication() -> None:
    from service1.clientflow_releases import (
        ClientFlowCatalogError, load_catalog, resolve_fresh_install_release, resolve_release,
    )
    load_catalog.cache_clear()
    assert resolve_fresh_install_release()["release_id"] == "clientflow-1.3.38-seq-1239"
    with pytest.raises(ClientFlowCatalogError, match="findes ikke"):
        resolve_release("1.3.42")
    for implicit in ("latest", "stable", ""):
        with pytest.raises(ClientFlowCatalogError, match="konkret katalogversion"):
            resolve_release(implicit)


def test_source_stage_documented_physical_and_approval_gates() -> None:
    text = (ROOT / "CLIENTFLOW_1.3.42_1243_SOURCE_STAGE.md").read_text(encoding="utf-8")
    for token in (
        "STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published",
        "NOT catalog-promoted", "1.3.42", "1243", "Viborg2", "ID 2",
        "1.3.38", "1.3.41", "ProtectHome=tmpfs", "BindPaths=/home/clientflow-kiosk",
        "exact-source", "reproducible", "immutable", "Ubuntu 26.04",
        "Livestream", "Remote Desktop", "automatic rollback", "reboot", "Heidi1",
        "CLIENTFLOW_1243_PILOT_CLIENT_ID", "source commit SHA", "SHA-256",
    ):
        assert token in text, token


def test_1243_files_are_in_source_integrity_manifest() -> None:
    lines = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    paths = {line.split("  ", 1)[1] for line in lines if line.strip()}
    assert {
        "CLIENTFLOW_1.3.42_1243_SOURCE_STAGE.md",
        "scripts/clientflow_1243_source_preflight.py",
        "scripts/tests/test_clientflow_1243_source_stage.py",
    } <= paths
