#!/usr/bin/env python3
"""CI-only, fail-closed APT execution with live output and bounded diagnostics.

This module is never bundled into ClientFlow runtime. The platform verifier
uses it only on disposable GitHub Ubuntu hosts, preserving production APT flow.
"""
from __future__ import annotations

from collections import deque
import os
import select
import signal
import re
import subprocess
import time


class CIAptCommandError(RuntimeError):
    """The required APT command failed or could not be verified as complete."""


# An otherwise silent APT subprocess should not consume the whole job timeout.
# APT/dpkg progress keeps the watchdog alive, subject to an absolute limit.
MAX_IDLE_SECONDS = 240
MAX_UPDATE_SECONDS = 420
MAX_INSTALL_SECONDS = 900

# GitHub's Ubuntu mirror+file source prefers azure.archive.ubuntu.com and
# falls back to archive.ubuntu.com/security.ubuntu.com. Default same-mirror
# retries can consume the entire CI job when an HTTP connection stalls.
# Bound each transport attempt and allow the signed APT mirror list to fail
# over; do not change package sources, signatures, or production APT settings.
CI_APT_NETWORK_OPTIONS = (
    "-o",
    "Acquire::Retries=0",
    "-o",
    "Acquire::http::Timeout=20",
    "-o",
    "Acquire::https::Timeout=20",
)


def _terminate_group(proc: subprocess.Popen[bytes]) -> None:
    """Kill the whole apt/dpkg process group, including any forked children."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def stream_command(command: list[str], *, timeout: float, idle_timeout: float = MAX_IDLE_SECONDS) -> str:
    """Stream output while retaining only a bounded tail for useful failures.

    Both wall-clock and inactivity watchdogs fail closed. No shell is used.
    """
    if timeout <= 0 or idle_timeout <= 0:
        raise ValueError("CI APT timeouts must be positive")
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "DEBIAN_FRONTEND": "noninteractive",
        "APT_LISTCHANGES_FRONTEND": "none",
    }
    print(f"CI_APT_START command={command!r} hard_timeout={timeout}s idle_timeout={idle_timeout}s", flush=True)
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env, start_new_session=True, bufsize=0,
    )
    assert proc.stdout is not None
    started = last_output = time.monotonic()
    tail: deque[str] = deque(maxlen=64)
    try:
        while True:
            now = time.monotonic()
            elapsed, idle = now - started, now - last_output
            if elapsed >= timeout:
                raise CIAptCommandError(f"CI_APT_HARD_TIMEOUT after {elapsed:.1f}s: {command!r}")
            if idle >= idle_timeout and proc.poll() is None:
                raise CIAptCommandError(f"CI_APT_IDLE_TIMEOUT no output for {idle:.1f}s: {command!r}")
            ready, _, _ = select.select([proc.stdout], [], [], min(1.0, timeout - elapsed, max(0.01, idle_timeout - idle)))
            if ready:
                data = os.read(proc.stdout.fileno(), 8192)
                if data:
                    last_output = time.monotonic()
                    chunk = data.decode("utf-8", errors="replace")
                    print(chunk, end="", flush=True)
                    tail.append(chunk[-2048:])
                    continue
                # EOF means all output streams have closed. Still require the
                # exact process to exit successfully, not just to close stdout.
                try:
                    result = proc.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    raise CIAptCommandError("CI_APT_CHILD_DID_NOT_EXIT after output EOF") from exc
                if result != 0:
                    raise CIAptCommandError(f"CI_APT_EXIT_{result}: {command!r}\n{''.join(tail)[-4000:]}")
                print(f"CI_APT_SUCCESS elapsed={time.monotonic() - started:.1f}s", flush=True)
                return "".join(tail)
    except CIAptCommandError as exc:
        # Capture the blocking process/lock state *before* killing the CI-only
        # process group; the outer adapter also snapshots the final state.
        if "TIMEOUT" in str(exc) or "CHILD_DID_NOT_EXIT" in str(exc):
            print_apt_diagnostics()
        _terminate_group(proc)
        raise
    except BaseException:
        _terminate_group(proc)
        raise
    finally:
        proc.stdout.close()


def print_apt_diagnostics() -> None:
    """Read-only snapshot on error; never repair or alter package state."""
    for label, command in (
        ("apt-processes", ["/usr/bin/ps", "-eo", "pid,ppid,stat,etime,args"]),
        ("dpkg-audit", ["/usr/bin/dpkg", "--audit"]),
        ("apt-locks", ["/usr/bin/lslocks", "-n"]),
    ):
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
            output = completed.stdout + completed.stderr
            if label == "apt-processes":
                output = "\n".join(line for line in output.splitlines() if any(x in line.lower() for x in ("apt", "dpkg", "pid,ppid")))
            output = output[-5000:]
            print(f"CI_APT_DIAGNOSTIC {label} exit={completed.returncode}\n{output}", flush=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"CI_APT_DIAGNOSTIC {label} unavailable: {exc}", flush=True)
    try:
        from pathlib import Path
        log = Path("/var/log/apt/term.log")
        if log.exists():
            print("CI_APT_DIAGNOSTIC apt-term-log tail:\n" + log.read_text(encoding="utf-8", errors="replace")[-4000:], flush=True)
    except OSError as exc:
        print(f"CI_APT_DIAGNOSTIC apt-term-log unavailable: {exc}", flush=True)


def run_ci_apt(command: list[str], *, timeout: int = 600) -> str:
    """APT-only adapter for the canonical platform_prepare._run contract."""
    update = ["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "update"]
    install_prefix = [
        "/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120",
        "-y", "--no-install-recommends", "install",
    ]
    is_install = (command[:len(install_prefix)] == install_prefix
                  and len(command) > len(install_prefix)
                  and all(re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", name)
                          for name in command[len(install_prefix):]))
    if command != update and not is_install:
        raise CIAptCommandError("CI_APT_REJECTED noncanonical or unsupported command")
    limit = min(timeout, MAX_INSTALL_SECONDS if is_install else MAX_UPDATE_SECONDS)
    # Validate the exact production-shaped command *before* adding CI-only
    # transport settings.  Keep the host's signed repository and mirror list.
    bounded_command = [*command[:3], *CI_APT_NETWORK_OPTIONS, *command[3:]]
    try:
        return stream_command(bounded_command, timeout=limit)
    except (CIAptCommandError, OSError, subprocess.SubprocessError) as exc:
        print(f"CI_APT_FAILED: {exc}", flush=True)
        print_apt_diagnostics()
        raise
