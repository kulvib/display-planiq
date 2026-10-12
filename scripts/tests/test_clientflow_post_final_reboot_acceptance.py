from __future__ import annotations

from collections import namedtuple
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from clientflow_runtime import post_final_reboot_acceptance as gate


def _pending(state_path: Path, boot_id: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "status": "awaiting_post_final_reboot_acceptance",
        "pre_reboot_boot_id": boot_id,
        "lockdown_verified_before_reboot": True,
    }), encoding="utf-8")
    state_path.chmod(0o600)


def _prepare_verified_gate(monkeypatch, tmp_path: Path) -> Path:
    state_path = tmp_path / "customer-handoff.json"
    boot_path = tmp_path / "boot_id"
    boot_path.write_text("boot-b\n", encoding="ascii")
    _pending(state_path, "boot-a")
    monkeypatch.setattr(gate, "STATE_PATH", state_path)
    monkeypatch.setattr(gate, "BOOT_ID_PATH", boot_path)
    monkeypatch.setattr(gate, "STATE_OWNER_UID", state_path.stat().st_uid)
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gate, "_active_local_kiosk_session", lambda: "session-1")
    monkeypatch.setattr(gate, "lockdown_status", lambda: {
        "desired": True, "status": "applied", "enforcement": {"ok": True}
    })
    monkeypatch.setattr(gate, "_group_names", lambda username: {"sudo"} if username == "cfadmin" else set())
    monkeypatch.setattr(gate, "_verify_nautilus_ding_session", lambda: None)
    monkeypatch.setattr(gate, "_verify_display_runtime", lambda current_boot: "https://display.example/")
    monkeypatch.setattr(gate, "_verify_critical_services", lambda: None)
    monkeypatch.setattr(gate, "_verify_browser_guard", lambda _kiosk_url: None)
    monkeypatch.setattr(gate, "_verify_backend_approved", lambda: None)
    return state_path


def test_post_final_reboot_gate_rejects_same_boot(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "customer-handoff.json"
    boot_path = tmp_path / "boot_id"
    boot_path.write_text("boot-a\n", encoding="ascii")
    _pending(state_path, "boot-a")
    monkeypatch.setattr(gate, "STATE_PATH", state_path)
    monkeypatch.setattr(gate, "BOOT_ID_PATH", boot_path)
    monkeypatch.setattr(gate, "STATE_OWNER_UID", state_path.stat().st_uid)
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="Final reboot"):
        gate.verify_and_accept()


def test_post_final_reboot_gate_accepts_only_complete_verified_new_boot(monkeypatch, tmp_path: Path) -> None:
    state_path = _prepare_verified_gate(monkeypatch, tmp_path)

    result = gate.verify_and_accept()

    assert result["status"] == "accepted"
    assert result["accepted_boot_id"] == "boot-b"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "accepted"
    assert persisted["kiosk_lockdown_status"] == "applied"
    assert persisted["kiosk_session_ready"] is True
    assert persisted["nautilus_ready"] is True
    assert persisted["ding_filemanager_ready"] is True
    assert persisted["account_separation_ready"] is True
    assert persisted["browser_boot_ready"] is True
    assert persisted["browser_boot_countdown_seconds"] == 10
    assert persisted["browser_guard_ready"] is True
    assert persisted["critical_services_ready"] is True
    assert persisted["backend_approved_ready"] is True


def test_post_final_reboot_gate_reapplies_desired_lockdown_drift(monkeypatch, tmp_path: Path) -> None:
    state_path = _prepare_verified_gate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(gate, "lockdown_status", lambda: {
        "desired": True, "status": "pending", "enforcement": {"ok": False}
    })

    def apply():
        calls.append("apply")
        return {"desired": True, "status": "applied", "enforcement": {"ok": True}}

    monkeypatch.setattr(gate, "apply_lockdown", apply)

    result = gate.verify_and_accept()

    assert calls == ["apply"]
    assert result["status"] == "accepted"
    assert json.loads(state_path.read_text(encoding="utf-8"))["kiosk_lockdown_status"] == "applied"


def test_post_final_reboot_gate_lockdown_reapply_failure_stays_pending(monkeypatch, tmp_path: Path) -> None:
    state_path = _prepare_verified_gate(monkeypatch, tmp_path)
    monkeypatch.setattr(gate, "lockdown_status", lambda: {
        "desired": True, "status": "pending", "enforcement": {"ok": False}
    })

    def fail_apply():
        raise RuntimeError("GNOME session not ready")

    monkeypatch.setattr(gate, "apply_lockdown", fail_apply)

    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="kunne ikke konvergeres"):
        gate.verify_and_accept()

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "awaiting_post_final_reboot_acceptance"


