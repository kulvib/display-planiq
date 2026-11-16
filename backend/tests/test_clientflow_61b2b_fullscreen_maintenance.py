"""61B-2B – host-free fullscreen notice safety and lifecycle tests.

No GTK, Wayland, systemctl, Chrome or real OS/firmware update is launched.
"""
from __future__ import annotations

from pathlib import Path
import os
import runpy
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'client/runtime'
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from clientflow_runtime import display_runtime, update_maintenance  # noqa: E402

SCREEN = ROOT / 'client/libexec/update-maintenance-screen'


@pytest.fixture
def screen_reader(monkeypatch, tmp_path):
    # run_path sets __name__ to <run_path>, therefore it cannot launch Gtk.
    namespace = runpy.run_path(str(SCREEN))
    # The function's globals are the namespace used during run_path execution.
    reader = namespace['_trusted_snapshot']
    glob = reader.__globals__
    directory = tmp_path / 'maintenance'
    directory.mkdir(mode=0o755)
    # CI runs as an unprivileged runner, while the real marker is required to
    # be root-owned. Simulate only filesystem ownership for the temporary test
    # files; keep real open(O_NOFOLLOW), mode and content checks in place.
    # NEVER weaken the production reader's root-ownership requirement.
    def root_metadata(info):
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_size=info.st_size)

    class RootOwnedDirectory:
        def lstat(self):
            return root_metadata(directory.lstat())

    class RootOwnedFileOperations:
        def __getattr__(self, key):
            return getattr(os, key)

        def fstat(self, descriptor):
            return root_metadata(os.fstat(descriptor))

    monkeypatch.setitem(glob, 'STATE_DIR', RootOwnedDirectory())
    monkeypatch.setitem(glob, 'STATE_PATH', directory / 'state.json')
    monkeypatch.setitem(glob, 'os', RootOwnedFileOperations())
    return reader, directory


def test_fullscreen_reader_only_uses_root_owned_validated_non_secret_fields(screen_reader):
    import json
    reader, directory = screen_reader
    path = directory / 'state.json'
    assert reader() is None
    path.write_text(json.dumps({
        'schema_version': 1, 'action': 'update_os',
        'phase': 'installing', 'command_id': 'secret-command-not-exposed',
    }), encoding='utf-8')
    path.chmod(0o644)
    assert reader() == {'action': 'Ubuntu', 'phase': 'installing'}
    path.write_text(json.dumps({'schema_version': 1, 'action': 'update_os', 'phase': 'completed'}))
    assert reader() is None


def test_fullscreen_untrusted_non_root_owned_directory_and_marker_fail_closed(screen_reader, monkeypatch):
    reader, directory = screen_reader
    marker = directory / 'state.json'
    marker.write_text('{"schema_version":1,"action":"update_os","phase":"installing"}')
    assert reader() == {'action': 'Ubuntu', 'phase': 'installing'}

    # On a real kiosk neither the directory nor the file may be user-owned.
    # The simulated metadata below must be rejected regardless of the runner UID.
    glob = reader.__globals__
    root_dir = glob['STATE_DIR']
    root_os = glob['os']
    monkeypatch.setitem(glob, 'STATE_DIR', SimpleNamespace(lstat=lambda: SimpleNamespace(
        st_uid=1234, st_mode=directory.lstat().st_mode,
    )))
    assert reader() == {'action': 'System', 'phase': 'recovery_required'}
    monkeypatch.setitem(glob, 'STATE_DIR', root_dir)

    class UntrustedFileOperations:
        def __getattr__(self, key):
            return getattr(root_os, key)

        def fstat(self, fd):
            original = root_os.fstat(fd)
            return SimpleNamespace(st_uid=1234, st_mode=original.st_mode, st_size=original.st_size)

    monkeypatch.setitem(glob, 'os', UntrustedFileOperations())
    assert reader() == {'action': 'System', 'phase': 'recovery_required'}


def test_fullscreen_invalid_symlink_or_world_writable_state_shows_recovery(screen_reader, tmp_path):
    reader, directory = screen_reader
    marker = directory / 'state.json'
    marker.write_text('not-json', encoding='utf-8')
    assert reader()['phase'] == 'recovery_required'
    marker.write_text('{"schema_version":1,"action":"update_clientflow","phase":"installing"}')
    assert reader()['phase'] == 'recovery_required'
    marker.chmod(0o666)
    assert reader()['phase'] == 'recovery_required'
    marker.unlink()
    outside = tmp_path / 'outside.json'
    outside.write_text('{"schema_version":1,"action":"update_os","phase":"completed"}')
    marker.symlink_to(outside)
    assert reader()['phase'] == 'recovery_required'


