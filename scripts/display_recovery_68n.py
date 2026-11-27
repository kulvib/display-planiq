#!/usr/bin/env python3
"""68N-B1: version-bound recovery, explicit operator actions only.

Reuses the private 62B stage format. No API, secret export, deployment,
release promotion or restore into a running Display database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time

from display_62b_backup_evidence import (
    capture, verify, _hash_regular, _safe_dir, _open_regular,
)

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend/service1"
MOUNT = Path("/var/data/clientflow-release-artifacts")
SOCKET = Path("/run/display-postgres")
PROFILE_ID = "closed-1251-r3"
# Profiles are code-reviewed source, never accepted from a backup or CLI path.
# Preserve this registry entry and immutable pinned files on future releases.
PROFILES = {
    PROFILE_ID: (
        "display_recovery_closed_1251_r3.json",
        "clientflow_release_catalog_1251_closed.stage.json",
        "clientflow_1251_archive_inventory.json",
        "clientflow_pilot_1251_approval.json",
    ),
}
FALSE_GATES = dict(offsite_verified=False, publisher_signatures_verified=False,
                   client_reconnect_verified=False, recovery_acceptance_verified=False,
                   deployment_authorized=False, cutover_authorized=False)


class RecoveryStop(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise RecoveryStop(reason)


def read_json(path, expected=None):
    fd, info = _open_regular(path)
    with os.fdopen(fd, "rb") as stream:
        require(0 < info.st_size <= 65536, "JSON_SIZE")
        raw = stream.read(65537)
    require(len(raw) <= 65536, "JSON_SIZE")
    if expected is not None:
        require(hashlib.sha256(raw).hexdigest() == expected, "SOURCE_PIN")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    obj = json.loads(raw, object_pairs_hook=unique)
    require(type(obj) is dict, "JSON_OBJECT")
    return obj


def profile(profile_id=PROFILE_ID):
    require(profile_id in PROFILES, "UNKNOWN_PROFILE")
    filename, catalog_file, inventory_file, approval_file = PROFILES[profile_id]
    p = read_json(ROOT / "scripts" / filename, "f4c4bfa5f3f9230886749bc66cc34ba1ad4edd791ed5067e7004061b0b696329")
    require(p["schema"] == 1 and p["profile_id"] == profile_id, "PROFILE_ID")
    catalog = read_json(SERVICE / catalog_file, p["catalog_sha256"])
    inventory = read_json(SERVICE / inventory_file, p["archive_inventory_sha256"])["releases"]
    approval = read_json(SERVICE / approval_file, p["approval_sha256"])
    ids = p["retained_release_ids"]
    require(type(ids) is list and len(ids) == len(set(ids)) == 3, "PROFILE_RETENTION")
    stable = p["stable_release_id"]
    require(ids[-1] == stable and approval["release_id"] == stable
            and approval["approved"] is True, "PROFILE_APPROVAL")
    require(len(catalog["releases"]) == 1 and catalog["releases"][0]["release_id"] == stable
            and catalog["releases"][0]["rollback_allowed"] is False
            and catalog["catalog_sequence"] == inventory[stable]["sequence"], "PROFILE_CATALOG")
    rows = {rid + ".tar": (inventory[rid]["sha256"], inventory[rid]["size"]) for rid in ids}
    require(rows[stable + ".tar"] == (approval["approved_bundle_sha256"],
            approval["approved_bundle_size"]), "PROFILE_ARTIFACT")
    for sha, size in rows.values():
        require(re.fullmatch(r"[a-f0-9]{64}", sha) is not None
                and type(size) is int and size > 0, "PROFILE_ARTIFACT")
    require(type(p["revision"]) is int and p["revision"] > 0
            and re.fullmatch(r"[A-Za-z0-9_]+", p["migration"]) is not None
            and re.fullmatch(r"clientflow-\d+\.\d+\.\d+-seq-\d+", stable) is not None
            and re.fullmatch(r"postgres:18\.\d+@sha256:[a-f0-9]{64}", p["postgres_image"]) is not None,
            "PROFILE_FIELDS")
    return p, rows


def policy_sql(p, rows):
    # All interpolated values come only from the reviewed profile and pinned
    # source inventory. Never construct SQL from an archive manifest.
    stable = p["stable_release_id"]
    sha = rows[stable + ".tar"][0]
    return f"""SELECT CASE WHEN
      (SELECT count(*) FROM public.alembic_version) = 1
      AND EXISTS (SELECT 1 FROM public.alembic_version WHERE version_num = '{p["migration"]}')
      AND (SELECT count(*) FROM public.clientflow_release_control) = 1
      AND EXISTS (SELECT 1 FROM public.clientflow_release_control
        WHERE id = 1 AND revision = {p["revision"]} AND stable_release_id = '{stable}'
        AND stable_bundle_sha256 = '{sha}'
        AND fresh_install_open IS FALSE AND fleet_open IS FALSE AND cutover_enabled IS FALSE)
      AND NOT EXISTS (SELECT 1 FROM public.clientflow_deployment WHERE completed_at IS NULL)
      THEN 'PASS' ELSE 'STOP' END;"""


def private_stage(path):
    _safe_dir(path, private=True)
    require(not any(path == r or r in path.parents for r in (MOUNT, SOCKET, Path("/opt/display"))),
            "LIVE_PATH_FORBIDDEN")


def verify_stage(stage, p, rows):
    private_stage(stage)
    # Strictly parse before the legacy verifier; reject duplicate JSON keys.
    manifest = read_json(stage / "manifest.json")
    require(manifest.get("stable_release_id") == p["stable_release_id"], "STABLE_ID")
    require(manifest.get("stable_sha256") == rows[p["stable_release_id"] + ".tar"][0], "STABLE_SHA")
    records = manifest.get("releases")
    require(type(records) is list and len(records) == len(rows), "EXACT_INVENTORY")
    require(all(type(r) is dict and set(r) == {"filename", "sha256", "size"}
                and type(r["size"]) is int for r in records), "INVENTORY_FIELDS")
    require({r["filename"]: (r["sha256"], r["size"]) for r in records} == rows, "EXACT_INVENTORY")
    _safe_dir(stage / "releases", private=True)
    for path in [stage / "manifest.json", stage / "database.pgdump",
                 *(stage / "releases" / name for name in rows)]:
        fd, info = _open_regular(path)
        os.close(fd)
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, "PRIVATE_FILE_REQUIRED")
    require(verify(stage)["stage_bytes_hash_verified"] is True, "STAGE_VERIFY")
    return dict(profile=p["profile_id"], stage_bytes_verified=True,
                retained_release_count=len(rows), isolated_database_restore_verified=False, **FALSE_GATES)


def run(argv, *, stdin=None, timeout=60):
    # Do not expose subprocess diagnostics: dumps and SQL may contain secrets.
    result = subprocess.run(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    require(result.returncode == 0, "SUBPROCESS_FAILED")
    return result.stdout.decode("utf-8").strip()


def local_policy(p, rows):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"}
    env["PGCONNECT_TIMEOUT"] = "5"
    argv = ["gosu", "display_app", "psql", "-XAt", "--no-password", "-v", "ON_ERROR_STOP=1",
            "-h", str(SOCKET), "-U", "display_app", "-d", "display", "-c",
            "BEGIN READ ONLY; SET LOCAL statement_timeout='15s'; " + policy_sql(p, rows) + " COMMIT;"]
    result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30, check=False)
    require(result.returncode == 0 and result.stdout.decode().splitlines() == ["BEGIN", "SET", "PASS", "COMMIT"],
            "LIVE_POLICY")


def verify_store(rows):
    _safe_dir(MOUNT / "store")
    require({x.name for x in (MOUNT / "store").iterdir() if x.name.endswith(".tar")} == set(rows),
            "STORE_INVENTORY")
    for name, identity in rows.items():
        require(_hash_regular(MOUNT / "store" / name) == identity, "STORE_BYTES")


def capture_current(parent, p, rows):
    require(ROOT == Path("/opt/display") and os.geteuid() == 0 and SOCKET.is_dir(), "WRONG_HOST")
    private_stage(parent)
    require(parent.stat().st_dev != MOUNT.stat().st_dev, "STAGING_ON_LIVE_DISK")
    require(_hash_regular(SERVICE / "clientflow_release_catalog.json")[0] == p["catalog_sha256"],
            "ACTIVE_CATALOG")
    require(os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") == "1"
            and os.environ.get("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false").lower() == "false",
            "ENVIRONMENT_NOT_CLOSED")
    # Conservative headroom: all retained TARs plus current database size and
    # 128 MiB. This is a precheck, not a guarantee of filesystem quota.
    dbsize = subprocess.run(["gosu", "display_app", "psql", "-XAt", "--no-password",
        "-h", str(SOCKET), "-U", "display_app", "-d", "display", "-c",
        "SELECT pg_database_size(current_database())"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("PG")})
    require(dbsize.returncode == 0 and dbsize.stdout.strip().isdigit(), "DB_SIZE_UNKNOWN")
    require(shutil.disk_usage(parent).free >= sum(s for _, s in rows.values()) +
            int(dbsize.stdout) * 2 + 128 * 1024 * 1024, "STAGE_CAPACITY")
    local_policy(p, rows)
    verify_store(rows)
    stable = p["stable_release_id"]
    sha, size = rows[stable + ".tar"]
    result = capture(MOUNT, parent, release_id=stable, expected_sha256=sha, expected_size=size)
    stage = Path(result["stage"])
    try:
        verify_stage(stage, p, rows)
        local_policy(p, rows)
        verify_store(rows)
    except BaseException:
        # Only the directory exclusively created by capture can be removed.
        shutil.rmtree(stage)
        raise
    return dict(stage=str(stage), capture_verified=True,
                cross_store_atomic_snapshot_verified=False, **FALSE_GATES)


def offline_restore(stage, p, rows):
    require(not MOUNT.exists() and not SOCKET.exists(), "LIVE_HOST_FORBIDDEN")
    evidence = verify_stage(stage, p, rows)
    # Explicit local daemon, never a remote DOCKER_HOST or context.
    docker = ["docker", "--host", "unix:///var/run/docker.sock"]
    image = p["postgres_image"]
    run([*docker, "image", "inspect", image])
    name = "display-recovery-" + secrets.token_hex(12)
    secret = secrets.token_urlsafe(36)
    container = run([*docker, "run", "-d", "--pull=never", "--network", "none",
                     "--name", name, "-e", "POSTGRES_PASSWORD=" + secret, image], timeout=120)
    require(re.fullmatch(r"[a-f0-9]{64}", container) is not None, "CONTAINER_ID")
    started = time.monotonic()
    try:
        for attempt in range(90):
            try:
                run([*docker, "exec", "-u", "postgres", container, "pg_isready", "-q",
                     "-U", "postgres", "-d", "postgres"], timeout=5)
                break
            except RecoveryStop:
                if attempt == 89:
                    raise
                time.sleep(1)
        run([*docker, "exec", "-u", "postgres", container, "createdb", "-U", "postgres", "display_restore"])
        fd, _ = _open_regular(stage / "database.pgdump")
        with os.fdopen(fd, "rb") as dump:
            run([*docker, "exec", "-i", "-u", "postgres", container, "pg_restore",
                 "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl",
                 "-U", "postgres", "-d", "display_restore"], stdin=dump, timeout=1800)
        require(run([*docker, "exec", "-u", "postgres", container, "psql", "-XAt",
                     "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "display_restore",
                     "-c", policy_sql(p, rows)]) == "PASS", "RESTORED_POLICY")
        verify_stage(stage, p, rows)
        evidence.update(isolated_database_restore_verified=True,
                        restore_elapsed_seconds=round(time.monotonic() - started, 2))
    finally:
        run([*docker, "rm", "--force", "--volumes", container], timeout=120)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=PROFILE_ID, choices=PROFILES)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--inspect-profile", action="store_true")
    modes.add_argument("--policy-sql", action="store_true")
    modes.add_argument("--verify-stage", type=Path)
    modes.add_argument("--capture-to", type=Path)
    modes.add_argument("--offline-restore", type=Path)
    parser.add_argument("--confirm-private-staging", action="store_true")
    args = parser.parse_args()
    require(bool(args.capture_to) == args.confirm_private_staging, "EXPLICIT_CAPTURE_ATTESTATION")
    p, rows = profile(args.profile)
    if args.policy_sql:
        print(policy_sql(p, rows))
        return 0
    if args.inspect_profile:
        result = dict(profile=p, retained_files=rows, **FALSE_GATES)
    elif args.capture_to:
        result = capture_current(args.capture_to, p, rows)
    elif args.verify_stage:
        result = verify_stage(args.verify_stage, p, rows)
    else:
        result = offline_restore(args.offline_restore, p, rows)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RecoveryStop, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, RuntimeError) as exc:
        # Exception messages from lower layers may include private paths.
        print("68N_RECOVERY_STOP=" + (str(exc) if type(exc) is RecoveryStop else type(exc).__name__),
              file=sys.stderr)
        raise SystemExit(2)
