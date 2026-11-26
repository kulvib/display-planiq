"""Local inventory never grants deletion, including on incomplete evidence."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/release/lib"))
from clientflow_release.transaction import Layout, TransactionError, _manifest_digest, release_inventory

ACTIVE = "clientflow-1.4.0-seq-1250"
PREVIOUS = "clientflow-1.3.47-seq-1248"
OLDER = "clientflow-1.3.46-seq-1247"


def write(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(mode)


def setup(root):
    layout = Layout(root)
    layout.releases.mkdir(parents=True, mode=0o755)
    layout.state_root.mkdir(parents=True, mode=0o700)
    layout.lock_file.touch(mode=0o600)
    records = {}
    for release_id in (ACTIVE, PREVIOUS, OLDER):
        version, sequence = release_id.removeprefix("clientflow-").split("-seq-")
        manifest = {"release_id": release_id, "version": version, "release_sequence": int(sequence)}
        write(layout.releases / release_id / "release-manifest.json", manifest, 0o444)
        records[release_id] = {"version": version, "release_sequence": int(sequence), "manifest_sha256": _manifest_digest(manifest)}
    layout.active.symlink_to(layout.releases / ACTIVE)
    state = {"schema_version": 2, "highest_release_sequence": 1250,
             "active_release_id": ACTIVE, "previous_release_id": PREVIOUS,
             "staged_release_id": None, "activation_intent": None,
             "installed": records, "history": [], "rollback_reports": {}}
    write(layout.state_file, state)
    write(layout.path("/var/lib/clientflow/update-controller/state.json"),
          {"schema_version": 1, "phase": "idle", "deployment": None, "previous_release_id": None})
    return layout, state


def test_inventory_preserves_active_previous_and_journal(tmp_path):
    layout, state = setup(tmp_path)
    before = layout.state_file.read_bytes()
    result = release_inventory(layout)
    rows = {row["release_id"]: row for row in result["releases"]}
    assert result["blockers"] == []
    assert rows[ACTIVE]["classification"] == rows[PREVIOUS]["classification"] == "protected"
    assert rows[OLDER]["classification"] == "review_only"
    assert not result["deletion_authorized"] and not result["automatic_cleanup_enabled"]
    assert layout.state_file.read_bytes() == before
    assert layout.releases.joinpath(OLDER).is_dir()


def test_staged_and_unknown_entries_are_never_deletion_candidates(tmp_path):
    layout, state = setup(tmp_path)
    state["staged_release_id"] = OLDER
    write(layout.state_file, state)
    (layout.releases / "clientflow-1.3.45-seq-1246").symlink_to(layout.releases / ACTIVE)
    result = release_inventory(layout)
    assert "staged_release_present" in result["blockers"]
    assert "unverified_release_directory" in result["blockers"]
    rows = {row["release_id"]: row for row in result["releases"]}
    assert rows[OLDER]["classification"] == "protected"
    assert rows["clientflow-1.3.45-seq-1246"]["classification"] == "unverified"
    assert result["deletion_authorized"] is False


def test_missing_lock_is_not_created(tmp_path):
    layout, _ = setup(tmp_path)
    layout.lock_file.unlink()
    with pytest.raises(OSError):
        release_inventory(layout)
    assert not layout.lock_file.exists()
