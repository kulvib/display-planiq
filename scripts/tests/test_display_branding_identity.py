"""Guard the renamed product identity against legacy branding regressions."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def _tracked_paths() -> list[Path]:
    # Read the committed source rather than generated bundles, Python caches or
    # node_modules. Git is available on both CI and release-build checkouts.
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def test_no_previous_product_branding_in_any_tracked_source() -> None:
    old_tokens = (
        ("kultur" + "skole").encode("utf-8"),
        ("info" + "skaerm").encode("utf-8"),
        ("info" + "skærm").encode("utf-8"),
    )
    matches = []
    for path in _tracked_paths():
        if not path.is_file():
            continue
        data = path.read_bytes().lower()
        if any(token in data for token in old_tokens):
            matches.append(path.relative_to(ROOT).as_posix())
    assert not matches, "Legacy product branding is present in: " + ", ".join(matches)


def test_frontend_package_and_browser_metadata_match_display_brand() -> None:
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "frontend/public/site.webmanifest").read_text(encoding="utf-8"))
    assert package["name"] == "planiq-display-frontend"
    assert lock["name"] == lock["packages"][""]["name"] == package["name"]
    assert manifest["name"] == "PlanIQ Display"
    assert "PlanIQ Display" in (ROOT / "frontend/index.html").read_text(encoding="utf-8")


def test_release_transport_defaults_target_canonical_repo() -> None:
    workflow = (ROOT / ".github/workflows/runtime-input-transport.yml").read_text(encoding="utf-8")
    assert "https://github.com/kulvib/display-planiq/releases/download/" in workflow
    assert "expected_source_sha" in workflow
    assert "base_runtime_inputs_sha256" in workflow
