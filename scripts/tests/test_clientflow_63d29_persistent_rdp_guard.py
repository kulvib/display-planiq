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
    assert "ConditionPathExists=" not in guard.UNIT  # Must fail, not skip, on missing rules file.
    assert f"Requires={guard.UNIT_NAME}" in guard.DROPIN
    assert f"After={guard.UNIT_NAME}" in guard.DROPIN
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
    with pytest.raises(RuntimeError, match="Guard service ikke identisk"):
        guard.remove_guard("1000")
    assert calls == []


def test_remove_order_rdp_off_then_disable_boot_guard_then_delete_nft(monkeypatch, tmp_path):
    directory = tmp_path / "dir"
    directory.mkdir()
    rule = directory / "guard.nft"
    unit = tmp_path / "guard.service"
    rule.write_text(guard.RULES)
    unit.write_text(guard.UNIT)
    dropin_dir = tmp_path / "display-manager.service.d"
    dropin_dir.mkdir()
    dropin_path = dropin_dir / "clientflow-63d29-rdp-guard.conf"
    dropin_path.write_text(guard.DROPIN)
    monkeypatch.setattr(guard, "DROPIN_DIR", dropin_dir)
    monkeypatch.setattr(guard, "DROPIN_PATH", dropin_path)
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
    assert events.count("rdp-off") == 3
    assert not dropin_path.exists()
    assert events.index("systemctl daemon-reload") < events.index("systemctl disable --now " + guard.UNIT_NAME)
    assert events.index("systemctl disable --now " + guard.UNIT_NAME) > 1
    assert events.index("nft delete table inet " + guard.TABLE_NAME) > events.index(
        "systemctl disable --now " + guard.UNIT_NAME
    )
    assert not directory.exists()
    assert not unit.exists()
    assert not dropin_path.exists()
    assert not dropin_dir.exists()


def test_source_never_starts_rdp_or_exposes_credentials():
    source = (Path(__file__).resolve().parents[1] /
              "clientflow_63d29_persistent_rdp_guard.py").read_text()
    forbidden = (
        "rdp enable", "rdp set-credentials", "rdp set-tls-key",
        "systemctl --user start", "grdctl --system", "grdctl --headless",
        "ufw allow", "nft flush ruleset", "socket.connect(", "urlopen(",
    )
    assert not any(value in source for value in forbidden)


def test_guard_only_drill_installs_and_removes_without_starting_rdp(monkeypatch):
    import sys
    events = []
    monkeypatch.setattr(guard, "target", lambda: "1000")
    monkeypatch.setattr(guard, "install_guard", lambda uid: events.append("install"))
    monkeypatch.setattr(guard, "status", lambda uid: events.append("status"))
    monkeypatch.setattr(guard, "remove_guard", lambda uid: events.append("remove"))
    monkeypatch.setattr(sys, "argv", ["rdp-guard", "drill"])
    assert guard.main() == 0
    assert events == ["install", "status", "remove"]


def test_guard_only_drill_refuses_cleanup_if_state_cannot_be_proven(monkeypatch):
    import sys
    events = []
    monkeypatch.setattr(guard, "target", lambda: "1000")
    monkeypatch.setattr(guard, "install_guard", lambda uid: events.append("install"))
    monkeypatch.setattr(
        guard, "status",
        lambda uid: (_ for _ in ()).throw(RuntimeError("unknown kernel state")),
    )
    monkeypatch.setattr(guard, "remove_guard", lambda uid: events.append("remove"))
    monkeypatch.setattr(sys, "argv", ["rdp-guard", "drill"])
    assert guard.main() == 2
    assert events == ["install"]


