"""63D-30 local RDP authentication test-package planning only, no host mutation."""
from pathlib import Path

import pytest

from scripts import clientflow_63d30_local_client_package_preflight as p


@pytest.mark.parametrize("raw, expected", [
    ("freerdp-x11:\n Installed: (none)\n Candidate: 3.32.2+dfsg-0ubuntu0.26.04.1", "3.32.2+dfsg-0ubuntu0.26.04.1"),
    ("xvfb:\n Installed: (none)\n Candidate: (none)", None),
    ("xauth:\n Candidate: 1:1.1.4-1", "1:1.1.4-1"),
    ("", None),
])
def test_candidate_parser(raw, expected):
    assert p.candidate(raw) == expected


def test_apt_simulation_counts_removals_installations_upgrades():
    result = p.simulation_summary(
        "Reading package lists...\n"
        "Inst freerdp-x11 (3.32.2+dfsg-0ubuntu0.26.04.1 Ubuntu:26.04/updates [amd64])\n"
        "Inst xvfb (2:21.1.22-1ubuntu1 Ubuntu:26.04/updates [amd64])\n"
        "Inst openssl [old-version] (new-version Ubuntu:26.04/updates [amd64])\n"
        "Remv unrelated-package [1.0]\n"
    )
    assert result == {"installs": 3, "removals": 1, "upgrades": 1}


def test_read_only_script_has_no_network_listeners_package_installs_or_ssh_actions():
    source = Path(p.__file__).read_text()
    assert "apt-get\", \"-s" in source
    assert "Debug::NoLocking=1" in source
    assert '"--no-install-recommends"' in source
    assert p.PACKAGES == ("freerdp-x11", "xvfb", "xauth")
    for forbidden in (
        'apt-get", "install"',
        'apt-get", "update"',
        'systemctl", "enable"',
        'systemctl", "start"',
        'nft", "add"',
        'nft", "delete"',
        'grdctl", "rdp"',
        'ssh", "-L"',
        'subprocess.Popen',
    ):
        assert forbidden not in source
