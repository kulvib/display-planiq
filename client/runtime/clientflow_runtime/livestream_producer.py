"""Generation-bound GNOME Mutter/PipeWire HLS producer.

The lifecycle watcher remains a hardened system service with no backend
credential. The actual desktop-capture child is dropped to the active local
Wayland user so it can use that GNOME session's Mutter ScreenCast D-Bus API and
PipeWire stream without an interactive XDG ScreenCast portal dialog.
"""
from __future__ import annotations

import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import stat
import subprocess
import time
from typing import Any
import uuid

from .atomic import atomic_write_json
from .livestream_paths import CONFIG_PATH, DESIRED_PATH, GENERATIONS_DIR, PRODUCER_STATUS_PATH, STATE_DIR
from .logging_utils import configure_logging

CONTROL_GROUP = "clientflow-livestream-control"
SETACL = Path("/usr/bin/setfacl")
SETPRIV = Path("/usr/bin/setpriv")
LOGINCTL = Path("/usr/bin/loginctl")
SYSTEM_PYTHON = Path("/usr/bin/python3")
CAPTURE_HELPER = Path(__file__).with_name("livestream_wayland_capture.py")

# Retrying a broken Mutter/PipeWire source every ~25 seconds did not yield
# frames in the 2026-11-14 pilot. Back off without restarting GNOME, PipeWire
# or the kiosk, and always remain responsive to a stop/new generation.
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 120
HEALTHY_RESET_SECONDS = 180


def retry_delay_seconds(attempt: int) -> int:
    """Bounded exponential retry interval; no unbounded integer exponentiation."""
    return min(RETRY_BASE_SECONDS * (2 ** min(max(attempt - 1, 0), 5)), RETRY_MAX_SECONDS)


def capture_source_mode(retries: int) -> str:
    """Keep the fast path; change PipeWire negotiation only after a failed attempt."""
    return "normal" if retries <= 0 else "bounded"


