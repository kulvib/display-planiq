"""63D-41 source-level Unix socket feasibility: negative tests, no RFB execution."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import clientflow_63d41_rfb_source_gate as gate


CONNECTIONS = """
void check_unix_sock(long usec) {
    rfbNewClient(screen, sock);
}
"""
RFBSERVER = """
if (setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)) < 0) {
    return NULL;
}
"""
SOCKETS = """
if (setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)) < 0) {
    return;
}
"""
OPTIONS = """
-unixsock path
May require libvncserver rfbserver.c changes after setsockopt().
"""


def fixture_sources(tmp_path: Path):
    x = tmp_path / "x11-src"
    l = tmp_path / "libvnc-src"
    contents = [
        (x / "debian/changelog", "x11vnc (0.9.17-2) resolute; urgency=medium\n"),
        (l / "debian/changelog",
         "libvncserver (0.9.15+dfsg-3ubuntu0.2) resolute; urgency=medium\n"),
        (x / "src/connections.c", CONNECTIONS),
        (x / "doc/OPTIONS.md", OPTIONS),
        (l / "src/libvncserver/rfbserver.c", RFBSERVER),
        (l / "src/libvncserver/sockets.c", SOCKETS),
    ]
    for path, body in contents:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return x, l


def test_inspection_proves_only_static_source_evidence(tmp_path):
    x, l = fixture_sources(tmp_path)
    result = gate.review(x, l)
    assert result["static_source_inventory_pass"] is True
    assert all(result["source_compatibility_observations"].values())
    assert result["ubuntu_source_versions"] == gate.EXPECTED_VERSIONS
    assert len(result["source_files"]) == 4
    for flag in ("unix_socket_runtime_proven", "tcp_listener_absence_proven",
                 "cve_status_independently_cleared", "root_supervisor_reviewed",
                 "producer_approved", "activation_permitted",
                 "physical_client_modified", "binary_executed"):
        assert result[flag] is False


@pytest.mark.parametrize("package", ["x11vnc", "libvncserver"])
def test_wrong_source_version_rejected(tmp_path, package):
    x, l = fixture_sources(tmp_path)
    target = x if package == "x11vnc" else l
    path = target / "debian/changelog"
    path.write_text(path.read_text().replace(
        gate.EXPECTED_VERSIONS[package], "unapproved",
    ))
    with pytest.raises(gate.SourceGateError, match="version mismatch"):
        gate.review(x, l)


@pytest.mark.parametrize("bad_relative", [
    "src/connections.c", "doc/OPTIONS.md",
])
def test_missing_source_file_rejected(tmp_path, bad_relative):
    x, l = fixture_sources(tmp_path)
    (x / bad_relative).unlink()
    with pytest.raises(OSError):
        gate.review(x, l)


def test_symlinked_source_file_rejected(tmp_path):
    x, l = fixture_sources(tmp_path)
    (x / "src/connections.c").unlink()
    (x / "src/connections.c").symlink_to(l / "src/libvncserver/rfbserver.c")
    with pytest.raises(gate.SourceGateError, match="Symlink"):
        gate.review(x, l)


@pytest.mark.parametrize("changed_path,text", [
    ("src/connections.c", "void check_unix_sock(void) {}"),
    ("doc/OPTIONS.md", "-unixsock path"),
])
def test_missing_source_caveat_fails_closed(tmp_path, changed_path, text):
    x, l = fixture_sources(tmp_path)
    (x / changed_path).write_text(text)
    with pytest.raises(gate.SourceGateError, match="caveat"):
        gate.review(x, l)


def test_missing_libvnc_tcp_nodelay_path_fails_closed(tmp_path):
    x, l = fixture_sources(tmp_path)
    (l / "src/libvncserver/rfbserver.c").write_text("no TCP_NODELAY")
    with pytest.raises(gate.SourceGateError, match="caveat"):
        gate.review(x, l)


def test_unauthorised_host_rejected():
    env = {"CI": "true", "GITHUB_ACTIONS": "true",
           "GITHUB_REPOSITORY": "kulvib/display-planiq"}
    release = 'ID=ubuntu\nVERSION_ID="26.04"\n'
    assert gate.authorized_ci(env, release, 1000)
    assert not gate.authorized_ci(env, release, 0)
    assert not gate.authorized_ci(env, release.replace("26.04", "24.04"), 1000)
    assert not gate.authorized_ci(dict(env, CI="false"), release, 1000)
    assert not gate.authorized_ci(dict(env, GITHUB_REPOSITORY="other/repo"), release, 1000)


def test_bad_source_root_rejected(tmp_path):
    x, l = fixture_sources(tmp_path)
    link = tmp_path / "x11-link"
    link.symlink_to(x, target_is_directory=True)
    with pytest.raises(gate.SourceGateError, match="source directory"):
        gate.review(link, l)


def test_source_root_cannot_be_swapped_for_random_path(tmp_path):
    x, l = fixture_sources(tmp_path)
    with pytest.raises((OSError, gate.SourceGateError)):
        gate.review(tmp_path / "nonexistent", l)


def test_source_file_size_guard(tmp_path):
    x, l = fixture_sources(tmp_path)
    (x / "doc/OPTIONS.md").write_bytes(b"x" * (gate.MAX_FILE + 1))
    with pytest.raises(gate.SourceGateError, match="oversized"):
        gate.review(x, l)
