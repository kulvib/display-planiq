"""61B-2F read-only local preflight never performs any host action."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import json

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/clientflow_61b2f_pilot_preflight_readonly.py'
spec = importlib.util.spec_from_file_location('pilot_readonly', SCRIPT)
preflight = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(preflight)
RELEASE = 'clientflow-1.3.45-seq-1246'


def seeded_host(tmp_path):
    release = tmp_path / 'opt/clientflow/releases' / RELEASE
    (release / 'client-runtime/libexec').mkdir(parents=True)
    source = release / 'client-runtime/libexec/update-maintenance-screen'
    source.write_bytes(b'#!/usr/bin/python3\nprint("no network")\n')
    active = tmp_path / 'opt/clientflow/active'
    active.symlink_to('releases/' + RELEASE)
    screen = tmp_path / 'usr/lib/clientflow/maintenance/host-screen'
    screen.parent.mkdir(parents=True)
    screen.write_bytes(source.read_bytes())
    unit = tmp_path / 'etc/systemd/system/planiq-display-maintenance.service'
    unit.parent.mkdir(parents=True)
    unit.write_text('''[Service]
User=clientflow-kiosk
ExecStart=/usr/bin/python3 -I /usr/lib/clientflow/maintenance/host-screen --supervisor
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX
ProtectSystem=strict
''')
    return tmp_path, source, screen, unit


def test_readonly_preflight_never_declares_backend_or_physical_authorization(tmp_path, monkeypatch):
    root, _src, screen, unit = seeded_host(tmp_path)
    before = {p: p.read_bytes() for p in (screen, unit)}
    report = preflight.inspect(root)
    assert report['schema_version'] == 1
    assert report['deployment_authorized'] is False
    assert report['pilot_accepted'] is False
    assert report['result'] == 'STOP'  # no real physical service test
    assert report['checks']['active_release_identity']['pass'] is True
    assert report['checks']['host_screen_matches_signed_release']['pass'] is True
    assert report['checks']['host_service_unit']['pass'] is True
    assert report['checks']['host_service_running']['detail'] == 'not_physically_verified'
    assert {p: p.read_bytes() for p in (screen, unit)} == before
    assert not (root / 'var/lib/clientflow/install-coordinator').exists()


def test_preflight_blocks_current_installer_and_recovery_marker(tmp_path):
    root, *_ = seeded_host(tmp_path)
    coord = root / 'var/lib/clientflow/install-coordinator/state.json'
    coord.parent.mkdir(parents=True)
    coord.write_text(json.dumps({'schema_version': 1, 'owner': 'update_os', 'operation_id': 'uuid'}))
    system = root / 'var/lib/clientflow/update-maintenance/state.json'
    system.parent.mkdir(parents=True)
    system.write_text(json.dumps({'schema_version': 1, 'phase': 'recovery_required'}))
    report = preflight.inspect(root)
    assert not report['checks']['no_active_installation']['pass']
    assert not report['checks']['system_update_idle']['pass']
    assert report['result'] == 'STOP'


def test_preflight_blocks_tampered_host_screen_and_symlink_unit(tmp_path):
    root, source, screen, unit = seeded_host(tmp_path)
    screen.write_bytes(b'tampered')
    unit.unlink()
    unit.symlink_to(root / 'outside')
    report = preflight.inspect(root)
    assert not report['checks']['host_screen_matches_signed_release']['pass']
    assert not report['checks']['host_service_unit']['pass']
    assert report['result'] == 'STOP'


def test_preflight_blocks_outside_active_release_symlink(tmp_path):
    root, *_ = seeded_host(tmp_path)
    link = root / 'opt/clientflow/active'
    link.unlink()
    link.symlink_to('../../outside')
    report = preflight.inspect(root)
    assert not report['checks']['active_release_identity']['pass']
    assert report['result'] == 'STOP'


def test_preflight_rejects_relative_root(tmp_path):
    with pytest.raises(ValueError, match='absolute'):
        preflight.inspect(Path('relative-path'))
