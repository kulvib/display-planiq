"""Execute the local cache parser without importing the command agent."""
import ast
from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_apt_parser_requires_recognizable_complete_output():
    source = (ROOT / "client/runtime/clientflow_runtime/system_agent.py").read_text()
    tree = ast.parse(source)
    selected = [node for node in tree.body if
                isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_UPGRADABLE" for t in node.targets)
                or isinstance(node, ast.FunctionDef) and node.name == "_parse_apt_upgradable"]
    env = {"re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<apt-parser>", "exec"), env)
    parse = env["_parse_apt_upgradable"]
    assert parse("Listing...\n") == 0
    assert parse("Listing...\nfoo/resolute-updates 2 amd64 [upgradable from: 1]\nbar/resolute-security 3 all [upgradable from: 2]\n") == 2
    for bad in ("", "error", "Listing...\nunexpected", "Listing...\nfoo/resolute 2 amd64"):
        with pytest.raises(ValueError):
            parse(bad)


def test_update_status_is_advisory_and_does_not_replace_authorization():
    agent = (ROOT / "client/runtime/clientflow_runtime/system_agent.py").read_text()
    gui = (ROOT / "client/libexec/local-gui").read_text()
    assert '[str(APT), "list", "--upgradable"]' in agent
    assert '"ubuntu_update_inventory": ubuntu' in agent
    assert '"Firmware update", "firmware_update"' in gui
    assert "UPDATE_STATUS_PATH" in gui


def test_ubuntu_cache_retries_unknown_and_refreshes_reboot_marker_without_apt(monkeypatch):
    from clientflow_runtime import system_agent as agent

    monotonic = [100.0]
    wall = [200_000.0]
    marker = [False]
    calls = []
    stamp = 190_000 * 10**9
    monkeypatch.setattr(agent.time, "monotonic", lambda: monotonic[0])
    monkeypatch.setattr(agent.time, "time", lambda: wall[0])
    monkeypatch.setattr(agent, "_apt_fingerprint", lambda: (stamp, None, 1))
    class Marker:
        def __init__(self, path):
            assert path == "/run/reboot-required"
        def exists(self):
            return marker[0]
    monkeypatch.setattr(agent, "Path", Marker)
    def snapshot():
        calls.append(True)
        return {"state": "unknown", "update_count": None} if len(calls) == 1 else {"state": "known", "update_count": 69}
    monkeypatch.setattr(agent, "_ubuntu_snapshot", snapshot)
    cache = agent.UbuntuStatusCache()
    assert cache.snapshot()["state"] == "unknown"
    monotonic[0] += 299
    assert cache.snapshot()["state"] == "unknown"
    monotonic[0] += 1
    assert cache.snapshot()["update_count"] == 69
    assert len(calls) == 2
    marker[0] = True
    assert cache.snapshot()["requires_reboot"] is True
    assert len(calls) == 2


def test_known_ubuntu_inventory_expires_at_index_age_boundary(monkeypatch):
    from clientflow_runtime import system_agent as agent

    monotonic = [1.0]
    wall = [300_000.0]
    stamp = (300_000 - agent.APT_INDEX_MAX_AGE_SECONDS + 1) * 10**9
    monkeypatch.setattr(agent.time, "monotonic", lambda: monotonic[0])
    monkeypatch.setattr(agent.time, "time", lambda: wall[0])
    monkeypatch.setattr(agent, "_apt_fingerprint", lambda: (stamp, None, 1))
    calls = []
    def snapshot():
        calls.append(True)
        return {"state": "known", "update_count": 69} if len(calls) == 1 else {"state": "stale", "update_count": None}
    monkeypatch.setattr(agent, "_ubuntu_snapshot", snapshot)
    cache = agent.UbuntuStatusCache()
    assert cache.snapshot()["update_count"] == 69
    wall[0] += 2
    monotonic[0] += 2
    assert cache.snapshot()["state"] == "stale"
    assert cache.snapshot()["update_count"] is None
    assert len(calls) == 2