def test_remove_refuses_unknown_display_manager_dependency(monkeypatch, tmp_path):
    directory = tmp_path / "guard"
    directory.mkdir()
    (directory / "guard.nft").write_text(guard.RULES)
    unit = tmp_path / "guard.service"
    unit.write_text(guard.UNIT)
    dropin_dir = tmp_path / "display-manager.service.d"
    dropin_dir.mkdir()
    dropin_path = dropin_dir / "clientflow-63d29-rdp-guard.conf"
    dropin_path.write_text("[Unit]\\nRequires=UNRELATED.service\\n")
    monkeypatch.setattr(guard, "DIRECTORY", directory)
    monkeypatch.setattr(guard, "RULE_PATH", directory / "guard.nft")
    monkeypatch.setattr(guard, "UNIT_PATH", unit)
    monkeypatch.setattr(guard, "DROPIN_DIR", dropin_dir)
    monkeypatch.setattr(guard, "DROPIN_PATH", dropin_path)
    monkeypatch.setattr(guard, "ensure_rdp_off", lambda uid: None)
    monkeypatch.setattr(guard, "guard_verified", lambda: True)
    commands = []
    monkeypatch.setattr(guard, "run", lambda *args, **kw: commands.append(args) or Result())
    with pytest.raises(RuntimeError, match="Display manager dependency er ændret"):
        guard.remove_guard("1000")
    assert not commands
    assert dropin_path.exists()


@pytest.mark.parametrize("blocked", [
    "system-active", "system-enabled", "user-active", "user-enabled",
    "settings-enabled", "rdp-listener",
])
def test_unprotect_rejects_unexpected_rdp_activation_or_boot_enable(monkeypatch, blocked):
    def fake_run(*args, **kwargs):
        if args == ("systemctl", "is-active", "gnome-remote-desktop.service"):
            return Result(code=0 if blocked == "system-active" else 3,
                          stdout="active" if blocked == "system-active" else "inactive")
        if args == ("systemctl", "is-enabled", "gnome-remote-desktop.service"):
            return Result(stdout="enabled" if blocked == "system-enabled" else "disabled")
        if args[:3] == ("ss", "-H", "-ltn"):
            return Result(stdout=(
                "LISTEN 0 128 0.0.0.0:3389 0.0.0.0:*" if blocked == "rdp-listener"
                else "LISTEN 0 128 0.0.0.0:443 0.0.0.0:*"
            ))
        if args[:3] == ("ss", "-H", "-lun"):
            return Result()
        raise AssertionError(repr(args))
    def fake_kiosk(*args, uid):
        if args == ("systemctl", "--user", "is-active", "gnome-remote-desktop.service"):
            return Result(stdout="active" if blocked == "user-active" else "inactive")
        if args == ("systemctl", "--user", "is-enabled", "gnome-remote-desktop.service"):
            return Result(stdout="enabled" if blocked == "user-enabled" else "disabled")
        if args == ("gsettings", "get", "org.gnome.desktop.remote-desktop.rdp", "enable"):
            return Result(stdout="true" if blocked == "settings-enabled" else "false")
        raise AssertionError(repr(args))
    monkeypatch.setattr(guard, "run", fake_run)
    monkeypatch.setattr(guard, "kiosk", fake_kiosk)
    with pytest.raises(RuntimeError, match="STOP"):
        guard.ensure_rdp_off("1000")


def test_unprotect_accepts_proven_disabled_rdp_without_other_network_changes(monkeypatch):
    commands = []
    def fake_run(*args, **kwargs):
        commands.append(args)
        if args == ("systemctl", "is-active", "gnome-remote-desktop.service"):
            return Result(code=3, stdout="inactive")
        if args == ("systemctl", "is-enabled", "gnome-remote-desktop.service"):
            return Result(stdout="disabled")
        if args[0] == "ss":
            return Result(stdout="LISTEN 0 128 0.0.0.0:443 0.0.0.0:*")
        raise AssertionError(repr(args))
    def fake_kiosk(*args, uid):
        commands.append(args)
        if "is-active" in args:
            return Result(code=3, stdout="inactive")
        if "is-enabled" in args:
            return Result(stdout="disabled")
        if "gsettings" in args:
            return Result(stdout="false")
        raise AssertionError(repr(args))
    monkeypatch.setattr(guard, "run", fake_run)
    monkeypatch.setattr(guard, "kiosk", fake_kiosk)
    guard.ensure_rdp_off("1000")
    assert len(commands) == 7