@pytest.mark.parametrize("helper", [
    "_verify_nautilus_ding_session",
    "_verify_display_runtime",
    "_verify_critical_services",
    "_verify_browser_guard",
    "_verify_backend_approved",
])
def test_post_final_reboot_gate_never_accepts_when_required_runtime_proof_fails(
    monkeypatch, tmp_path: Path, helper: str
) -> None:
    state_path = _prepare_verified_gate(monkeypatch, tmp_path)

    def fail(*_args, **_kwargs):
        raise gate.PostFinalRebootAcceptanceError("proof missing")

    monkeypatch.setattr(gate, helper, fail)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="proof missing"):
        gate.verify_and_accept()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "awaiting_post_final_reboot_acceptance"


def test_display_runtime_proof_requires_current_boot_exact_countdown_and_configured_url(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "configuration.json"
    status = tmp_path / "runtime-status.json"
    marker = tmp_path / "browser-boot.json"
    proc_root = tmp_path / "proc"
    pid_dir = proc_root / "4242"
    pid_dir.mkdir(parents=True)
    config.write_text(json.dumps({"schema_version": 1, "revision": 3, "kiosk_url": "https://display.example/screen"}))
    status.write_text(json.dumps({"schema_version": 1, "state": "running", "browser_requested": True, "browser_pid": 4242}))
    marker.write_text(json.dumps({
        "schema_version": 1,
        "boot_id": "boot-b",
        "countdown_reason": "system_start",
        "countdown_seconds": 10,
    }))
    chrome_executable = tmp_path / "opt" / "google" / "chrome" / "chrome"
    chrome_executable.parent.mkdir(parents=True)
    chrome_executable.touch()
    (pid_dir / "exe").symlink_to(chrome_executable)
    (pid_dir / "status").write_text("Name:\tchrome\nUid:\t1001\t1001\t1001\t1001\n", encoding="ascii")
    command = [
        str(chrome_executable),
        "--ozone-platform=wayland", "--start-fullscreen",
        f"--user-data-dir={tmp_path / 'browser-profile'}",
        "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222",
        "about:blank",
    ]
    (pid_dir / "cmdline").write_bytes(("\0".join(command) + "\0").encode())
    monkeypatch.setattr(gate, "CANONICAL_CHROME_EXECUTABLE", chrome_executable)
    monkeypatch.setattr(gate, "CANONICAL_CHROME_PROFILE", tmp_path / "browser-profile")
    monkeypatch.setattr(gate.pwd, "getpwnam", lambda _username: namedtuple("Pw", "pw_uid")(1001))
    monkeypatch.setattr(gate, "DISPLAY_CONFIG_PATH", config)
    monkeypatch.setattr(gate, "DISPLAY_STATUS_PATH", status)
    monkeypatch.setattr(gate, "DISPLAY_BOOT_MARKER_PATH", marker)
    monkeypatch.setattr(gate, "PROC_ROOT", proc_root)

    assert gate._verify_display_runtime("boot-b") == "https://display.example/screen"

    marker.write_text(json.dumps({
        "schema_version": 1,
        "boot_id": "boot-b",
        "countdown_reason": "system_start",
        "countdown_seconds": 9,
    }))
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="10 sekunders"):
        gate._verify_display_runtime("boot-b")


