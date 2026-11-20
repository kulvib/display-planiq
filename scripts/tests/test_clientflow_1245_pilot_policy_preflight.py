"""The stage check is read-only and must fail closed on altered authority."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clientflow_1245_pilot_policy_preflight import inspect  # noqa: E402

FILES = (
    "client/VERSION", "client/release/release-input.json", "client/release/rollback-trust.json",
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1246_pilot.stage.json",
    "backend/service1/clientflow_release_catalog_1247_pilot.stage.json",
    "backend/service1/clientflow_pilot_1247_approval.json",
    "backend/service1/clientflow_pilot_1246_approval.json",
    "backend/service1/clientflow_pilot_1245_approval.json",
    "backend/service1/clientflow_pilot_1245.py",
    "backend/service1/clientflow_stable_rollout.py",
    "backend/service1/routers/clientflow_deployments.py",
    "scripts/clientflow_1245_source_preflight.py",
)


def _fixture(tmp_path):
    dst = tmp_path / "repo"
    for name in FILES:
        path = dst / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path)
    return dst


def test_read_only_pilot_policy_with_two_environment_gates():
    result = inspect(ROOT)
    assert result["ready"], result
    assert len(result["checks"]) == 9
    assert result["approved"] is True
    assert result["deployed"] is False
    assert result["stable_promoted"] is True


def test_preflight_cannot_modify_any_files(tmp_path):
    dst = _fixture(tmp_path)
    before = {path.relative_to(dst): path.read_bytes() for path in dst.rglob("*") if path.is_file()}
    assert inspect(dst)["ready"]
    assert before == {path.relative_to(dst): path.read_bytes() for path in dst.rglob("*") if path.is_file()}


def test_preflight_fails_on_withdrawn_approval(tmp_path):
    dst = _fixture(tmp_path)
    p = dst / "backend/service1/clientflow_pilot_1245_approval.json"
    lock = json.loads(p.read_text())
    lock["approved"] = False
    p.write_text(json.dumps(lock))
    assert not inspect(dst)["ready"]
    assert not inspect(dst)["checks"]["exact_approval_but_separate_pilot_flags"]


def test_preflight_fails_on_wrong_candidate_sha(tmp_path):
    dst = _fixture(tmp_path)
    p = dst / "backend/service1/clientflow_pilot_1245_approval.json"
    lock = json.loads(p.read_text())
    lock["candidate_sha256"] = "0" * 64
    p.write_text(json.dumps(lock))
    assert not inspect(dst)["ready"]


def test_preflight_fails_on_catalog_promotion(tmp_path):
    dst = _fixture(tmp_path)
    p = dst / "backend/service1/clientflow_release_catalog.json"
    cat = json.loads(p.read_text())
    cat["latest_stable"] = cat["default_install_version"] = "1.3.43"
    p.write_text(json.dumps(cat))
    assert not inspect(dst)["ready"]