class FakeProcess:
    def __init__(self):
        self.is_running = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.is_running else 0

    def terminate(self):
        self.terminated = True
        self.is_running = False

    def wait(self, timeout=None):
        self.is_running = False
        return 0

    def kill(self):
        self.killed = True
        self.is_running = False


def _isolated_runtime():
    obj = display_runtime.DisplayRuntime.__new__(display_runtime.DisplayRuntime)
    obj.browser = None
    obj.maintenance_screen = None
    obj.next_maintenance_screen_attempt = 0.0
    obj.logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)
    obj._local_gui_environment = lambda: {'XDG_RUNTIME_DIR': '/fake-seat'}
    return obj


def test_active_update_starts_one_fullscreen_process_and_completion_closes_it(monkeypatch, tmp_path):
    script = tmp_path / 'update-maintenance-screen'
    script.write_text('# test helper, never launched\n')
    monkeypatch.setattr(display_runtime, 'MAINTENANCE_SCREEN_SCRIPT', script)
    monkeypatch.setattr(display_runtime, 'SYSTEM_PYTHON', Path('/usr/bin/python3'))
    active = [True]
    monkeypatch.setattr(update_maintenance, 'is_active', lambda: active[0])
    started = []

    def fake_popen(args, **kwargs):
        assert args == ['/usr/bin/python3', str(script)]
        assert kwargs['stdin'] is display_runtime.subprocess.DEVNULL
        assert kwargs['env']['XDG_RUNTIME_DIR'] == '/fake-seat'
        process = FakeProcess()
        started.append(process)
        return process

    monkeypatch.setattr(display_runtime.subprocess, 'Popen', fake_popen)
    runtime = _isolated_runtime()
    runtime._sync_maintenance_screen()
    assert len(started) == 1
    runtime._sync_maintenance_screen()
    assert len(started) == 1  # no duplicate/spam
    active[0] = False
    runtime._sync_maintenance_screen()
    assert started[0].terminated
    assert runtime.maintenance_screen is None


def test_screen_never_covers_browser_before_broker_stops_it(monkeypatch):
    monkeypatch.setattr(update_maintenance, 'is_active', lambda: True)
    monkeypatch.setattr(display_runtime.subprocess, 'Popen', lambda *_a, **_kw: pytest.fail('no overlay before browser stop'))
    runtime = _isolated_runtime()
    runtime.browser = FakeProcess()
    runtime._sync_maintenance_screen()
    assert runtime.maintenance_screen is None


def test_missing_wayland_screen_never_relaxes_maintenance_lock(monkeypatch, tmp_path):
    script = tmp_path / 'update-maintenance-screen'
    script.write_text('# stub\n')
    monkeypatch.setattr(display_runtime, 'MAINTENANCE_SCREEN_SCRIPT', script)
    monkeypatch.setattr(update_maintenance, 'is_active', lambda: True)
    runtime = _isolated_runtime()
    runtime._local_gui_environment = lambda: (_ for _ in ()).throw(RuntimeError('Wayland unavailable'))
    runtime._sync_maintenance_screen()
    assert runtime.maintenance_screen is None
    assert update_maintenance.is_active() is True
    assert runtime.next_maintenance_screen_attempt > 0


def test_source_cannot_authorize_client_release_or_bypass_reboot_gate():
    source = SCREEN.read_text(encoding='utf-8')
    assert 'window.fullscreen()' in source
    assert 'Gtk.Application' in source
    assert 'GDK_BACKEND' in source
    assert 'http://' not in source and 'https://' not in source
    assert 'os.system(' not in source and 'subprocess.' not in source
    runtime = (RUNTIME / 'clientflow_runtime/display_runtime.py').read_text(encoding='utf-8')
    assert '_sync_maintenance_screen()' in runtime
    assert 'if update_maintenance.is_active():' in runtime
    builder = (ROOT / 'client/release/lib/clientflow_release/builder.py').read_text(encoding='utf-8')
    assert 'client-runtime/libexec/update-maintenance-screen' in builder
