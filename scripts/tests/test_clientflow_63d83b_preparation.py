"""Viborg1 migration policy: test pure transformation and fail-closed boundaries."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prepare_viborg1", ROOT / "scripts/clientflow_63d83b_prepare_viborg1.py")
assert SPEC and SPEC.loader
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)


def test_config_migration_only_changes_approved_keys_and_is_idempotent():
    original = {"schema_version": 1, "capture_backend": "wayland_mutter", "fps": 17,
                "bitrate_kbit": 9000, "segment_seconds": 2, "continuous_wss": True,
                "playlist_size": 12, "extension": {"keep": True}}
    raw = json.dumps(original).encode()
    migrated = prep.migrated_config(raw)
    assert json.loads(migrated) == dict(original, segment_seconds=1, continuous_wss=False)
    assert prep.migrated_config(migrated) == migrated


@pytest.mark.parametrize("invalid", (b"[]", b'{"schema_version":2}', b'{"schema_version":1,"capture_backend":"other"}'))
def test_unknown_configuration_is_not_migrated(invalid):
    with pytest.raises(RuntimeError):
        prep.migrated_config(invalid)


def test_wrong_target_stops_before_pilot_or_config_work(monkeypatch, capsys):
    monkeypatch.setattr(prep, "target", lambda: prep.require(False, "WRONG_HOST"))
    monkeypatch.setattr(prep, "prepare", lambda: pytest.fail("mutated wrong client"))
    monkeypatch.setattr("sys.argv", ["prepare_viborg1", "prepare"])
    assert prep.main() == 2
    assert "WRONG_HOST" in capsys.readouterr().out


def test_preparation_does_not_change_config_until_both_rollbacks_pass(monkeypatch):
    raw = b'{"schema_version":1,"segment_seconds":2}'
    calls = []
    monkeypatch.setattr(prep, "state_stopped", lambda: None)
    monkeypatch.setattr(prep, "pilot_state", lambda: (True, True))
    monkeypatch.setattr(prep, "read_regular", lambda p: (raw, None))
    monkeypatch.setattr(prep, "backup_config", lambda p: p)
    monkeypatch.setattr(prep, "pinned", lambda *a: None)
    def run(*args, **kwargs):
        calls.append(args)
        return "63D83A_HLS_ROLLBACK=PASS" if str(prep.HLS / "rollback.py") in args else "FAIL"
    monkeypatch.setattr(prep, "run", run)
    monkeypatch.setattr(prep, "replace_config", lambda *a: pytest.fail("changed config after failed rollback"))
    with pytest.raises(RuntimeError, match="RDP_ROLLBACK_NOT_ATTESTED"):
        prep.prepare()
    assert len(calls) == 2
