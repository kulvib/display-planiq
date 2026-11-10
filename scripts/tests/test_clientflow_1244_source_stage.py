"""1244 is a staged new identity, not a clandestine approval or rollout."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clientflow_1244_source_preflight import inspect_source  # noqa: E402

REQUIRED = (
    "client/VERSION", "client/release/release-input.json",
    "client/release/rollback-trust.json",
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_releases.py",
    "client/systemd/clientflow-system-broker.service",
    "client/systemd/clientflow-platform-prepare.service",
    "client/systemd/clientflow-system-agent.service",
    ".github/workflows/release-build.yml",
    ".github/workflows/release-approve.yml",
)


def fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for relative in REQUIRED:
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    shutil.copy2(
        ROOT / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json",
        repo / "backend/service1/clientflow_release_catalog.json",
    )
    return repo


def test_exact_1244_source_without_approval(tmp_path):
    # A source-stage check must fail after production catalog promotion.
    assert inspect_source(ROOT)["source_stage_ready"] is False
    value = inspect_source(fixture(tmp_path))
    assert value["source_stage_ready"] is True, value["checks"]
    assert value["target"] == "clientflow-1.3.43-seq-1244"
    assert value["stage"] == "source_stage_only"
    for flag in ("published", "approved", "catalog_promoted", "install_authorized", "cleanup_authorized"):
        assert value[flag] is False
    assert value["requires_physical_fresh_install"] is True
    assert all(check["passed"] for check in value["checks"])


def test_historical_source_stage_does_not_promote_catalog_or_default():
    catalog = json.loads((ROOT / "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json").read_text())
    assert catalog["catalog_sequence"] == 1243
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert "1.3.43" not in [r["version"] for r in catalog["releases"]]
    assert "clientflow-1.3.43-seq-1244" not in [r["release_id"] for r in catalog["releases"]]


def test_malformed_identity_platform_or_premature_promotion_rejected(tmp_path):
    repo = fixture(tmp_path)
    p = repo / "client/VERSION"
    p.write_text("1.3.42\n")
    assert not inspect_source(repo)["source_stage_ready"]
    p.write_text("1.3.43\n")
    identity = repo / "client/release/release-input.json"
    obj = json.loads(identity.read_text())
    obj["release_sequence"] = 1243
    identity.write_text(json.dumps(obj))
    assert not inspect_source(repo)["source_stage_ready"]
    shutil.copy2(ROOT / "client/release/release-input.json", identity)
    c = repo / "backend/service1/clientflow_release_catalog.json"
    obj = json.loads(c.read_text())
    obj["catalog_sequence"] = 1244
    c.write_text(json.dumps(obj))
    assert not inspect_source(repo)["source_stage_ready"]


def test_security_and_three_release_guard_regressions_rejected(tmp_path):
    repo = fixture(tmp_path)
    trust = repo / "client/release/rollback-trust.json"
    trust.write_text('{"schema_version":1,"enabled":true,"keys":[]}')
    assert not inspect_source(repo)["source_stage_ready"]
    shutil.copy2(ROOT / "client/release/rollback-trust.json", trust)
    broker = repo / "client/systemd/clientflow-system-broker.service"
    original = broker.read_text()
    broker.write_text(original.replace("SystemCallFilter=~@module", "SystemCallFilter=~@mount"))
    assert not inspect_source(repo)["source_stage_ready"]
    shutil.copy2(ROOT / "client/systemd/clientflow-system-broker.service", broker)
    resolver = repo / "backend/service1/clientflow_releases.py"
    resolver.write_text(resolver.read_text().replace('if data["catalog_sequence"] >= 1244:',
                                                    'if data["catalog_sequence"] >= 1245:'))
    assert not inspect_source(repo)["source_stage_ready"]


def test_preflight_never_mutates_source(tmp_path):
    repo = fixture(tmp_path)
    before = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert inspect_source(repo)["source_stage_ready"]
    after = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after


def test_documented_gates_and_checksum_manifest():
    doc = (ROOT / "CLIENTFLOW_1.3.43_1244_SOURCE_STAGE_AND_THREE_RELEASE_POLICY.md").read_text()
    for token in (
        "STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published",
        "NOT catalog-promoted", "1.3.43", "1244", "Ubuntu 26.04", "Viborg2",
        "Heidi1", "dracut", "tre-release", "rollback", "SHA-256",
        "recovery", "fresh-install", "CI", "Smoke", "manual",
    ):
        assert token.lower() in doc.lower(), token
    manifest = (ROOT / "SHA256SUMS.txt").read_text()
    for target in (
        "CLIENTFLOW_1.3.43_1244_SOURCE_STAGE_AND_THREE_RELEASE_POLICY.md",
        "scripts/clientflow_1244_source_preflight.py",
        "scripts/tests/test_clientflow_1244_source_stage.py",
    ):
        assert target in manifest
