#!/usr/bin/env python3
"""63D-41: static Ubuntu 26.04 RFB source compatibility review; no execution.

Inspects only a source tree unpacked from an APT signed-index source package
on a disposable GitHub runner. NEVER approves an RFB server from a source
string match; CVE status and native AF_UNIX behavior remain separately gated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

EXPECTED_VERSIONS = {
    "x11vnc": "0.9.17-2",
    "libvncserver": "0.9.15+dfsg-3ubuntu0.2",
}
SOURCES = {
    "x11_connections": ("x11vnc", "src/connections.c"),
    "x11_options": ("x11vnc", "doc/OPTIONS.md"),
    "lib_rfbserver": ("libvncserver", "src/libvncserver/rfbserver.c"),
    "lib_sockets": ("libvncserver", "src/libvncserver/sockets.c"),
}
MAX_FILE = 2 * 1024 * 1024


class SourceGateError(ValueError):
    """Invalid source package or unapproved environment; fail closed."""


def authorized_ci(env: dict[str, str], os_release: str, euid: int) -> bool:
    fields = {}
    for line in os_release.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value.strip().strip('"')
    return (
        euid != 0
        and env.get("CI") == "true"
        and env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_REPOSITORY") == "kulvib/display-planiq"
        and fields.get("ID") == "ubuntu"
        and fields.get("VERSION_ID") == "26.04"
    )


def read_source(root: Path, relative: str) -> str:
    """Reject symlink traversal and oversized/non-file sources."""
    if not root.is_dir() or root.is_symlink():
        raise SourceGateError("Untrusted extracted source directory")
    path = root
    for component in Path(relative).parts:
        if component in {".", ".."}:
            raise SourceGateError("Unsafe source component")
        path = path / component
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise SourceGateError("Symlink in inspected source path")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_FILE:
        raise SourceGateError("Missing or oversized source file")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise SourceGateError("Invalid UTF-8 source") from exc


def verify_source_version(root: Path, package: str) -> str:
    if package not in EXPECTED_VERSIONS:
        raise SourceGateError("Unexpected source package")
    contents = read_source(root, "debian/changelog")
    first_line = contents.splitlines()[0] if contents else ""
    match = re.fullmatch(
        r"([a-z0-9.+-]+) \(([^()]*)\) ([a-z0-9-]+); urgency=[a-z]+",
        first_line.strip(),
    )
    if (
        not match or match.group(1) != package
        or match.group(2) != EXPECTED_VERSIONS[package]
    ):
        raise SourceGateError("Ubuntu source package version mismatch")
    return match.group(2)


def review(x11_dir: Path, lib_dir: Path) -> dict:
    roots = {"x11vnc": x11_dir, "libvncserver": lib_dir}
    versions = {name: verify_source_version(root, name) for name, root in roots.items()}
    source_files = {}
    bodies = {}
    for label, (package, relative) in SOURCES.items():
        text = read_source(roots[package], relative)
        bodies[label] = text
        source_files[label] = {
            "path": relative,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "bytes": len(text.encode("utf-8")),
        }
    connections = bodies["x11_connections"]
    rfbserver = bodies["lib_rfbserver"]
    sockets = bodies["lib_sockets"]
    options = bodies["x11_options"]
    evidence = {
        "x11vnc_check_unix_sock_source": bool(re.search(
            r"\bcheck_unix_sock\s*\(", connections,
        )),
        "x11vnc_rfb_new_client_reference": bool(re.search(
            r"\brfbNewClient\s*\(", connections,
        )),
        "libvncserver_tcp_nodelay_path": bool(
            re.search(r"\bsetsockopt\s*\(", rfbserver)
            and "TCP_NODELAY" in rfbserver
        ),
        "libvncserver_sockets_tcp_nodelay_path": bool(
            re.search(r"\bsetsockopt\s*\(", sockets)
            and "TCP_NODELAY" in sockets
        ),
        "x11vnc_upstream_unixsock_warning": (
            "-unixsock" in options and "rfbserver.c" in options
            and "setsockopt" in options
        ),
    }
    # Missing expected source landmarks is a FAIL, not automatic approval.
    if not all(evidence.values()):
        raise SourceGateError("Expected source-level Unix socket caveat not verified")
    return {
        "schema": "63d41-rfb-source-compatibility-v1",
        "static_source_inventory_pass": True,
        "ubuntu_source_versions": versions,
        "source_files": source_files,
        "source_compatibility_observations": evidence,
        "unix_socket_runtime_proven": False,
        "tcp_listener_absence_proven": False,
        "cve_status_independently_cleared": False,
        "root_supervisor_reviewed": False,
        "producer_approved": False,
        "activation_permitted": False,
        "physical_client_modified": False,
        "binary_executed": False,
        "reason": (
            "STOP: no runtime proof of AF_UNIX compatibility, isolation, "
            "TCP absence or x11vnc CVE clearance"
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--x11-source", required=True, type=Path)
    p.add_argument("--libvnc-source", required=True, type=Path)
    args = p.parse_args()
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if not authorized_ci(dict(os.environ), release, os.geteuid()):
            raise SourceGateError("Only unprivileged Ubuntu 26.04 GitHub CI allowed")
        result = review(args.x11_source, args.libvnc_source)
    except (SourceGateError, OSError, ValueError) as exc:
        result = {
            "schema": "63d41-rfb-source-compatibility-v1",
            "static_source_inventory_pass": False,
            "producer_approved": False,
            "activation_permitted": False,
            "binary_executed": False,
            "physical_client_modified": False,
            "reason": "STOP: " + str(exc),
        }
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)
    return 0 if result["static_source_inventory_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