@pytest.mark.parametrize("argv0", ["canonical_launcher", "canonical_elf"])
def test_post_reboot_chrome_acceptance_matches_debian_launcher_and_exec_elf(
    monkeypatch, tmp_path: Path, argv0: str
) -> None:
    """The real 26.04 Chrome process execs /opt/google/chrome/chrome."""
    executable = tmp_path / "opt" / "google" / "chrome" / "chrome"
    executable.parent.mkdir(parents=True)
    executable.touch()
    launcher = tmp_path / "usr" / "bin" / "google-chrome-stable"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    proc_root = tmp_path / "proc"
    proc = proc_root / "4525"
    proc.mkdir(parents=True)
    (proc / "exe").symlink_to(executable)
    (proc / "status").write_text("Name:\tchrome\nUid:\t1001\t1001\t1001\t1001\n", encoding="ascii")
    profile = tmp_path / "browser-profile"
    arguments = [
        str(executable if argv0 == "canonical_elf" else launcher),
        "--ozone-platform=wayland", "--start-fullscreen",
        f"--user-data-dir={profile}",
        "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222",
        "about:blank",
    ]

    def store(args: list[str]) -> None:
        (proc / "cmdline").write_bytes(("\0".join(args) + "\0").encode())

    store(arguments)
    monkeypatch.setattr(gate, "PROC_ROOT", proc_root)
    monkeypatch.setattr(gate, "CANONICAL_CHROME_EXECUTABLE", executable)
    monkeypatch.setattr(gate, "CANONICAL_CHROME_LAUNCHER", launcher)
    monkeypatch.setattr(gate, "CANONICAL_CHROME_PROFILE", profile)
    monkeypatch.setattr(gate.pwd, "getpwnam", lambda _username: namedtuple("Pw", "pw_uid")(1001))
    gate._verify_chrome_process(4525)

    # Chromium's Linux setproctitle may flatten the entire cmdline to argv[0].
    # This was observed physically on ClientFlow 1.3.35 / Ubuntu 26.04.
    store([" ".join(arguments)])
    gate._verify_chrome_process(4525)
    for missing_flag in arguments[1:]:
        store([" ".join(arg for arg in arguments if arg != missing_flag)])
        with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
            gate._verify_chrome_process(4525)
    store([" ".join([arg for arg in arguments if arg != "--start-fullscreen"] +
                    ["--start-fullscreen=spoofed"])])
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
        gate._verify_chrome_process(4525)
    store([" ".join([*arguments, "--type=renderer"])])
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
        gate._verify_chrome_process(4525)
    store(["/tmp/untrusted-chrome " + " ".join(arguments[1:])])
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
        gate._verify_chrome_process(4525)
    store(arguments)

    # Every tested boundary is required, even when /proc says Chrome runs.
    for missing in ("--ozone-platform=wayland", "--start-fullscreen", f"--user-data-dir={profile}",
                    "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222", "about:blank"):
        store([arg for arg in arguments if arg != missing])
        with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
            gate._verify_chrome_process(4525)
    store(arguments)

    (proc / "status").write_text("Name:\tchrome\nUid:\t1002\t1002\t1002\t1002\n", encoding="ascii")
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
        gate._verify_chrome_process(4525)
    (proc / "status").write_text("Name:\tchrome\nUid:\t1001\t1001\t1001\t1001\n", encoding="ascii")

    malicious = tmp_path / "untrusted" / "chrome"
    malicious.parent.mkdir(parents=True)
    malicious.touch()
    (proc / "exe").unlink()
    (proc / "exe").symlink_to(malicious)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
        gate._verify_chrome_process(4525)

    (proc / "exe").unlink()
    (proc / "exe").symlink_to(executable)
    store(["/tmp/untrusted-chrome", *arguments[1:]])
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="canonical Chrome"):
        gate._verify_chrome_process(4525)

    (proc / "cmdline").unlink()
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="identitetsverificeres"):
        gate._verify_chrome_process(4525)


def test_browser_guard_proof_requires_correct_url_marker_css_and_no_visible_consent(monkeypatch) -> None:
    from clientflow_runtime import browser_guard

    monkeypatch.setattr(browser_guard, "get_tabs", lambda: [{
        "type": "page", "url": "https://display.example/", "webSocketDebuggerUrl": "ws://example"
    }])
    monkeypatch.setattr(browser_guard, "is_main_page_target", lambda _tab: True)

    async def good(_tab, _js, _label):
        return {
            "href": "https://display.example/",
            "readyState": "complete",
            "marker": browser_guard.VERSION,
            "css": True,
            "visibleConsent": [],
        }

    monkeypatch.setattr(browser_guard, "evaluate_js", good)
    gate._verify_browser_guard("https://display.example/")

    async def blocked(_tab, _js, _label):
        return {
            "href": "https://display.example/",
            "readyState": "complete",
            "marker": browser_guard.VERSION,
            "css": True,
            "visibleConsent": ["#coiOverlay"],
        }

    monkeypatch.setattr(browser_guard, "evaluate_js", blocked)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="cookie/consent"):
        gate._verify_browser_guard("https://display.example/")

    async def wrong_url(_tab, _js, _label):
        return {
            "href": "https://wrong.example/",
            "readyState": "complete",
            "marker": browser_guard.VERSION,
            "css": True,
            "visibleConsent": [],
        }

    monkeypatch.setattr(browser_guard, "evaluate_js", wrong_url)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="konfigurerede URL"):
        gate._verify_browser_guard("https://display.example/")


