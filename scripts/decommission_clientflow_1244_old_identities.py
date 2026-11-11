#!/usr/bin/env python3
"""Read-only by default: retire obsolete Heidi1/Viborg2 backend identities for 1244.

Never starts installation, deletes history, or alters the approved release.
Run from Render Shell with DISPLAY's local DB and normal display_app account.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from service1.clientflow_1244_identity_decommission import (  # noqa: E402
    APPROVAL_REFERENCE, IdentityResetDenied, RELEASE_ID, RELEASE_SHA256,
    RELEASE_SIZE, decommission, require_1244_paused, require_write_schema, snapshot,
)

STORE = Path("/var/data/clientflow-release-artifacts/store")


def verify_only_1244_artifact(store: Path) -> None:
    if not store.is_absolute() or store.is_symlink() or not store.is_dir():
        raise IdentityResetDenied("Invalid release-store directory")
    if store.stat().st_mode & 0o022:
        raise IdentityResetDenied("Release-store permissions are unsafe")
    files = sorted(p.name for p in store.iterdir() if p.name.startswith("clientflow-") and p.name.endswith(".tar"))
    if files != [f"{RELEASE_ID}.tar"]:
        raise IdentityResetDenied("Exact one-release 1244 store is required")
    p = store / files[0]
    st = p.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022:
        raise IdentityResetDenied("Approved bundle is not a secure regular file")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
            raise IdentityResetDenied("Approved bundle changed during verification")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            for chunk in iter(lambda: f.read(2 * 1024 * 1024), b""):
                digest.update(chunk)
        if opened.st_size != RELEASE_SIZE or digest.hexdigest() != RELEASE_SHA256:
            raise IdentityResetDenied("Approved 1244 bundle size/SHA-256 mismatch")
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=STORE)
    parser.add_argument("--confirm-decommission", action="store_true")
    parser.add_argument("--confirm-physical-wipe", action="store_true")
    parser.add_argument("--approval-reference", default="")
    args = parser.parse_args(argv)
    try:
        require_1244_paused()
        verify_only_1244_artifact(args.artifact_dir)
        # Imported only in Render's runtime with its pinned backend dependencies.
        from service1.db import engine
        write_requested = args.confirm_decommission or args.confirm_physical_wipe or bool(args.approval_reference)
        if write_requested:
            if not (args.confirm_decommission and args.confirm_physical_wipe
                    and args.approval_reference == APPROVAL_REFERENCE):
                raise IdentityResetDenied("Both confirmations and exact approval reference are required")
            with engine.begin() as conn:
                result = decommission(conn)
            # Independent read-back after commit, not just transactional assertions.
            with engine.connect() as conn:
                postflight = snapshot(conn)
            if not postflight["already_decommissioned"] or any(postflight["active_before_or_remaining"].values()):
                raise IdentityResetDenied("Independent postflight verification failed")
            print(json.dumps({"result":result, "independent_postflight":postflight},
                             sort_keys=True, ensure_ascii=False, indent=2, default=str))
            print("CLIENTFLOW_1244_IDENTITY_DECOMMISSION=PASS")
        else:
            with engine.connect() as conn:
                require_write_schema(conn)
                result = snapshot(conn)
            print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2, default=str))
            print("CLIENTFLOW_1244_IDENTITY_DECOMMISSION=READ_ONLY_PASS")
            print("CLIENTFLOW_1244_FRESH_INSTALL_RESUME=NOT_AUTHORIZED_HERE")
        return 0
    except (IdentityResetDenied, OSError, ValueError, TypeError, SQLAlchemyError) as exc:
        # Never print a DB statement, URL or parameter (may contain secrets).
        reason = type(exc).__name__ if isinstance(exc, SQLAlchemyError) else str(exc)
        print(f"CLIENTFLOW_1244_IDENTITY_DECOMMISSION=STOP: {reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
