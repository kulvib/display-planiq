#!/usr/bin/env python3
"""68N-D1: operator-only exact 1248/1250/1251 -> 1250/1251/1252 rotation.

Dry run by default. Separate explicit operator local-dependency attestation.
No control rebind, catalog changes, deployment orders or new client authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "client/release/lib")]

from sqlmodel import Session, select  # noqa: E402
from service1.audit import add_audit_log  # noqa: E402
from service1.clientflow_1252_transition import CANDIDATE_ID, OLDEST_ID  # noqa: E402
from service1.clientflow_pilot_1252 import (  # noqa: E402
    FINAL_IDS, approval_lock_1252, match_candidate_manifest, require_rotated_store,
    rotation_inventory, rotation_state,
)
from service1.clientflow_release_security_policy import require_centrally_eligible_release  # noqa: E402
from service1.clientflow_update_models import ClientFlowDeployment  # noqa: E402
from scripts.audit_clientflow_release_retention import inspect_store, verify_publication  # noqa: E402
from scripts.promote_clientflow_1251_closed_standard import (  # noqa: E402
    _control_and_dependencies as closed_1251_dependencies,
)
from scripts.reconcile_clientflow_1251_store import (  # noqa: E402
    STORE, RotationDenied, require, verify_archive,
)
from scripts.prune_clientflow_release_retention import prune_one_oldest  # noqa: E402
from scripts.publish_clientflow_release import publish  # noqa: E402
from clientflow_release.bundle import open_verified_bundle  # noqa: E402
from clientflow_release.constants import INSTALL_MODE_UPDATE  # noqa: E402


def require_dependencies(session):
    # Reuse the complete verified 1250 -> 1251 history, fresh Viborg1
    # status, local PostgreSQL control locks and no outstanding authority.
    control, mode, latest = closed_1251_dependencies(session, apply=True)
    require(mode == "bound" and control.revision == 3, "CLOSED_1251_REVISION_3_REQUIRED")
    require_centrally_eligible_release(release_id=CANDIDATE_ID, release_sequence=1252)
    require(session.exec(select(ClientFlowDeployment.id).where(
        (ClientFlowDeployment.target_release_id == CANDIDATE_ID)
        | (ClientFlowDeployment.target_release_sequence == 1252)
        | (ClientFlowDeployment.target_version == "1.4.2")
    ).limit(1)).first() is None, "1252_ALREADY_ORDERED")
    return latest


def verify_staged_candidate(bundle):
    manifest, _payload, size, digest, handle = open_verified_bundle(
        bundle, require_deployable=True, required_install_mode=INSTALL_MODE_UPDATE)
    try:
        match_candidate_manifest(manifest, size=size, digest=digest)
    finally:
        handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-viborg1-local-preflight", action="store_true")
    args = parser.parse_args()
    require(args.apply == args.confirm_viborg1_local_preflight,
            "EXPLICIT_APPLY_AND_LOCAL_ATTESTATION_REQUIRED")
    require(ROOT == Path("/opt/display") and os.environ.get("CLIENTFLOW_RELEASE_ARTIFACT_DIR") == str(STORE),
            "WRONG_RENDER_SOURCE_OR_STORE")
    from service1.db import engine
    require(engine.dialect.name == "postgresql" and engine.url.database == "display"
            and engine.url.query.get("host") == "/run/display-postgres"
            and engine.url.host is None, "WRONG_LOCAL_DATABASE")
    inventory = rotation_inventory()
    initial = rotation_state(inspect_store(STORE))
    with Session(engine) as session, session.begin():
        require_dependencies(session)
    print(json.dumps({"mode": "apply" if args.apply else "dry_run",
                      "store_state": initial, "control_revision": 3,
                      "deployment_authorized": False}, sort_keys=True), flush=True)
    if not args.apply:
        print("ROTATION_PREFLIGHT=PASS; NO_MUTATION")
        return 0
    if initial == "published":
        require_rotated_store()
        print("ROTATION_ALREADY_COMPLETE=PASS; DEPLOYMENT_AUTHORIZED=NO")
        return 0

    temp_root = Path("/tmp")
    require(temp_root.stat().st_dev != STORE.stat().st_dev, "TEMP_ON_PERSISTENT_STORE")
    require(shutil.disk_usage(temp_root).free >= inventory[CANDIDATE_ID]["size"] + 64 * 1024 * 1024,
            "INSUFFICIENT_EPHEMERAL_DISK")
    with tempfile.TemporaryDirectory(prefix="clientflow-1252-", dir=temp_root) as tmp:
        # Even on retry from the two-release state, prove the removed
        # predecessor remains externally retrievable. Never use metadata only.
        verify_archive(inventory[OLDEST_ID])
        print(f"ARCHIVE_BYTES_VERIFIED={OLDEST_ID}", flush=True)
        bundle = Path(tmp) / "approved-1252.tar"
        with bundle.open("xb") as target:
            verify_archive(inventory[CANDIDATE_ID], destination=target)
            target.flush()
            os.fsync(target.fileno())
        verify_staged_candidate(bundle)
        print(f"ARCHIVE_BYTES_AND_MANIFEST_VERIFIED={CANDIDATE_ID}", flush=True)
        # Re-evaluate the exact state and all DB dependencies after download.
        # The existing prune/publish helpers own immutable-store file locks.
        with Session(engine) as session, session.begin():
            require_dependencies(session)
            state = rotation_state(inspect_store(STORE))
            require(state == initial, "CONCURRENT_STORE_CHANGE")
            if state == "original":
                result = prune_one_oldest(STORE, expected_release_id=OLDEST_ID,
                    expected_sha256=inventory[OLDEST_ID]["sha256"], confirm_prune=True,
                    confirm_no_dependencies=True)
                require(result["deleted"] is True, "PRUNE_DID_NOT_COMPLETE")
                print(json.dumps(result, sort_keys=True), flush=True)
            require(rotation_state(inspect_store(STORE)) == "pruned", "EXPECTED_TWO_PREDECESSORS")
            approval = approval_lock_1252()
            path, size, digest = publish(bundle, STORE,
                expected_bundle_sha256=approval["approved_bundle_sha256"],
                expected_approval_reference=approval["approval_reference"],
                expected_source_commit=approval["source_commit"])
            require(path.stem == CANDIDATE_ID and size == approval["approved_bundle_size"]
                    and digest == approval["approved_bundle_sha256"], "PUBLICATION_IDENTITY_MISMATCH")
            verify_publication(STORE, release_id=CANDIDATE_ID, size_bytes=size, sha256=digest)
            require(rotation_state(inspect_store(STORE)) == "published", "FINAL_STORE_MISMATCH")
            require_rotated_store()
            add_audit_log(session, action="clientflow_1252_store_rotation",
                entity_type="clientflow_release_control", entity_id=1,
                entity_label="1250 / 1251 / 1252", severity="critical", is_critical=True,
                details={"authority": "render_operator_shell", "retained": sorted(FINAL_IDS),
                         "github_archives_verified": [OLDEST_ID, CANDIDATE_ID],
                         "bundle_sha256": digest, "revision": 3, "deployment_authorized": False})
    print("ROTATION=PASS; RELEASE_COUNT=3; DEPLOYMENT_AUTHORIZED=NO")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RotationDenied) else type(exc).__name__
        print("ROTATION_STOP=" + reason, file=sys.stderr, flush=True)
        raise SystemExit(2)