def test_kiosk_url_match_allows_only_refresh_marker_query_delta() -> None:
    assert gate._kiosk_url_matches(
        "https://display.example/screen?location=1",
        "https://display.example/screen/?location=1&_kiosk_refresh=123",
    )
    assert not gate._kiosk_url_matches(
        "https://display.example/screen?location=1",
        "https://display.example/other?location=1",
    )
    assert not gate._kiosk_url_matches(
        "https://display.example/screen?location=1",
        "https://wrong.example/screen?location=1",
    )


def test_critical_services_proof_requires_every_unit_and_accept_cookie_mode(monkeypatch) -> None:
    Completed = namedtuple("Completed", "returncode stdout stderr")

    def good(command, **_kwargs):
        if "show" in command:
            return Completed(0, "CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE=accept CLIENTFLOW_BROWSER_GUARD_INTERVAL=2\n", "")
        return Completed(0, "active\n", "")

    monkeypatch.setattr(gate, "_run", good)
    gate._verify_critical_services()

    def one_failed(command, **_kwargs):
        if "show" in command:
            return Completed(0, "CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE=accept\n", "")
        if command[-1] == gate.CRITICAL_ACTIVE_UNITS[0]:
            return Completed(3, "inactive\n", "")
        return Completed(0, "active\n", "")

    monkeypatch.setattr(gate, "_run", one_failed)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="Kritiske ClientFlow-units"):
        gate._verify_critical_services()

def test_nautilus_ding_proof_requires_filemanager_dbus_and_clean_current_boot_journal(
    monkeypatch, tmp_path: Path
) -> None:
    Completed = namedtuple("Completed", "returncode stdout stderr")
    nautilus = tmp_path / "nautilus"
    nautilus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    nautilus.chmod(0o755)
    run_user_root = tmp_path / "run-user"
    (run_user_root / "1001").mkdir(parents=True)
    (run_user_root / "1001" / "bus").touch()
    Pw = namedtuple("Pw", "pw_uid pw_dir")
    monkeypatch.setattr(gate, "NAUTILUS", nautilus)
    monkeypatch.setattr(gate, "RUN_USER_ROOT", run_user_root)
    monkeypatch.setattr(gate.pwd, "getpwnam", lambda _username: Pw(1001, "/home/clientflow-kiosk"))

    calls: list[list[str]] = []

    def clean(command, **_kwargs):
        calls.append(command)
        if "gdbus" in " ".join(command):
            return Completed(0, "(uint32 1,)\n", "")
        return Completed(0, "", "")

    monkeypatch.setattr(gate, "_run", clean)
    gate._verify_nautilus_ding_session()
    assert any("org.freedesktop.FileManager1" in command for command in calls)
    assert any("--grep=Nautilus File Manager not found|mandatory to work with Desktop Icons NG" in command for command in calls)

    def popup_seen(command, **_kwargs):
        if "gdbus" in " ".join(command):
            return Completed(0, "(uint32 1,)\n", "")
        return Completed(0, "Nautilus File Manager not found\n", "")

    monkeypatch.setattr(gate, "_run", popup_seen)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="startup-fejl"):
        gate._verify_nautilus_ding_session()


def test_backend_approved_proof_requires_fresh_status_domain_token(monkeypatch) -> None:
    credential = object()
    seen: dict[str, object] = {}

    class Credentials:
        @staticmethod
        def load(domain):
            seen["domain"] = domain
            return credential

    class Transport:
        def __init__(self, value):
            assert value is credential

        def access_token(self, *, force_refresh=False):
            seen["force_refresh"] = force_refresh
            return "approved-token"

    monkeypatch.setattr(gate, "DomainCredential", Credentials)
    monkeypatch.setattr(gate, "DomainTransport", Transport)
    gate._verify_backend_approved()
    assert seen == {"domain": gate.Domain.STATUS, "force_refresh": True}

def test_post_final_reboot_gate_rejects_wrong_state_owner(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "customer-handoff.json"
    _pending(state_path, "boot-a")
    monkeypatch.setattr(gate, "STATE_PATH", state_path)
    monkeypatch.setattr(gate, "STATE_OWNER_UID", state_path.stat().st_uid + 1)
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="ownership/permissions"):
        gate.verify_and_accept()
