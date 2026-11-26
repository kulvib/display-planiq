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
