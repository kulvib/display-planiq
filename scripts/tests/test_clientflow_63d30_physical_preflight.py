"""63D-30 physical preflight: parse only non-sensitive GNOME and socket state."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import clientflow_63d30_physical_preflight as p


def test_strict_machine_identity():
    assert p.valid_target("viborg1-NUC14MNK-B2", 0, {"CLIENT_ID": 3})
    for host, uid, data in (
        ("another", 0, {"CLIENT_ID": 3}),
        ("viborg1-NUC14MNK-B2", 1000, {"CLIENT_ID": 3}),
        ("viborg1-NUC14MNK-B2", 0, {"CLIENT_ID": 2}),
        ("viborg1-NUC14MNK-B2", 0, {}),
        ("viborg1-NUC14MNK-B2", 0, None),
    ):
        assert not p.valid_target(host, uid, data)


@pytest.mark.parametrize("text, expected", [
    ("RDP:\n Username: (empty)\n Password: (empty)\n", "EMPTY"),
    ("Overall:\n\tUnit status: inactive\nRDP:\n\tUsername: (empty)\n\tPassword: (empty)\n", "EMPTY"),
    ("RDP:\n\tUsername:\t(empty)\n\tPassword:\t(empty)\n", "EMPTY"),
    ("RDP:\r\n Username: (empty)\r\n\tPassword: (empty) \r\n", "EMPTY"),
    ("RDP:\n\tUsername: (empty)\n\tPassword: (empty)\nVNC:\n\tPassword: (hidden)\n", "EMPTY"),
    ("RDP:\n\tUsername: (empty)\n\tUsername: (empty)\n\tPassword: (empty)\n", "UNKNOWN"),
    ("RDP:\n\tUsername: (empty)\n\tPassword: (empty)\n\tPassword: (empty)\n", "UNKNOWN"),
    ("RDP:\n\tUsername: (empty)\n\tPassword: (empty)\nRDP:\n\tUsername: (empty)\n\tPassword: (empty)", "UNKNOWN"),
    ("RDP:\n Username: (hidden)\n Password: (hidden)", "NOT_EMPTY_OR_UNEXPECTED"),
    ("RDP:\n Username: (empty)\n Password: (hidden)", "NOT_EMPTY_OR_UNEXPECTED"),
    ("RDP:\n Username: remote-user\n Password: remote-secret", "NOT_EMPTY_OR_UNEXPECTED"),
    ("RDP:\n Username: (empty)\n", "UNKNOWN"),
    ("VNC:\n\tPassword: (empty)\n", "UNKNOWN"),
    (" Username: (empty)\n Password: (empty)", "UNKNOWN"),
    ("", "UNKNOWN"),
])

def test_credentials_are_never_copied_to_output(text, expected):
    assert p.credential_state(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("LISTEN 0 128 0.0.0.0:3389 0.0.0.0:*", [3389]),
    ("LISTEN 0 128 [::]:3398 [::]:*", [3398]),
    ("UNCONN 0 0 [::]:3389 [::]:*", [3389]),
    ("LISTEN 0 128 0.0.0.0:3389 0.0.0.0:*\n"
     "LISTEN 0 128 127.0.0.1:3390 0.0.0.0:*", [3389, 3390]),
    ("LISTEN 0 128 0.0.0.0:443 0.0.0.0:*", []),
    ("", []),
])
def test_port_parser_preserves_ipv4_ipv6_and_detects_full_range(text, expected):
    assert p.listened_ports(text) == expected


def test_preflight_source_has_no_mutating_commands_or_secret_dumping():
    source = Path(p.__file__).read_text()
    assert "grdctl\", \"status" in source
    assert "grdctl\", \"--help" in source
    assert "systemd-analyze\", \"calendar" in source
    assert "print(raw)" not in source
    assert "print(help_text)" not in source
    for forbidden in (
        '"systemctl", "enable"', '"systemctl", "disable"',
        '"systemctl", "restart"', '"nft", "delete"',
        '"nft", "add"', '"grdctl", "rdp"', "gsettings\", \"set",
        '"ssh", "-L"', 'subprocess.Popen', "open(\"w\")",
    ):
        assert forbidden not in source


def test_readiness_requires_all_dormant_gnome_properties():
    assert p.RDP_KEYS == {
        "port": "uint16 3389",
        "negotiate-port": "true",
        "screen-share-mode": "'mirror-primary'",
        "view-only": "true",
        "enable": "false",
        "auth-methods": "['credentials']",
        "tls-cert": "''",
        "tls-key": "''",
    }
    assert "set-credentials" in p.REQUIRED_HELP
    assert "clear-credentials" in p.REQUIRED_HELP
    assert "disable-port-negotiation" in p.REQUIRED_HELP
    assert "disable-view-only" in p.REQUIRED_HELP
