"""Source-only 1245 identity must never silently publish or enable an update."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clientflow_1245_source_preflight import inspect_source  # noqa: E402

REQUIRED = (
    "client/VERSION", "client/release/release-input.json",
    "client/release/rollback-trust.json",
    "client/release/runtime-platform-inputs.lock.json",
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1246_pilot.stage.json",
    "backend/service1/clientflow_pilot_1246_approval.json",
    "backend/service1/clientflow_release_catalog_1247_pilot.stage.json",
    "backend/service1/clientflow_pilot_1247_approval.json",
    "backend/service1/clientflow_release_catalog_1248_pilot.stage.json",
    "backend/service1/clientflow_pilot_1248_approval.json",
    "backend/service1/clientflow_release_catalog_1245_pilot.stage.json",
    "backend/service1/clientflow_release_catalog_1245_stable.stage.json",
    "scripts/tests/fixtures/clientflow_1244_pre_1245_pilot_catalog.json",
    "backend/service1/clientflow_release_security_policy.json",
    ".github/workflows/release-build.yml", ".github/workflows/release-approve.yml",
    "scripts/clientflow_1244_source_preflight.py",
    "scripts/tests/test_clientflow_1244_source_stage.py",
    "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json",
)


def fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for name in REQUIRED:
        destination = repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = "backend/service1/clientflow_release_catalog_1248_pilot.stage.json" if name.endswith("/clientflow_release_catalog.json") else name
        shutil.copy2(ROOT / source, destination)
    return repo


def test_exact_new_identity_staged_without_any_deployment_authority(tmp_path):
    result = inspect_source(fixture(tmp_path))
    assert result["source_stage_ready"], result["checks"]
    assert result["target"] == "clientflow-1.3.44-seq-1245"
    assert result["stage"] == "source_approved_single_stable_catalog_ready"
    assert result["approved"] is result["published"] is result["catalog_promoted"] is True
    for name in ("install_authorized", "in_place_update_authorized", "physical_pilot_complete"):
        assert result[name] is False


def test_staged_identity_is_now_exact_live_pilot_catalog():
    release = json.loads((ROOT / "client/release/release-input.json").read_text())
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog_1248_pilot.stage.json").read_text())
    assert release["release_sequence"] == 1252  # unsigned candidate
    assert catalog["catalog_sequence"] == 1248  # 1245 stable + 1247/1248 update-only
    assert len(catalog["releases"]) == 3
    assert catalog["releases"][1]["installable"] is False
    assert catalog["releases"][0]["install_modes"] == ["fresh_install", "in_place_update"]
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.44"


def test_staging_never_mutates_repository(tmp_path):
    repo = fixture(tmp_path)
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert inspect_source(repo)["source_stage_ready"]
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after


def test_mutations_to_version_catalog_security_and_rollback_fail_closed(tmp_path):
    repo = fixture(tmp_path)
    scenarios = {
        "client/VERSION": lambda _: "1.3.43\n",
        "client/release/release-input.json": lambda s: s.replace('"release_sequence": 1252', '"release_sequence": 1244'),
        "backend/service1/clientflow_release_catalog.json": lambda s: s.replace('"update_allowed": true', '"update_allowed": false'),
        "backend/service1/clientflow_release_security_policy.json": lambda s: s.replace('"minimum_safe_release_sequence": 1239', '"minimum_safe_release_sequence": 1200'),
        "client/release/rollback-trust.json": lambda s: s.replace('"enabled": false', '"enabled": true'),
    }
    for name, change in scenarios.items():
        path = repo / name
        original = path.read_text(encoding="utf-8")
        altered = change(original)
        assert altered != original, name
        path.write_text(altered, encoding="utf-8")
        result = inspect_source(repo)
        assert not result["source_stage_ready"], name
        path.write_text(original, encoding="utf-8")
        assert inspect_source(repo)["source_stage_ready"], name


def test_catalog_promotion_or_old_release_overwrite_is_rejected(tmp_path):
    repo = fixture(tmp_path)
    path = repo / "backend/service1/clientflow_release_catalog.json"
    baseline = json.loads(path.read_text(encoding="utf-8"))
    modified = json.loads(path.read_text(encoding="utf-8"))
    modified["catalog_sequence"] = 1249
    modified["latest_stable"] = modified["default_install_version"] = "1.3.44"
    modified["releases"][0]["release_id"] = "clientflow-1.3.44-seq-1245"
    modified["releases"][0]["version"] = "1.3.44"
    modified["releases"][0]["release_sequence"] = 1245
    path.write_text(json.dumps(modified), encoding="utf-8")
    assert not inspect_source(repo)["source_stage_ready"]
    path.write_text(json.dumps(baseline), encoding="utf-8")
    baseline["releases"][0]["notes"][1] = "replaced approved bundle with other bytes"
    path.write_text(json.dumps(baseline), encoding="utf-8")
    assert not inspect_source(repo)["source_stage_ready"]
