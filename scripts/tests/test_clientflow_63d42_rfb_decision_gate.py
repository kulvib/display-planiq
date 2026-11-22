"""63D-42: source byte pin, negative Unix socket controls and real AF_UNIX smoke."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import struct
import tempfile

import pytest

from scripts import clientflow_63d42_rfb_decision_gate as gate


HEADER = """
if (setsockopt(sock, IPPROTO_TCP, TCP_NODELAY,
        (char *)&one, sizeof(one)) < 0) {
    rfbLogPerror("setsockopt failed");
}
"""


def test_nonfatal_diagnostic_branch_is_not_a_runtime_approval():
    assert gate.classify_nodelay_branch(HEADER) == "logging_only_in_branch"


@pytest.mark.parametrize("mutation", [
    "rfbLogPerror(\"failed\"); return NULL;",
    "rfbLogPerror(\"failed\"); close(sock);",
    "rfbLogPerror(\"failed\"); rfbCloseSocket(sock);",
    "rfbLogPerror(\"failed\"); goto fail;",
    "rfbLogPerror(\"failed\"); abort();",
    "rfbLogPerror(\"failed\"); exit(1);",
])
def test_fatal_tcp_nodelay_branch_is_denied(mutation):
    bad = HEADER.replace('rfbLogPerror("setsockopt failed");', mutation)
    assert gate.classify_nodelay_branch(bad) == "fatal_or_control_transfer"


@pytest.mark.parametrize("bad", [
    "void foo(void) { return; }",
    HEADER + HEADER,
    HEADER.replace("IPPROTO_TCP", "SOL_SOCKET"),
    HEADER.replace("rfbLogPerror", "printf"),
    HEADER.replace("< 0", "== 0"),
    HEADER.replace("{\n", "{\n" + "x" * 3000),
])
def test_ambiguous_untrusted_tcp_nodelay_cannot_pass(bad):
    with pytest.raises(gate.DecisionError):
        gate.classify_nodelay_branch(bad)


def fake_previous(monkeypatch, rfbserver=HEADER):
    pins = {
        **gate.PINNED_SOURCE_SHA256,
        "lib_rfbserver": hashlib.sha256(rfbserver.encode()).hexdigest(),
    }
    monkeypatch.setattr(gate, "PINNED_SOURCE_SHA256", pins)
    monkeypatch.setattr(gate.previous, "review", lambda *a: {
        "static_source_inventory_pass": True,
        "source_files": {name: {"sha256": digest} for name, digest in pins.items()},
    })
    monkeypatch.setattr(gate.previous, "read_source", lambda *a: rfbserver)


def test_source_pin_still_cannot_approve_producer(monkeypatch, tmp_path):
    fake_previous(monkeypatch)
    result = gate.source_decision(tmp_path / "x", tmp_path / "l")
    assert result["ubuntu_source_pinned"] is True
    assert result["source_only_nonfatal_branch"] is True
    for key in (
        "other_socket_branches_verified", "real_unix_rfb_handshake_proven",
        "x11vnc_cve_2026_32853_cleared", "tigervnc_cve_2026_34352_cleared",
    ):
        assert result[key] is False


def test_any_changed_source_sha_fails_closed(monkeypatch, tmp_path):
    fake_previous(monkeypatch)
    monkeypatch.setattr(gate.previous, "review", lambda *a: {
        "static_source_inventory_pass": True,
        "source_files": {
            name: {"sha256": "0" * 64}
            for name in gate.PINNED_SOURCE_SHA256
        },
    })
    with pytest.raises(gate.DecisionError, match="changed"):
        gate.source_decision(tmp_path, tmp_path)


def test_read_between_source_and_decision_must_stay_same(monkeypatch, tmp_path):
    fake_previous(monkeypatch)
    monkeypatch.setattr(gate.previous, "read_source", lambda *a: HEADER + "/* mutated */")
    with pytest.raises(gate.DecisionError, match="read changed"):
        gate.source_decision(tmp_path, tmp_path)


def test_no_previous_positive_gate_means_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(gate.previous, "review",
                        lambda *a: {"static_source_inventory_pass": False})
    with pytest.raises(gate.DecisionError):
        gate.source_decision(tmp_path, tmp_path)


def test_af_unix_os_socket_smoke_is_not_an_rfb_producer():
    result = gate.local_unix_os_smoke()
    assert result["af_unix_probe_pass"] is True
    assert result["socket_mode"] == "0600"
    assert result["directory_mode"] == "0700"
    assert result["peer_uid_check"] is True
    assert result["bounded_local_frame_bytes"] == 16 * 1024
    assert result["max_future_supervisor_lease_seconds"] == 360
    for key in ("rfb_producer_executed", "real_rfb_handshake_proven",
                "producer_tcp_udp_absence_proven"):
        assert result[key] is False


def test_wrong_peer_uid_is_denied():
    peer = struct.pack("3i", 123, os.geteuid() + 1, 1)
    with pytest.raises(gate.DecisionError, match="peer UID"):
        gate.check_peer_uid(peer, os.geteuid())
    with pytest.raises(gate.DecisionError, match="shape"):
        gate.check_peer_uid(b"", os.geteuid())


def test_non_private_socket_mode_fails_closed():
    with tempfile.TemporaryDirectory(prefix="cf42-negative-") as root:
        directory = Path(root)
        os.chmod(directory, 0o700)
        path = directory / "rfb.sock"
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            os.chmod(path, 0o666)
            with pytest.raises(gate.DecisionError, match="mode"):
                gate.check_private_socket(directory, path, os.geteuid())
            os.chmod(path, 0o600)
            os.chmod(directory, 0o755)
            with pytest.raises(gate.DecisionError, match="mode"):
                gate.check_private_socket(directory, path, os.geteuid())


def test_socket_symlink_instead_of_socket_denied():
    with tempfile.TemporaryDirectory(prefix="cf42-negative-") as root:
        directory = Path(root)
        os.chmod(directory, 0o700)
        path = directory / "link.sock"
        path.symlink_to(directory / "missing.sock")
        with pytest.raises(gate.DecisionError):
            gate.check_private_socket(directory, path, os.geteuid())


def test_fail_closed_decision_never_enables_browser(monkeypatch, tmp_path):
    fake_previous(monkeypatch)
    result = gate.gate(tmp_path, tmp_path)
    assert result["evidence_pass"] is True
    for key in ("activation_permitted", "producer_approved",
                "browser_pixel_path_proven",
                "remote_desktop_input_latency_proven",
                "physical_client_modified"):
        assert result[key] is False


def test_fake_ci_host_does_not_pass():
    env = {
        "CI": "true", "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "kulvib/display-planiq",
    }
    release = 'ID=ubuntu\nVERSION_ID="26.04"\n'
    assert gate.previous.authorized_ci(env, release, 1000)
    assert not gate.previous.authorized_ci(dict(env, CI="false"), release, 1000)
    assert not gate.previous.authorized_ci(env, release, 0)
    assert not gate.previous.authorized_ci(
        env, 'ID=ubuntu\nVERSION_ID="24.04"\n', 1000,
    )
