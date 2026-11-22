#!/usr/bin/env python3
"""63D-42: pinned Ubuntu source decision and independent AF_UNIX OS smoke.

Executed only by unprivileged ephemeral Ubuntu 26.04 GitHub CI. Never
installs, builds, loads, or executes x11vnc/LibVNCServer/TigerVNC. The
AF_UNIX smoke exercises Python's OS socket only, not an RFB producer.
All output is evidence, explicitly NEVER permission to activate RFB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import tempfile

from scripts import clientflow_63d41_rfb_source_gate as previous

PINNED_SOURCE_SHA256 = {
    "lib_rfbserver": "b9de5db49422de2b4bde6c032db9432408cf39d710e4c52e48bd802fed4a2cf7",
    "lib_sockets": "29e69ea91f547819d1f04a239623e6444448a92b2b82478a9ddb807402ee62ce",
    "x11_connections": "9a2fb9cf704cc53a35abb04e7bf197d3ad6c497194035b9003130feb861f787e",
    "x11_options": "da9f799ee8025cc1867ca675e5df8a1e20ab091049cd3692858c4c8f536e46b9",
}
MAX_LOCAL_LEASE_SECONDS = 360
MAX_FRAME_BYTES = 16 * 1024
# Explicitly different from a real x11vnc RFB handshake.
SMOKE_PROBE = b"CF42-local-AF_UNIX-smoke-only"


class DecisionError(ValueError):
    """Fail-closed classification error; never includes input source content."""


def classify_nodelay_branch(source: str) -> str:
    """Classify the exact client-accept TCP_NODELAY failure branch, not flags.

    Do not infer runtime compatibility from a source-level nonfatal branch.
    Other paths (e.g. getpeername, rfbCheckFds, threading, CVEs) may fail.
    """
    pattern = r"\bif\s*\(\s*setsockopt\s*\(\s*sock\s*,\s*IPPROTO_TCP\s*,\s*TCP_NODELAY\b"
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        raise DecisionError("Expected single client TCP_NODELAY branch not found")
    marker = matches[0]
    begin = source.find("{", marker.end())
    if begin < 0 or begin - marker.start() > 450:
        raise DecisionError("Unbounded TCP_NODELAY error branch")
    header = source[marker.start():begin]
    if not re.search(r"\)\s*<\s*0\s*\)\s*$", header):
        raise DecisionError("TCP_NODELAY failure test not recognised")
    depth = 1
    end = begin + 1
    while end < len(source) and depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    if depth or end - begin > 2000:
        raise DecisionError("TCP_NODELAY failure branch not bounded")
    block = source[begin + 1:end - 1]
    if "rfbLogPerror" not in block:
        raise DecisionError("TCP_NODELAY failure diagnostics changed")
    if re.search(
        r"\b(?:return|goto|break|continue|abort|exit|_exit|"
        r"close|closesocket|rfbCloseSocket|shutdown)\b", block,
    ):
        return "fatal_or_control_transfer"
    return "logging_only_in_branch"


def source_decision(x11_source: Path, lib_source: Path) -> dict:
    previous_result = previous.review(x11_source, lib_source)
    if previous_result.get("static_source_inventory_pass") is not True:
        raise DecisionError("Prior source compatibility gate not passed")
    files = previous_result.get("source_files", {})
    if set(files) != set(PINNED_SOURCE_SHA256):
        raise DecisionError("Unexpected source evidence set")
    for label, expected in PINNED_SOURCE_SHA256.items():
        if files[label].get("sha256") != expected:
            raise DecisionError("Ubuntu source bytes changed; re-review required")
    rfbserver = previous.read_source(lib_source, "src/libvncserver/rfbserver.c")
    if hashlib.sha256(rfbserver.encode("utf-8")).hexdigest() != PINNED_SOURCE_SHA256["lib_rfbserver"]:
        raise DecisionError("RFB source read changed")
    classify = classify_nodelay_branch(rfbserver)
    if classify != "logging_only_in_branch":
        raise DecisionError("Client TCP_NODELAY branch aborts or returns")
    # Remaining risk is explicit even if the particular branch logs only.
    return {
        "ubuntu_source_pinned": True,
        "nodelay_client_failure_branch": classify,
        "source_only_nonfatal_branch": True,
        "other_socket_branches_verified": False,
        "real_unix_rfb_handshake_proven": False,
        "x11vnc_cve_2026_32853_cleared": False,
        "tigervnc_cve_2026_34352_cleared": False,
    }


def check_private_socket(directory: Path, path: Path, expected_uid: int) -> None:
    """No symlinks, no group/world permissions, exactly one local socket."""
    root = directory.lstat()
    entry = path.lstat()
    if (
        not stat.S_ISDIR(root.st_mode) or root.st_uid != expected_uid
        or stat.S_IMODE(root.st_mode) != 0o700
        or not stat.S_ISSOCK(entry.st_mode)
        or entry.st_uid != expected_uid or stat.S_IMODE(entry.st_mode) != 0o600
        or root.st_dev != entry.st_dev
    ):
        raise DecisionError("Private Unix socket owner, inode or mode invalid")


def check_peer_uid(credentials: bytes, expected_uid: int) -> None:
    if len(credentials) != struct.calcsize("3i"):
        raise DecisionError("Peer credential shape invalid")
    _pid, uid, _gid = struct.unpack("3i", credentials)
    if uid != expected_uid:
        raise DecisionError("Unexpected AF_UNIX peer UID")


def local_unix_os_smoke() -> dict:
    """Exercise real OS AF_UNIX isolation, no x11vnc, no TCP or UDP sockets."""
    if os.geteuid() <= 0 or not hasattr(socket, "SO_PEERCRED"):
        raise DecisionError("Unprivileged Linux SO_PEERCRED unavailable")
    uid = os.geteuid()
    with tempfile.TemporaryDirectory(prefix="cf42-") as tmp:
        directory = Path(tmp)
        os.chmod(directory, 0o700)
        path = directory / "rfb-probe.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.settimeout(2)
            listener.bind(str(path))
            os.chmod(path, 0o600)
            check_private_socket(directory, path, uid)
            listener.listen(1)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(path))
                with listener.accept()[0] as accepted:
                    accepted.settimeout(2)
                    check_peer_uid(
                        accepted.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")),
                        uid,
                    )
                    client.sendall(SMOKE_PROBE)
                    received = accepted.recv(MAX_FRAME_BYTES + 1)
                    if received != SMOKE_PROBE:
                        raise DecisionError("Local AF_UNIX message mismatch")
                    accepted.sendall(b"ACK")
                    if client.recv(4) != b"ACK":
                        raise DecisionError("Local AF_UNIX acknowledgement mismatch")
            check_private_socket(directory, path, uid)
    if directory.exists():
        raise DecisionError("Local AF_UNIX workspace did not clean up")
    return {
        "af_unix_probe_pass": True,
        "directory_mode": "0700",
        "socket_mode": "0600",
        "peer_uid_check": True,
        "bounded_local_frame_bytes": MAX_FRAME_BYTES,
        "max_future_supervisor_lease_seconds": MAX_LOCAL_LEASE_SECONDS,
        "rfb_producer_executed": False,
        "real_rfb_handshake_proven": False,
        "producer_tcp_udp_absence_proven": False,
    }


def gate(x11_source: Path, lib_source: Path) -> dict:
    decision = source_decision(x11_source, lib_source)
    socket_evidence = local_unix_os_smoke()
    return {
        "schema": "63d42-source-decision-and-unix-os-smoke-v1",
        "evidence_pass": True,
        "ubuntu_source": decision,
        "local_os_socket": socket_evidence,
        "activation_permitted": False,
        "producer_approved": False,
        "browser_pixel_path_proven": False,
        "remote_desktop_input_latency_proven": False,
        "physical_client_modified": False,
        "reason": (
            "STOP: unrelated Ubuntu CVE review, RFB runtime Unix-only proof, "
            "root watchdog and browser/physical acceptance are outstanding"
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--x11-source", type=Path, required=True)
    p.add_argument("--libvnc-source", type=Path, required=True)
    args = p.parse_args()
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if not previous.authorized_ci(dict(os.environ), release, os.geteuid()):
            raise DecisionError("Only unprivileged Ubuntu 26.04 GitHub CI permitted")
        output = gate(args.x11_source, args.libvnc_source)
    except (DecisionError, previous.SourceGateError, OSError) as exc:
        output = {
            "schema": "63d42-source-decision-and-unix-os-smoke-v1",
            "evidence_pass": False,
            "activation_permitted": False,
            "producer_approved": False,
            "physical_client_modified": False,
            "reason": "STOP: " + str(exc),
        }
    print(json.dumps(output, sort_keys=True, indent=2), flush=True)
    return 0 if output["evidence_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
