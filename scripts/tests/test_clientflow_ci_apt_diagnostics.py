"""CI-only APT diagnostics must preserve fail-closed host proof semantics."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "clientflow_ci_apt.py"
HOST = ROOT / "scripts" / "verify_clientflow_ubuntu2604_host.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"

spec = importlib.util.spec_from_file_location("clientflow_ci_apt_test_module", SCRIPT)
assert spec is not None and spec.loader is not None
ci_apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_apt)


def test_stream_command_reports_success_and_live_output(capsys):
    result = ci_apt.stream_command(
        [sys.executable, "-u", "-c", "print('CI_APT_SAMPLE_PACKAGE_INSTALLED')"],
        timeout=15, idle_timeout=10,
    )
    assert "CI_APT_SAMPLE_PACKAGE_INSTALLED" in result
    output = capsys.readouterr().out
    assert "CI_APT_START" in output
    assert "CI_APT_SUCCESS" in output
    assert "CI_APT_SAMPLE_PACKAGE_INSTALLED" in output


def test_stream_command_rejects_nonzero_exit():
    with pytest.raises(ci_apt.CIAptCommandError, match="CI_APT_EXIT_7"):
        ci_apt.stream_command([sys.executable, "-c", "raise SystemExit(7)"], timeout=5)


def test_stream_command_fails_closed_when_child_stops_sending_output():
    started = time.monotonic()
    with pytest.raises(ci_apt.CIAptCommandError, match="CI_APT_IDLE_TIMEOUT"):
        ci_apt.stream_command(
            [sys.executable, "-u", "-c", "import time; print('started'); time.sleep(30)"],
            timeout=5, idle_timeout=0.3,
        )
    assert time.monotonic() - started < 3


def test_stream_command_fails_closed_on_hard_timeout_despite_progress():
    with pytest.raises(ci_apt.CIAptCommandError, match="CI_APT_HARD_TIMEOUT"):
        ci_apt.stream_command(
            [sys.executable, "-u", "-c", "import time; [(print('alive'), time.sleep(.1)) for _ in range(200)]"],
            timeout=0.5, idle_timeout=2,
        )


def test_ci_apt_adapter_requires_canonical_apt_executable_and_command(monkeypatch):
    seen = []

    def fake_stream(command, *, timeout):
        seen.append((command, timeout))
        return "ok"

    monkeypatch.setattr(ci_apt, "stream_command", fake_stream)
    with pytest.raises(ci_apt.CIAptCommandError, match="CI_APT_REJECTED"):
        ci_apt.run_ci_apt(["/bin/true"], timeout=600)
    assert not seen
    update = ["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "update"]
    install = ["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "-y", "--no-install-recommends", "install", "rfkill"]
    assert ci_apt.run_ci_apt(update, timeout=600) == "ok"
    assert ci_apt.run_ci_apt(install, timeout=1200) == "ok"
    assert seen == [(update, ci_apt.MAX_UPDATE_SECONDS), (install, ci_apt.MAX_INSTALL_SECONDS)]


def test_ci_apt_failure_snapshots_diagnostics_and_never_succeeds(monkeypatch, capsys):
    def error(*args, **kwargs):
        raise ci_apt.CIAptCommandError("broken-package")

    called = []
    monkeypatch.setattr(ci_apt, "stream_command", error)
    monkeypatch.setattr(ci_apt, "print_apt_diagnostics", lambda: called.append(True))
    with pytest.raises(ci_apt.CIAptCommandError, match="broken-package"):
        ci_apt.run_ci_apt(["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "update"])
    assert called == [True]
    assert "CI_APT_FAILED" in capsys.readouterr().out


def test_ci_apt_runner_is_only_used_by_host_gate_not_production_client():
    source = HOST.read_text(encoding="utf-8")
    workflow = CI.read_text(encoding="utf-8")
    production = (ROOT / "client/runtime/clientflow_runtime/platform_prepare.py").read_text(encoding="utf-8")
    assert "from clientflow_ci_apt import run_ci_apt" in source
    assert "module._ensure_packages(packages)" in source
    assert "module._verify_capabilities()" in source
    assert "return run_ci_apt(command, timeout=timeout)" in source
    assert "clientflow_ci_apt" not in production
    assert "timeout-minutes: 25" in workflow
    assert 'test "$PLATFORM_RESULT" = "success"' in workflow
    assert "--install-platform-requirements" in workflow
    assert "client-host-ubuntu-2604-platform" in workflow


def test_host_capability_gate_preserves_canonical_package_and_probe_contract(monkeypatch):
    """CI changes process I/O, never which requirements/capabilities are checked."""
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    host_spec = importlib.util.spec_from_file_location("clientflow_ci_host_gate_probe", HOST)
    assert host_spec is not None and host_spec.loader is not None
    host = importlib.util.module_from_spec(host_spec)
    host_spec.loader.exec_module(host)

    calls = []
    apt = ["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "update"]

    def ordinary(command, *, timeout):
        calls.append(("original", command, timeout))
        return "original"

    module = SimpleNamespace(
        _requirements=lambda: [{"package": "rfkill", "minimum_version": "1"}],
        _run=ordinary,
    )

    def ensure(packages):
        calls.append(("packages", packages))
        assert module._run(apt, timeout=600) == "streamed"
        assert module._run(["/usr/bin/python3", "-V"], timeout=60) == "original"

    module._ensure_packages = ensure
    module._verify_capabilities = lambda: calls.append(("verified",))
    monkeypatch.setattr(host, "_load_platform_prepare", lambda _repo: module)
    monkeypatch.setattr(host.os, "geteuid", lambda: 0)
    monkeypatch.setattr(host, "run_ci_apt", lambda cmd, *, timeout: calls.append(("apt", cmd, timeout)) or "streamed")

    result = host._platform_capabilities(ROOT)
    assert result == {"platform_packages": 1, "capabilities": "ok"}
    assert calls == [
        ("packages", [{"package": "rfkill", "minimum_version": "1"}]),
        ("apt", apt, 600),
        ("original", ["/usr/bin/python3", "-V"], 60),
        ("verified",),
    ]


def test_ci_apt_adapter_rejects_unapproved_options_or_package_syntax(monkeypatch):
    monkeypatch.setattr(ci_apt, "stream_command", lambda *args, **kwargs: "UNREACHABLE")
    for command in (
        ["/usr/bin/apt-get", "-y", "update"],
        ["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "-y", "install", "rfkill"],
        ["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "-y", "--no-install-recommends", "install", "--allow-unauthenticated"],
    ):
        with pytest.raises(ci_apt.CIAptCommandError, match="CI_APT_REJECTED"):
            ci_apt.run_ci_apt(command)
