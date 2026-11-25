"""Native RDP packaging and fail-closed release transition tests."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from clientflow_release import builder, transaction

SPEC = importlib.util.spec_from_file_location("native_rdp_entry", ROOT / "client/libexec/native-rdp/entrypoint.py")
assert SPEC and SPEC.loader
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


def test_actual_release_payload_contains_only_pinned_root_helpers(tmp_path):
    updater = tmp_path / "updater.pyz"
    updater.write_bytes(b"test")
    payload = tmp_path / "payload.tar"
    builder._create_payload(ROOT, payload, version="9.9.9", epoch=1700000000,
                            runtime_inputs=None, updater_pyz=updater)
    prefix = "clientflow-9.9.9/client-runtime/libexec/native-rdp/"
    with tarfile.open(payload) as tar:
        actual = {m.name.removeprefix(prefix + "scripts/") for m in tar.getmembers()
                  if m.isfile() and m.name.startswith(prefix + "scripts/")}
        assert actual == set(entry.PINS)
        assert set(builder.NATIVE_RDP_ROOT_SOURCES) == actual - {"__init__.py"}
        for name, expected in entry.PINS.items():
            member = tar.getmember(prefix + "scripts/" + name)
            assert member.uid == 0 and member.mode & 0o022 == 0
            assert hashlib.sha256(tar.extractfile(member).read()).hexdigest() == expected
        for name in (*transaction._NATIVE_RDP_SOCKET_UNITS, *transaction._NATIVE_RDP_TEMPLATES):
            text = tar.extractfile("clientflow-9.9.9/client-runtime/systemd/" + name).read().decode()
            if name.endswith("@.service"):
                assert "/opt/clientflow/active/client-runtime/libexec/native-rdp/entrypoint.py" in text
                assert "/usr/local/libexec/clientflow/native-rdp-pilot" not in text
            else:
                assert "Accept=yes" in text and "WantedBy=clientflow.target" in text


def test_generic_removal_preserves_physical_guard(tmp_path):
    layout = transaction.Layout(tmp_path)
    marker = layout.path(transaction._NATIVE_RDP_PHYSICAL_PATHS[0])
    marker.mkdir(parents=True)
    unit = layout.unit_root / "clientflow-63d29-rdp-guard.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("guard")
    with pytest.raises(transaction.TransactionError, match="preserve guard"):
        transaction._remove_managed_units(layout)
    assert unit.read_text() == "guard"


def test_quiesce_admission_then_agent_without_killing_templates(tmp_path, monkeypatch):
    layout = transaction.Layout(tmp_path)
    layout.unit_root.mkdir(parents=True)
    for name in (*transaction._NATIVE_RDP_SOCKET_UNITS, *transaction._NATIVE_RDP_TEMPLATES,
                 "clientflow-remote-desktop-agent.service"):
        (layout.unit_root / name).write_text("")
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "inactive\n" if "show" in cmd else "", "")
    monkeypatch.setattr(transaction, "_run", run)
    transaction._quiesce_native_rdp(layout)
    assert calls[0][-1] == "clientflow-rdp-lifecycle.socket"
    assert calls[1][-1] == "clientflow-remote-desktop-agent.service"
    assert not transaction._NATIVE_RDP_TEMPLATES.intersection(transaction._runtime_unit_names(layout))
    assert any("list-units" in command for command in calls)


def test_previous_pilot_blocks_swap_before_mutation(tmp_path, monkeypatch):
    layout = transaction.Layout(tmp_path)
    marker = layout.path(transaction._NATIVE_RDP_PHYSICAL_PATHS[0])
    marker.mkdir(parents=True)
    monkeypatch.setattr(transaction, "_run", lambda *a, **k: pytest.fail("unsafe mutation"))
    with pytest.raises(transaction.TransactionError, match="Previous RDP pilot"):
        transaction._quiesce_native_rdp(layout)
