"""Regression guards for the Oct-2026 certifi/Vite security remediation."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def test_certifi_security_floor_is_hash_locked_in_both_python_graphs():
    requirements = (ROOT / "backend/requirements.txt").read_text()
    assert "certifi==2026.10.19" in requirements.splitlines()
    for lock_path in ("backend/requirements.lock.txt", "requirements-ci.lock.txt"):
        content = (ROOT / lock_path).read_text()
        assert "certifi==2026.7.22" not in content
        assert "certifi==2026.10.19 \\" in content
        assert "--hash=sha256:035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae" in content
        assert "--hash=sha256:42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b" in content


def test_vite_security_patch_keeps_npm_tarball_integrity_and_no_allowlist_bypass():
    pkg = json.loads((ROOT / "frontend/package.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    assert pkg["devDependencies"]["vite"] == "8.1.6"
    assert lock["packages"][""]["devDependencies"]["vite"] == "8.1.6"
    vite = lock["packages"]["node_modules/vite"]
    assert vite["version"] == "8.1.6"
    assert vite["integrity"] == "sha512-aRAHIxx5SW5zc1sMqFwJU/t5qaFfXb5Hj0J7W0VXihu/X99+346tz6080tO1T1xVIJORX/b3zVTXGFqUXh35uw=="
    assert vite["resolved"] == "https://registry.npmjs.org/vite/-/vite-8.1.6.tgz"
    assert vite["dependencies"]["rolldown"] == "~1.1.5"
    assert vite["dependencies"]["postcss"] == "^8.5.17"
    assert lock["packages"]["node_modules/rolldown"]["version"] == "1.1.5"
    assert lock["packages"]["node_modules/postcss"]["version"] == "8.5.23"
    assert json.loads((ROOT / "frontend/dependency-audit-allowlist.json").read_text())["exceptions"] == []
