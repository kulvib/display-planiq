"""63D-37: no network and no service activation; AF_UNIX only."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import stat
import tempfile

import pytest

from client.runtime.clientflow_runtime import native_rfb_local_gate as gate

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture
def local_rfb(monkeypatch):
    # AF_UNIX path is limited to ~108 bytes on Linux. GitHub runner's
    # pytest tmp_path can exceed that even though production /run is short.
    with tempfile.TemporaryDirectory(prefix="cf-rfb37-", dir="/tmp") as scratch:
        root = Path(scratch) / "private"
        root.mkdir(mode=0o700)
        path = gate.socket_path(SESSION, runtime_root=root)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen(1)
        path.chmod(0o600)
        owner = os.getuid()
        if owner == 0:
            owner = 65534
            os.chown(root, owner, owner)
            os.chown(path, owner, owner)
            monkeypatch.setattr(gate.os, "geteuid", lambda: owner)
        try:
            yield root, path, server, owner
        finally:
            server.close()


def test_canonical_session_and_fixed_socket_leaf():
    assert gate.socket_path(SESSION) == (
        gate.RUNTIME_ROOT / ("rfb-" + SESSION + ".sock")
    )
    for bad in ("", "../etc/shadow", SESSION.upper(), OTHER.replace("-", ""), "not-uuid"):
        with pytest.raises(gate.NativeRfbLocalGateError):
            gate.socket_path(bad)
    with pytest.raises(gate.NativeRfbLocalGateError):
        gate.socket_path(SESSION, runtime_root=Path("relative"))
    with pytest.raises(gate.NativeRfbLocalGateError):
        gate.socket_path(SESSION, runtime_root=Path("/run/clientflow/../unsafe"))


def test_socket_permissions_and_inodes_must_be_exact(local_rfb):
    root, path, _, owner = local_rfb
    result = gate.inspect_socket(SESSION, runtime_root=root, expected_uid=owner)
    assert result.socket_inode == path.lstat().st_ino
    assert result.socket_device == root.lstat().st_dev
    gate.revalidate_socket(result)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_world_readable_or_group_writable_socket_rejected(local_rfb):
    root, path, _, owner = local_rfb
    for mode in (0o644, 0o660, 0o666, 0o400, 0o777):
        path.chmod(mode)
        with pytest.raises(gate.NativeRfbLocalGateError):
            gate.inspect_socket(SESSION, runtime_root=root, expected_uid=owner)
    path.chmod(0o600)
    for mode in (0o750, 0o755, 0o770, 0o777):
        root.chmod(mode)
        with pytest.raises(gate.NativeRfbLocalGateError):
            gate.inspect_socket(SESSION, runtime_root=root, expected_uid=owner)


def test_symlinked_directory_or_fake_regular_file_rejected(tmp_path, local_rfb):
    root, path, _, owner = local_rfb
    link = tmp_path / "redirect"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(gate.NativeRfbLocalGateError):
        gate.inspect_socket(SESSION, runtime_root=link, expected_uid=owner)
    path.unlink()
    path.write_bytes(b"fake RFB socket")
    path.chmod(0o600)
    with pytest.raises(gate.NativeRfbLocalGateError):
        gate.inspect_socket(SESSION, runtime_root=root, expected_uid=owner)


def test_wrong_user_root_and_stale_socket_fail_closed(local_rfb, monkeypatch):
    root, path, server, owner = local_rfb
    with pytest.raises(gate.NativeRfbLocalGateError):
        gate.inspect_socket(SESSION, runtime_root=root, expected_uid=owner+1)
    checked = gate.inspect_socket(SESSION, runtime_root=root, expected_uid=owner)
    server.close()
    path.unlink()
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        replacement.bind(str(path))
        path.chmod(0o600)
        with pytest.raises(gate.NativeRfbLocalGateError):
            gate.revalidate_socket(checked)
    finally:
        replacement.close()
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    with pytest.raises(gate.NativeRfbLocalGateError):
        gate.inspect_socket(SESSION, runtime_root=root, expected_uid=0)


def test_provider_unapproved_blocks_socket_open_without_side_effect(local_rfb):
    root, _, server, _ = local_rfb
    assert gate.PRODUCER_APPROVED is False
    async def run():
        with pytest.raises(gate.NativeRfbLocalGateError, match="security acceptance"):
            await gate.open_approved_socket(SESSION, runtime_root=root)
    asyncio.run(run())
    assert server.fileno() != -1


def test_only_approved_source_change_can_connect_to_private_unix_socket(local_rfb, monkeypatch):
    root, _, server, _ = local_rfb
    # Simulate a future reviewed source approval against an entirely local
    # test AF_UNIX socket; no host package, VNC daemon or GNOME involved.
    monkeypatch.setattr(gate, "PRODUCER_APPROVED", True)
    async def run():
        reader, writer = await gate.open_approved_socket(SESSION, runtime_root=root)
        assert isinstance(reader, asyncio.StreamReader)
        writer.close()
        await writer.wait_closed()
    asyncio.run(run())
    assert server.fileno() != -1


def test_no_external_ports_or_subprocess_in_local_gate():
    import inspect
    source = inspect.getsource(gate)
    assert "open_unix_connection" in source
    assert "open_connection(" not in source.replace("open_unix_connection(", "")
    assert "import subprocess" not in source
    assert "subprocess." not in source
    assert "os.system(" not in source
    assert "Popen(" not in source
    assert "PRODUCER_APPROVED = False" in source
