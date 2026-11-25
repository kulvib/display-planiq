"""Test the actual create-only tmpfiles rule in an isolated fake root."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_release_config_defaults_and_create_only_installation(tmp_path):
    source = ROOT / "client/config-examples/livestream.json"
    defaults = json.loads(source.read_text())
    assert defaults["schema_version"] == 1
    assert defaults["capture_backend"] == "wayland_mutter"
    assert defaults["segment_seconds"] == 1
    assert defaults["continuous_wss"] is False
    rules = (ROOT / "client/tmpfiles.d/clientflow.conf").read_text().splitlines()
    rule = next(line for line in rules if line.startswith("C /etc/clientflow/livestream.json "))
    assert rule == ("C /etc/clientflow/livestream.json 0640 root root - "
                    "/opt/clientflow/active/client-runtime/config-examples/livestream.json")
    command = shutil.which("systemd-tmpfiles")
    if command is None:
        pytest.skip("systemd-tmpfiles unavailable on this runner")
    config = tmp_path / "etc/clientflow/livestream.json"
    config.parent.mkdir(parents=True)
    active = tmp_path / "opt/clientflow/active/client-runtime/config-examples/livestream.json"
    active.parent.mkdir(parents=True)
    active.write_bytes(source.read_bytes())
    tmpfiles = tmp_path / "etc/tmpfiles.d"
    tmpfiles.mkdir(parents=True)
    # The actual release runs as root; unprivileged CI can exercise copy
    # and preservation semantics without attempting a privileged chown.
    isolated_rule = rule if os.geteuid() == 0 else rule.replace("root root", "- -")
    (tmpfiles / "test.conf").write_text(isolated_rule + "\n")

    def apply():
        subprocess.run([command, "--root=" + str(tmp_path), "--create", "test.conf"],
                       check=True, capture_output=True, timeout=10)

    apply()
    assert config.read_bytes() == source.read_bytes()
    assert config.stat().st_mode & 0o777 == 0o640
    custom = b'{"schema_version":1,"segment_seconds":2,"continuous_wss":true}\n'
    config.write_bytes(custom)
    apply()
    assert config.read_bytes() == custom
