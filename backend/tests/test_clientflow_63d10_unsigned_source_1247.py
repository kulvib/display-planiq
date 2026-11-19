"""63D-10: exact 1247 source build eligibility, no accidental release authority."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/clientflow_61b2g_release_source_gate.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("clientflow_63d10_source_gate", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def _fixture(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    manifest = ROOT / "SHA256SUMS.txt"
    for line in manifest.read_text().splitlines():
        if not line:
            continue
        _, path = line.split("  ", 1)
        out = target / path
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, out)
    shutil.copy2(manifest, target / "SHA256SUMS.txt")
    for extra in ("scripts/build_clientflow_release.py",):
        out = target / extra
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / extra, out)
    return target


def _update_manifest(repo: Path, name: str) -> None:
    file = repo / name
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    manifest = repo / "SHA256SUMS.txt"
    lines = manifest.read_text().splitlines()
    assert sum(line.endswith("  " + name) for line in lines) == 1
    lines = [digest + "  " + name if line.endswith("  " + name) else line for line in lines]
    manifest.write_text("\n".join(lines) + "\n")


def test_exact_source_is_build_eligible_but_never_authorized():
    assert (ROOT / "client/VERSION").read_text().strip() == "1.3.46"
    source = json.loads((ROOT / "client/release/release-input.json").read_text())
    assert source == {
        "schema_version": 1,
        "release_sequence": 1247,
        "minimum_ubuntu_lts": "26.04",
        "architecture": "amd64",
        "runtime_python": "3.13.14",
    }
    report = gate.inspect(ROOT)
    assert report["source_verified"], report["checks"]
    assert report["candidate_identity_advanced"] is True
    assert report["result"] == "READY_FOR_UNSIGNED_CANDIDATE_BUILD"
    for key in ("deployment_authorized", "release_approved", "signature_verified", "pilot_accepted", "fresh_install_concurrency_proven"):
        assert report[key] is False


def test_current_release_catalog_does_not_contain_1247():
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())
    assert catalog["catalog_sequence"] == 1246
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.44"
    assert [x["release_sequence"] for x in catalog["releases"]] == [1245, 1246]
    assert catalog["releases"][1]["release_id"] == "clientflow-1.3.45-seq-1246"
    assert catalog["releases"][1]["installable"] is False
    assert catalog["retention_policy"] == {
        "max_selectable_versions": 3,
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }


@pytest.mark.parametrize("version,seq", [
    ("1.3.45", 1246), ("1.3.46", 1246), ("1.3.45", 1247),
    ("1.3.47", 1248), ("1.3.44", 1245),
])
def test_only_exact_1247_pair_can_be_built(tmp_path, version: str, seq: int):
    root = _fixture(tmp_path)
    version_file = root / "client/VERSION"
    version_file.write_text(version + "\n")
    _update_manifest(root, "client/VERSION")
    release_input = root / "client/release/release-input.json"
    data = json.loads(release_input.read_text())
    data["release_sequence"] = seq
    release_input.write_text(json.dumps(data) + "\n")
    _update_manifest(root, "client/release/release-input.json")
    report = gate.inspect(root)
    assert report["source_verified"], report["checks"]
    assert report["candidate_identity_advanced"] is False
    assert report["deployment_authorized"] is False


@pytest.mark.parametrize("name,modify", [
    ("backend/service1/clientflow_release_catalog.json", lambda x: x.update(catalog_sequence=1247)),
    ("backend/service1/clientflow_release_catalog.json", lambda x: x.update(latest_stable="1.3.46")),
    ("backend/service1/clientflow_1245_fleet_acceptance.json", lambda x: x.update(physical_pilot_accepted=True)),
    ("backend/service1/clientflow_pilot_1245_approval.json", lambda x: x.update(approved=False)),
])
def test_tampered_catalog_or_approval_fails_closed_even_with_rehash(tmp_path, name, modify):
    root = _fixture(tmp_path)
    path = root / name
    obj = json.loads(path.read_text())
    modify(obj)
    path.write_text(json.dumps(obj) + "\n")
    _update_manifest(root, name)
    report = gate.inspect(root)
    assert report["checks"]["complete_sha256_manifest"]["pass"] is True
    assert report["checks"]["unchanged_approved_stable_catalog_and_disarmed_pilot"]["pass"] is False
    assert report["source_verified"] is False