class Producer:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.livestream.producer")
        self.process: subprocess.Popen[bytes] | None = None
        self.generation_id: str | None = None
        self._last_start_attempt = 0.0
        self._retry_generation: str | None = None
        self._retry_attempts = 0
        self._retry_deadline = 0.0
        self._healthy_since: float | None = None

    def _reset_retry(self, generation_id: str | None) -> None:
        self._retry_generation = generation_id
        self._retry_attempts = 0
        self._retry_deadline = 0.0
        self._healthy_since = None

    def _schedule_retry(self, reason: str) -> None:
        # Only code-owned reason labels are admitted; no raw GStreamer debug,
        # signed media URLs or HTTP exception messages enter the status JSON.
        if reason not in {"startup_failed", "capture_exited"}:
            raise ValueError("Unknown capture retry reason")
        self._retry_attempts = getattr(self, "_retry_attempts", 0) + 1
        delay = retry_delay_seconds(self._retry_attempts)
        self._retry_deadline = time.monotonic() + delay
        next_retry_at = time.time() + delay
        self.logger.warning(
            "capture_retry_scheduled",
            extra={"event": "capture_retry", "attempt": self._retry_attempts,
                   "retry_after_seconds": delay, "reason": reason},
        )
        self._status(
            "retrying", reason=reason, attempt=self._retry_attempts,
            retry_after_seconds=delay, next_retry_at=next_retry_at,
            next_source_mode=capture_source_mode(self._retry_attempts),
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ugyldig JSON: {path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"JSON skal være et objekt: {path}")
        return value

    def _status(self, state: str, **details: Any) -> None:
        atomic_write_json(
            PRODUCER_STATUS_PATH,
            {
                "schema_version": 1,
                "state": state,
                "generation_id": self.generation_id,
                "pid": self.process.pid if self.process and self.process.poll() is None else None,
                "capture_backend": "wayland_mutter_pipewire",
                "updated_at": time.time(),
                **details,
            },
            mode=0o640,
        )

    def _stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        self._status("stopped")
        self.generation_id = None

    def _session_properties(self, session_id: str) -> dict[str, str]:
        result = subprocess.run(
            [
                str(LOGINCTL),
                "show-session",
                session_id,
                "--no-pager",
                "-p", "Active",
                "-p", "Remote",
                "-p", "Type",
                "-p", "State",
                "-p", "Name",
                "-p", "Seat",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        return values

    def _resolve_wayland_user(self) -> tuple[str, int, int, str, Path]:
        if not LOGINCTL.is_file():
            raise RuntimeError("loginctl mangler")
        result = subprocess.run(
            [str(LOGINCTL), "list-sessions", "--no-legend", "--no-pager"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError("Kunne ikke læse grafiske login-sessioner")
        candidates: list[tuple[int, str, dict[str, str]]] = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields:
                continue
            session_id = fields[0]
            properties = self._session_properties(session_id)
            if (
                properties.get("Active") != "yes"
                or properties.get("Remote") == "yes"
                or properties.get("Type") != "wayland"
                or properties.get("State") not in {"active", "online"}
            ):
                continue
            name = properties.get("Name") or ""
            if not name:
                continue
            priority = 0 if properties.get("Seat") == "seat0" else 1
            candidates.append((priority, session_id, properties))
        if not candidates:
            raise RuntimeError("Ingen aktiv lokal Wayland-session")
        candidates.sort(key=lambda item: (item[0], item[1]))
        properties = candidates[0][2]
        username = properties["Name"]
        try:
            account = pwd.getpwnam(username)
        except KeyError as exc:
            raise RuntimeError("Wayland-sessionens bruger findes ikke lokalt") from exc
        runtime_dir = Path(f"/run/user/{account.pw_uid}")
        if not (runtime_dir / "bus").exists():
            raise RuntimeError("Wayland-sessionens D-Bus er ikke klar")
        return username, account.pw_uid, account.pw_gid, account.pw_dir, runtime_dir

    def _control_gid(self) -> int:
        try:
            return grp.getgrnam(CONTROL_GROUP).gr_gid
        except KeyError as exc:
            raise RuntimeError(f"Gruppen {CONTROL_GROUP} mangler") from exc

    def _acl_traverse(self, username: str, path: Path) -> None:
        if not SETACL.is_file():
            raise RuntimeError("setfacl mangler")
        result = subprocess.run(
            [str(SETACL), "-m", f"u:{username}:--x", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Kunne ikke sætte afgrænset ACL på {path}: {result.stderr.strip()}")

    def _prepare_capture_state(self, username: str, uid: int) -> Path:
        """Create a private per-user cache area without granting home write access."""
        control_gid = self._control_gid()
        capture_root = STATE_DIR / "capture"
        user_root = capture_root / str(uid)
        capture_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(capture_root, 0, control_gid)
        os.chmod(capture_root, 0o750)
        self._acl_traverse(username, STATE_DIR)
        self._acl_traverse(username, capture_root)
        user_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(user_root, uid, control_gid)
        os.chmod(user_root, 0o700)
        cache_dir = user_root / "cache"
        cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(cache_dir, uid, control_gid)
        os.chmod(cache_dir, 0o700)
        return cache_dir

    def _prune_retired_generations(self, generation_id: str) -> None:
        """Keep current and one most recent retired generation on the host."""
        root = GENERATIONS_DIR
        metadata = root.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0
                or metadata.st_mode & 0o022 or not shutil.rmtree.avoids_symlink_attacks):
            raise RuntimeError("Ubetroet Livestream generationlager")
        retired = []
        for child in root.iterdir():
            if child.name == generation_id:
                continue
            try:
                if str(uuid.UUID(child.name)) != child.name:
                    continue
            except ValueError:
                continue
            meta = child.lstat()
            if stat.S_ISDIR(meta.st_mode):
                retired.append((meta.st_mtime_ns, child.name, child))
            elif stat.S_ISLNK(meta.st_mode):
                raise RuntimeError("Ubetroet Livestream generationsti")
        for _, _, path in sorted(retired, reverse=True)[1:]:
            shutil.rmtree(path)


    def _prepare_output(self, generation_id: str, username: str, uid: int) -> Path:
        control_gid = self._control_gid()
        GENERATIONS_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(GENERATIONS_DIR, 0, control_gid)
        os.chmod(GENERATIONS_DIR, 0o750)
        self._acl_traverse(username, STATE_DIR)
        self._acl_traverse(username, GENERATIONS_DIR)
        self._prune_retired_generations(generation_id)

        generation = GENERATIONS_DIR / generation_id
        output = generation / "out"
        generation.mkdir(mode=0o750, parents=True, exist_ok=True)
        if not stat.S_ISDIR(generation.lstat().st_mode):
            raise RuntimeError("Ubetroet Livestream generationsti")
        os.chown(generation, uid, control_gid)
        os.chmod(generation, 0o750)
        output.mkdir(mode=0o750, parents=True, exist_ok=True)
        if not stat.S_ISDIR(output.lstat().st_mode):
            raise RuntimeError("Ubetroet Livestream outputsti")
        os.chown(output, uid, control_gid)
        os.chmod(output, 0o2750)
        for child in output.iterdir():
            if child.is_symlink():
                child.unlink()
            elif child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
        return output

    def _configuration(self) -> tuple[int, int, str, int, int]:
        configuration = self._read_json(CONFIG_PATH)
        if configuration.get("schema_version") != 1:
            raise RuntimeError("Livestreamkonfiguration mangler schema_version 1")
        backend = str(configuration.get("capture_backend") or "wayland_mutter")
        if backend != "wayland_mutter":
            raise RuntimeError("capture_backend skal være wayland_mutter")
        fps = int(configuration.get("fps", 10))
        bitrate_kbit = int(configuration.get("bitrate_kbit", 12000))
        preset = str(configuration.get("preset") or "veryfast")
        segment_seconds = int(configuration.get("segment_seconds", 1))
        playlist_size = int(configuration.get("playlist_size", 8))
        if not 1 <= fps <= 30:
            raise RuntimeError("fps er ugyldig")
        if not 1000 <= bitrate_kbit <= 50000:
            raise RuntimeError("bitrate_kbit er ugyldig")
        if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
            raise RuntimeError("preset er ugyldig")
        if not 1 <= segment_seconds <= 10:
            raise RuntimeError("segment_seconds er ugyldig")
        if not 3 <= playlist_size <= 30:
            raise RuntimeError("playlist_size er ugyldig")
        return fps, bitrate_kbit, preset, segment_seconds, playlist_size

    def _wait_ready(self, output: Path, timeout: float = 25.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self.process
            if process is None:
                raise RuntimeError("Wayland capture-processen forsvandt")
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"Wayland capture-processen stoppede med exit code {code}")
            playlist = output / "index.m3u8"
            if playlist.is_file() and any(output.glob("segment-*.ts")):
                return
            time.sleep(0.25)
        raise RuntimeError(f"Wayland capture blev ikke HLS-klar inden for {timeout:g} sekunder")

    def _start(self, generation_id: str) -> None:
        try:
            uuid.UUID(generation_id)
        except ValueError as exc:
            raise RuntimeError("Ugyldig livestreamgeneration") from exc
        for binary in (SETPRIV, SYSTEM_PYTHON, CAPTURE_HELPER):
            if binary.is_symlink() and binary != CAPTURE_HELPER:
                # System binaries may be usr-merged symlinks on some systems; regular existence is enough.
                pass
            if not binary.exists():
                raise RuntimeError(f"Påkrævet fil mangler: {binary}")

        fps, bitrate_kbit, preset, segment_seconds, playlist_size = self._configuration()
        # Explicit opt-in only; preserve existing segment choices. A failed
        # dual-branch attempt falls back to the established HLS-only pipeline.
        continuous = (self._read_json(CONFIG_PATH).get("continuous_wss") is True
                      and segment_seconds == 1)
        username, uid, gid, home, runtime_dir = self._resolve_wayland_user()
        cache_dir = self._prepare_capture_state(username, uid)
        environment = {
            "HOME": home,
            "USER": username,
            "LOGNAME": username,
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "XDG_CACHE_HOME": str(cache_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
            "XDG_SESSION_TYPE": "wayland",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }

        # The backend agent waits for a real HLS segment before acknowledging
        # /started. Do a single bounded fallback *within* this claim/lease;
        # deferring it to the next retry would fail the backend command first.
        retries = getattr(self, "_retry_attempts", 0)
        modes = ("normal", "bounded") if retries == 0 else ("bounded",)
        for source_mode in modes:
            output = self._prepare_output(generation_id, username, uid)
            command = [
                str(SETPRIV),
                f"--reuid={uid}",
                f"--regid={gid}",
                "--init-groups",
                "--",
                str(SYSTEM_PYTHON),
                "-B",
                str(CAPTURE_HELPER),
                "--output", str(output),
                "--fps", str(fps),
                "--bitrate-kbit", str(bitrate_kbit),
                "--preset", preset,
                "--segment-seconds", str(segment_seconds),
                "--playlist-size", str(playlist_size),
                "--source-mode", source_mode,
            ]
            continuous_attempt = continuous and retries == 0 and source_mode == "normal"
            if continuous_attempt:
                command.append("--continuous")
            self.generation_id = generation_id
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=None,
                stderr=None,
                env=environment,
                cwd="/",
                start_new_session=True,
                close_fds=True,
            )
            self._status(
                "starting",
                source_mode=source_mode,
                graphical_user=username,
                fps=fps,
                bitrate_kbit=bitrate_kbit,
                preset=preset,
                segment_seconds=segment_seconds,
                playlist_size=playlist_size,
            )
            # A first cold boot should usually yield the first 2s segment
            # quickly; reserve time for the bounded-mode attempt under the
            # agent's command timeout and its existing 60s lease keeper.
            timeout = 12.0 if source_mode == "normal" else (14.0 if len(modes) == 2 else 25.0)
            try:
                self._wait_ready(output, timeout=timeout)
            except Exception as exc:
                # Terminate the child and close the previous Mutter session
                # before starting a second one; never overlap captures.
                self._stop()
                self.generation_id = generation_id
                if (
                    source_mode == "normal"
                    and isinstance(exc, RuntimeError)
                    and (continuous_attempt or str(exc).startswith("Wayland capture blev ikke HLS-klar inden for"))
                ):
                    self.logger.warning(
                        "capture_startup_bounded_fallback",
                        extra={"event": "capture_fallback", "source_mode": "bounded"},
                    )
                    continue
                raise
            self._status(
                "running",
                source_mode=source_mode,
                graphical_user=username,
                fps=fps,
                bitrate_kbit=bitrate_kbit,
                preset=preset,
                segment_seconds=segment_seconds,
                playlist_size=playlist_size,
            )
            return

    def run(self) -> int:
        self._status("stopped")
        try:
            while True:
                desired = self._read_json(DESIRED_PATH)
                wanted = desired.get("desired")
                generation = str(desired.get("generation_id") or "")
                if wanted == "running" and generation:
                    if getattr(self, "_retry_generation", None) != generation:
                        self._reset_retry(generation)

                    now = time.monotonic()
                    if self.process is not None:
                        exit_code = self.process.poll()
                        if exit_code is not None:
                            # The systemd unit can remain active after its
                            # unprivileged capture subprocess has failed.
                            self.logger.warning(
                                "capture_process_exited",
                                extra={"event": "capture_exit", "exit_code": exit_code},
                            )
                            self._status("failed", exit_code=exit_code)
                            self.process = None  # poll() already reaped the child
                            self._healthy_since = None
                            self._schedule_retry("capture_exited")
                        elif (
                            self._healthy_since is not None
                            and now - self._healthy_since >= HEALTHY_RESET_SECONDS
                        ):
                            # A short-lived successful first segment is not
                            # enough to reset a persistent crash loop.
                            self._retry_attempts = 0
                            self._retry_deadline = 0.0
                            self._healthy_since = None

                    if self.generation_id != generation:
                        self._stop()
                    if self.process is None and now >= getattr(self, "_retry_deadline", 0.0):
                        self._last_start_attempt = now
                        self._stop()
                        try:
                            self._start(generation)
                            self._healthy_since = time.monotonic()
                        except Exception as exc:
                            self.logger.exception("producer_start_failed")
                            self.generation_id = generation
                            self._status(
                                "failed", error=str(exc)[:1000],
                                source_mode=capture_source_mode(self._retry_attempts),
                            )
                            self._healthy_since = None
                            self._schedule_retry("startup_failed")
                else:
                    if self.process is not None or self.generation_id is not None:
                        self._stop()
                    if getattr(self, "_retry_generation", None) is not None:
                        self._reset_retry(None)
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
        finally:
            self._stop()


def main() -> int:
    return Producer().run()
