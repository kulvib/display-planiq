"""Regression: existing exact approved asset may be renamed, never replaced."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_clientflow_github_archive_metadata import (  # noqa: E402
    GithubArchiveMismatch,
    verify_release,
)

TAG = "clientflow-1.3.42-1243-approved-transport"
NAME = "clientflow-approved-1.3.42-1243.tar"
SHA = "ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914"
SOURCE = "b870cf8c3fa90286c6b4dccaae593eb8a0d57565"
SIZE = 223610880


def release(name: str = "clientflow-approved.tar") -> dict:
    return {
        "tag_name": TAG,
        "target_commitish": SOURCE,
        "draft": False,
        "prerelease": True,
        "assets": [{
            "id": 724299785,
            "name": name,
            "size": SIZE,
            "digest": "sha256:" + SHA,
            "state": "uploaded",
        }],
    }


def checked(data: dict, *, allow_legacy: bool = False) -> dict:
    return verify_release(
        data, expected_tag=TAG, expected_asset_name=NAME,
        expected_source_sha=SOURCE, expected_sha256=SHA, expected_size=SIZE,
        allow_legacy_handoff_name=allow_legacy,
    )


def test_actual_failed_1243_release_is_safe_metadata_only_rename() -> None:
    assert checked(release(), allow_legacy=True) == {
        "asset_id": 724299785, "needs_rename": True, "verified": True,
    }


def test_original_basename_denied_outside_specific_recovery() -> None:
    with pytest.raises(GithubArchiveMismatch, match="filename"):
        checked(release())


def test_correct_name_is_idempotent_in_fresh_and_recovery_paths() -> None:
    for allow in (False, True):
        assert checked(release(NAME), allow_legacy=allow)["needs_rename"] is False


@pytest.mark.parametrize("changes,match", [
    ({"tag_name": "clientflow-1.3.41-1242-approved-transport"}, "tag"),
    ({"target_commitish": "f" * 40}, "commit"),
    ({"prerelease": False}, "prerelease"),
    ({"draft": True}, "draft"),
    ({"assets": []}, "exactly one"),
    ({"assets": [release()["assets"][0]] * 2}, "exactly one"),
])
def test_foreign_release_denied(changes, match) -> None:
    data = release()
    data.update(changes)
    with pytest.raises(GithubArchiveMismatch, match=match):
        checked(data, allow_legacy=True)


@pytest.mark.parametrize("field,value,match", [
    ("id", 0, "ID"),
    ("name", "not-an-approved-tar.tar", "filename"),
    ("size", SIZE + 1, "size"),
    ("digest", "sha256:" + "a" * 64, "digest"),
    ("digest", None, "digest"),
    ("state", "starter", "upload"),
])
def test_wrong_asset_denied(field, value, match) -> None:
    data = release()
    data["assets"][0][field] = value
    with pytest.raises(GithubArchiveMismatch, match=match):
        checked(data, allow_legacy=True)


def test_expected_identity_cannot_be_made_up() -> None:
    with pytest.raises(GithubArchiveMismatch, match="does not match tag"):
        verify_release(release(), expected_tag=TAG, expected_asset_name="clientflow-approved.tar",
                       expected_source_sha=SOURCE, expected_sha256=SHA, expected_size=SIZE,
                       allow_legacy_handoff_name=True)


def test_workflow_preserves_both_source_verification_and_no_overwrite() -> None:
    path = ROOT / ".github/workflows/release-archive-approved.yml"
    wf = path.read_text(encoding="utf-8")
    assert "verify_clientflow_approved_release_asset.py" in wf
    assert "--allow-legacy-handoff-name" in wf
    assert "--method PATCH" in wf
    assert "verify_clientflow_github_archive_metadata.py" in wf
    assert "actions: read" in wf and "contents: write" in wf
    assert '"$ASSET_PATH#$ASSET_NAME"' not in wf
    assert '"$RUNNER_TEMP/archive-asset/$ASSET_NAME"' in wf
    assert "--target \"$SOURCE_SHA\"" in wf
    assert "--prerelease" in wf
    assert 'steps.archive_state.outputs.exists == \'false\'' in wf
    assert 'steps.archive_state.outputs.exists == \'true\'' in wf
    assert "APPROVED_GITHUB_RELEASE_ARCHIVE=PASS" in wf
    assert "publish_clientflow_release" not in wf
    assert "CLIENTFLOW_1243_PILOT_CLIENT_ID" not in wf
