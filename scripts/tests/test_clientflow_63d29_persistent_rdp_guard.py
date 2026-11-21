"""63D-29: boot-ordered RDP guard, no RDP start, safe removal and negative tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import clientflow_63d29_persistent_rdp_guard as guard


class Result:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def test_only_physical_root_client3_is_accepted():
    assert guard.identity_verified("viborg1-NUC14MNK-B2", 0, {"CLIENT_ID": 3})
    for host, uid, data in (
        ("another", 0, {"CLIENT_ID": 3}),
        ("viborg1-NUC14MNK-B2", 1000, {"CLIENT_ID": 3}),
        ("viborg1-NUC14MNK-B2", 0, {"CLIENT_ID": 56}),
        ("viborg1-NUC14MNK-B2", 0, {}),
        ("viborg1-NUC14MNK-B2", 0, None),
    ):
        assert not guard.identity_verified(host, uid, data)


def test_nft_policy_covers_ipv4_ipv6_tcp_udp_and_entire_negotiation_range():
    rules = guard.RULES
    assert f"table inet {guard.TABLE_NAME}" in rules
    assert 'iifname != "lo" tcp dport 3389-3398 drop' in rules
    assert 'iifname != "lo" udp dport 3389-3398 drop' in rules
    assert "hook input priority -150" in rules
    assert "policy accept;" in rules
    assert guard.canonical_installed_rules(rules)
    assert not guard.canonical_installed_rules(
        rules.replace("udp dport 3389-3398 drop", "udp dport 3389-3398 accept")
    )
    assert not guard.canonical_installed_rules(
        rules.replace("3389-3398", "3389-3390")
    )
    assert not guard.canonical_installed_rules(
        rules.replace("iifname != \"lo\"", "iifname \"lo\"")
    )
    assert not guard.canonical_installed_rules(
        rules.replace(f"table inet {guard.TABLE_NAME}", "table inet unrelated")
    )


def test_boot_guard_installed_before_display_manager_and_default_is_fail_closed():
    assert "Before=sysinit.target network-pre.target display-manager.service" in guard.UNIT
    assert "After=local-fs.target" in guard.UNIT
    assert "WantedBy=sysinit.target" in guard.UNIT
    assert "RemainAfterExit=yes" in guard.UNIT
    assert f"ExecStart=/usr/sbin/nft -f {guard.RULE_PATH}" in guard.UNIT
    assert "ExecStop=" not in guard.UNIT
    assert "grdctl" not in guard.UNIT
    assert "gnome-remote-desktop" not in guard.UNIT


@pytest.mark.parametrize("address", [
    "LISTEN 0 128 127.0.0.1:3389 0.0.0.0:*",
    "LISTEN 0 128 [::]:3398 [::]:*",
    "UNCONN 0 0 0.0.0.0:3389 0.0.0.0:*",
])
def test_existing_tcp_udp_rdp_listeners_block_install_or_removal(address):
    assert guard.contains_rdp_listener(address)


def test_unrelated_ports_do_not_block_guard():
    assert not guard.contains_rdp_listener("LISTEN 0 128 0.0.0.0:443 0.0.0.0:*")


def test_remove_aborts_without_changing_service_if_rdp_cannot_be_proved_off(monkeypatch):
    calls = []
    monkeypatch.setattr(
        guard, "ensure_rdp_off",
        lambda uid: (_ for _ in ()).throw(RuntimeError("STOP: RDP enabled")),
    )
    monkeypatch.setattr(guard, "run", lambda *a, **k: calls.append(a) or Result())
    with pytest.raises(RuntimeError, match="STOP"):
        guard.remove_guard("1000")
    assert not calls


def test_remove_requires_exact_owned_unit_and_valid_kernel_rules(monkeypatch, tmp_path):
    parent = tmp_path / "dir"
    parent.mkdir()
    unit = tmp_path / "guard.service"
    rule = parent / "guard.nft"
    unit.write_text("[Unit]\nDescription=UNTRUSTED\n")
    rule.write_text(guard.RULES)
    monkeypatch.setattr(guard, "UNIT_PATH", unit)
    monkeypatch.setattr(guard, "RULE_PATH", rule)
    monkeypatch.setattr(guard, "ensure_rdp_off", lambda uid: None)
    monkeypatch.setattr(guard, "guard_verified", lambda: True)
    calls = []
    monkeypatch.setattr(guard, "run", lambda *a, **kw: calls.append(a) or Result())
    with pytest.raises(RuntimeError, match="Ukendt guard"):
        guard.remove_guard("1000")
    assert calls == []


def test_remove_order_rdp_off_then_disable_boot_guard_then_delete_nft(monkeypatch, tmp_path):
    directory = tmp_path / "dir"
    directory.mkdir()
    rule = directory / "guard.nft"
    unit = tmp_path / "guard.service"
    rule.write_text(guard.RULES)
    unit.write_text(guard.UNIT)
    monkeypatch.setattr(guard, "DIRECTORY", directory)
    monkeypatch.setattr(guard, "RULE_PATH", rule)
    monkeypatch.setattr(guard, "UNIT_PATH", unit)
    events = []
    monkeypatch.setattr(guard, "ensure_rdp_off", lambda uid: events.append("rdp-off"))
    monkeypatch.setattr(guard, "guard_verified", lambda: True)
    def fake_run(*args, **kwargs):
        events.append(" ".join(args))
        return Result()
    monkeypatch.setattr(guard, "run", fake_run)
    guard.remove_guard("1000")
    assert events[:2] == ["rdp-off", "rdp-off"]
    assert events.index("systemctl disable --now " + guard.UNIT_NAME) > 1
    assert events.index("nft delete table inet " + guard.TABLE_NAME) > events.index(
        "systemctl disable --now " + guard.UNIT_NAME
    )
    assert not directory.exists()
    assert not unit.exists()


def test_source_never_starts_rdp_or_exposes_credentials():
    source = (Path(__file__).resolve().parents[1] /
              "clientflow_63d29_persistent_rdp_guard.py").read_text()
    forbidden = (
        "rdp enable", "rdp set-credentials", "rdp set-tls-key",
        "systemctl --user start", "grdctl --system", "grdctl --headless",
        "ufw allow", "nft flush ruleset", "socket.connect(", "urlopen(",
    )
    assert not any(value in source for value in forbidden)
