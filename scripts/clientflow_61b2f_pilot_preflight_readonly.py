#!/usr/bin/env python3
"""61B-2F: strictly observational, offline pilot preflight (NOT authorization).

Never changes client, firmware, service, release, database, lock or gate state.
Run with sudo only on a designated, physically attended test kiosk AFTER the
new signed release has been installed through the separately approved process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

RELEASE_PATTERN = re.compile(r'clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*\Z')
SCREEN = '/usr/lib/clientflow/maintenance/host-screen'
UNIT = '/etc/systemd/system/planiq-display-maintenance.service'
COORD = '/var/lib/clientflow/install-coordinator/state.json'
SYSTEM = '/var/lib/clientflow/update-maintenance/state.json'
RELEASE = '/var/lib/clientflow/release-status/state.json'
ACTIVE = '/opt/clientflow/active'


def _safe_file(path: Path, *, max_bytes: int = 8192, require_root: bool = True) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
                or info.st_size > max_bytes or (require_root and info.st_uid != 0)):
            raise ValueError('untrusted_file')
        content = os.read(fd, max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError('oversized_file')
        return content
    finally:
        os.close(fd)


def _status_marker(path: Path, *, active_phases: set[str], root_owner: bool) -> bool:
    try:
        value = json.loads(_safe_file(path, require_root=root_owner))
    except FileNotFoundError:
        return False
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('invalid_status_schema')
    phase = value.get('phase')
    if not isinstance(phase, str):
        raise ValueError('invalid_status_phase')
    return phase in active_phases or phase not in {'completed', 'rolled_back', 'cancelled'}


def _active_release(root: Path) -> str:
    link = root / ACTIVE.lstrip('/')
    if not link.is_symlink():
        raise ValueError('active_release_link_missing')
    # No resolve() to silently follow an untrusted chain outside the release root.
    target = os.readlink(link)
    if not target.startswith('releases/') or target.count('/') != 1:
        raise ValueError('active_release_link_outside_canonical_tree')
    release_id = target.removeprefix('releases/')
    if not RELEASE_PATTERN.fullmatch(release_id):
        raise ValueError('invalid_active_release_id')
    candidate = root / 'opt/clientflow/releases' / release_id
    if not candidate.is_dir() or candidate.is_symlink():
        raise ValueError('active_release_tree_missing')
    return release_id


def _service_state() -> tuple[bool, str]:
    for command in ('is-enabled', 'is-active'):
        try:
            result = subprocess.run(
                ['/usr/bin/systemctl', command, 'planiq-display-maintenance.service'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=10, check=False, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
            )
        except (OSError, subprocess.SubprocessError):
            return False, 'unavailable'
        expected = 'enabled' if command == 'is-enabled' else 'active'
        if result.returncode != 0 or result.stdout.strip() != expected:
            return False, 'not_' + expected
    return True, 'running_enabled'


def inspect(root: Path = Path('/'), *, physically_verify_service: bool = True) -> dict:
    if not root.is_absolute():
        raise ValueError('preflight_root_must_be_absolute')
    # There is deliberately no mutation, login, network access or unlock API.
    checks: dict[str, dict] = {}
    is_host = root == Path('/')
    def record(key: str, fn):
        try:
            detail = fn()
            checks[key] = {'pass': True, 'detail': detail}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            checks[key] = {'pass': False, 'detail': type(exc).__name__}

    record('active_release_identity', lambda: _active_release(root))

    def verify_screen():
        host = _safe_file(root / SCREEN.lstrip('/'), max_bytes=1024 * 1024,
                          require_root=is_host)
        active_id = _active_release(root)
        from_release = root / 'opt/clientflow/releases' / active_id / 'client-runtime/libexec/update-maintenance-screen'
        signed = _safe_file(from_release, max_bytes=1024 * 1024, require_root=is_host)
        if hashlib.sha256(host).digest() != hashlib.sha256(signed).digest():
            raise ValueError('host_screen_differs_from_active_signed_release')
        return 'matches_active_release'
    record('host_screen_matches_signed_release', verify_screen)

    def verify_unit():
        raw = _safe_file(root / UNIT.lstrip('/'), max_bytes=16384, require_root=is_host)
        required = (b'User=', b'ExecStart=/usr/bin/python3 -I /usr/lib/clientflow/maintenance/host-screen --supervisor',
                    b'NoNewPrivileges=yes', b'RestrictAddressFamilies=AF_UNIX',
                    b'ProtectSystem=strict')
        if any(item not in raw for item in required) or b'@CLIENTFLOW_KIOSK_' in raw:
            raise ValueError('host_service_contract_invalid')
        return 'hardened_host_service_present'
    record('host_service_unit', verify_unit)

    def check_lock():
        path = root / COORD.lstrip('/')
        try:
            _safe_file(path, max_bytes=4096, require_root=is_host)
        except FileNotFoundError:
            return 'no_durable_operation_recorded'
        raise ValueError('installation_active_or_in_doubt')
    record('no_active_installation', check_lock)

    def check_status(path: str, phases: set[str]):
        marker = root / path.lstrip('/')
        if _status_marker(marker, active_phases=phases, root_owner=is_host):
            raise ValueError('update_or_recovery_active')
        return 'no_active_update_or_recovery'
    record('system_update_idle', lambda: check_status(
        SYSTEM, {'browser_stopping', 'installing', 'rebooting', 'post_boot_check', 'recovery_required'}))
    record('clientflow_update_idle', lambda: check_status(
        RELEASE, {'preparing', 'staging', 'activating', 'post_activation_check', 'rolling_back', 'recovery_required'}))

    if physically_verify_service and is_host:
        success, detail = _service_state()
        checks['host_service_running'] = {'pass': success, 'detail': detail}
    else:
        checks['host_service_running'] = {'pass': False, 'detail': 'not_physically_verified'}
    ready = all(row['pass'] for row in checks.values())
    return {
        'schema_version': 1,
        'kind': 'offline_readonly_pilot_preflight',
        'result': 'READY_FOR_PHYSICAL_OBSERVATION' if ready else 'STOP',
        'deployment_authorized': False,
        'pilot_accepted': False,
        'checks': checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only pilot host preflight; never authorizes a release')
    parser.add_argument('--root', type=Path, default=Path('/'))
    args = parser.parse_args()
    report = inspect(args.root)
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if report['result'] == 'READY_FOR_PHYSICAL_OBSERVATION' else 2


if __name__ == '__main__':
    raise SystemExit(main())
