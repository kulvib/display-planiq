#!/usr/bin/env python3
"""68K-E4: operator-only closed 1250 control rebind and exact 1251 store rotation.

Dry run is the default. No client deployment, enrollment, recovery grant or
fleet change. Existing historical deployment and approval rows are preserved.
The filesystem and PostgreSQL are separate transactions: interruption is
resumable only from exact oldest-first suffixes of the pinned inventory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "client/release/lib")]

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402
from service1.audit import add_audit_log  # noqa: E402
from service1.client_presence import load_client_presence  # noqa: E402
from service1.clientflow_deployments import unacknowledged_recovery_failure  # noqa: E402
from service1.clientflow_pilot_1250 import approval_lock_1250  # noqa: E402
from service1.clientflow_pilot_1251 import (  # noqa: E402
    BASELINE_ID, BASELINE_VERSION, SUCCESSOR_ID, RETAINED_IDS, archive_inventory,
    approval_lock_1251, closed_baseline_catalog, require_closed_baseline,
    require_retained_store,
)
from service1.clientflow_release_admin_models import (  # noqa: E402
    ClientFlowReleaseControl, ClientFlowRolloutWave, ClientFlowRolloutTarget,
    ClientFlowPhysicalAcceptance,
)
from service1.clientflow_release_security_policy import require_centrally_eligible_release  # noqa: E402
from service1.clientflow_releases import load_catalog  # noqa: E402
from service1.clientflow_rollback_models import ClientFlowRollbackPermit  # noqa: E402
from service1.clientflow_update_models import (  # noqa: E402
    ClientFlowDeployment, ClientFlowUpdateCredential, ClientFlowUpdateProvisioningToken,
)
from service1.enrollment_models import ClientEnrollmentReceipt  # noqa: E402
from service1.models import Client, EnrollmentToken  # noqa: E402
from service1.native_rdp_admission import matches_completed_update  # noqa: E402
from service1.system_control import lock_system_client, active_system_command  # noqa: E402
from scripts.audit_clientflow_release_retention import inspect_store, verify_publication  # noqa: E402
from scripts.prune_clientflow_release_retention import prune_one_oldest  # noqa: E402
from scripts.publish_clientflow_release import publish  # noqa: E402

STORE = Path("/var/data/clientflow-release-artifacts/store")
OLD_ID = "clientflow-1.3.44-seq-1245"
OLD_SHA = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
REMOVE = ("clientflow-1.3.44-seq-1245", "clientflow-1.3.45-seq-1246", "clientflow-1.3.46-seq-1247")


class RotationDenied(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise RotationDenied(reason)


def remaining_rotation(snapshot, inventory):
    """Check all stored bytes and allow only exact resumable oldest-first states."""
    rows = snapshot["protected_latest"] + snapshot["older_review_only"]
    ids = set()
    for row in rows:
        identifier = row["release_id"]
        pin = inventory.get(identifier)
        require(identifier not in ids and pin is not None, "UNKNOWN_OR_DUPLICATE_ARTIFACT")
        require((row["size_bytes"], row["sha256"]) == (pin["size"], pin["sha256"]),
                "ARTIFACT_PROVENANCE_MISMATCH")
        ids.add(identifier)
    require(not snapshot["invalid_artifacts"] and len(ids) == snapshot["approved_count"],
            "INVALID_STORE")
    if ids == RETAINED_IDS:
        return [], True
    keep = RETAINED_IDS - {SUCCESSOR_ID}
    for index in range(len(REMOVE) + 1):
        if ids == keep | set(REMOVE[index:]):
            return list(REMOVE[index:]), False
    raise RotationDenied("UNEXPECTED_STORE_OR_NONCANONICAL_PARTIAL_ROTATION")


def _exists(session, query):
    return session.exec(query.limit(1)).first() is not None


def _control_and_dependencies(session):
    # All order writers use the same client/control row lock ordering.
    # No long-held database locks during network downloads.
    session.execute(text("SET LOCAL lock_timeout = '10s'"))
    session.execute(text("SET LOCAL statement_timeout = '30s'"))
    lock_system_client(session, 3)
    require(list(session.exec(select(Client.id).order_by(Client.id).limit(2)).all()) == [3],
            "CLIENT_INVENTORY_CHANGED")
    client = session.get(Client, 3)
    require(client is not None and client.name == "Viborg1" and client.status == "approved"
            and client.deleted_at is None and client.ubuntu_version == "26.04", "CLIENT_IDENTITY_CHANGED")
    presence = load_client_presence(session, client).status
    require(presence.is_online and presence.agent_version == BASELINE_VERSION, "FRESH_1250_STATUS_REQUIRED")
    control = session.exec(select(ClientFlowReleaseControl).where(
        ClientFlowReleaseControl.id == 1).with_for_update()).one_or_none()
    require(control is not None, "RELEASE_CONTROL_MISSING")
    approval = approval_lock_1250()
    old = (control.stable_release_id, control.stable_bundle_sha256, control.revision) == (OLD_ID, OLD_SHA, 1)
    new = (control.stable_release_id, control.stable_bundle_sha256, control.revision) == (
        BASELINE_ID, approval["approved_bundle_sha256"], 2)
    require(old or new, "UNEXPECTED_CONTROL_BINDING")
    projected = {**control.model_dump(), "stable_release_id": BASELINE_ID,
                 "stable_bundle_sha256": approval["approved_bundle_sha256"], "revision": 2}
    require_closed_baseline(load_catalog(), projected, 2)
    require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=1250)
    require_centrally_eligible_release(release_id=SUCCESSOR_ID, release_sequence=1251)
    require(not _exists(session, select(ClientFlowDeployment.id).where(
        ClientFlowDeployment.completed_at.is_(None))), "ACTIVE_DEPLOYMENT")
    require(not _exists(session, select(ClientFlowDeployment.id).where(
        ClientFlowDeployment.target_release_id == SUCCESSOR_ID)), "1251_ALREADY_ORDERED")
    require(unacknowledged_recovery_failure(session, client_id=3) is None, "UNACKNOWLEDGED_RECOVERY")
    require(active_system_command(session, 3) is None, "ACTIVE_SYSTEM_COMMAND")
    credentials = session.exec(select(ClientFlowUpdateCredential.id).where(
        ClientFlowUpdateCredential.client_id == 3,
        ClientFlowUpdateCredential.revoked_at.is_(None)).limit(2)).all()
    require(len(credentials) == 1, "UPDATE_IDENTITY_NOT_UNIQUE")
    prior = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.client_id == 3).order_by(
        ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()
    baseline = {"target_release_id": BASELINE_ID, "target_version": BASELINE_VERSION,
                "target_release_sequence": 1250, "bundle_sha256": approval["approved_bundle_sha256"],
                "bundle_size": approval["approved_bundle_size"],
                "release_approval_reference": approval["approval_reference"],
                "release_candidate_sha256": approval["candidate_sha256"], "source_commit": approval["source_commit"]}
    require(matches_completed_update(prior, client_id=3, artifact=baseline)
            and prior.observed_previous_release_id == "clientflow-1.3.47-seq-1248", "1250_PREDECESSOR_EVIDENCE_MISMATCH")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    require(not _exists(session, select(EnrollmentToken.id).where(
        EnrollmentToken.used_at.is_(None), EnrollmentToken.revoked_at.is_(None),
        EnrollmentToken.expires_at > now)), "LIVE_ENROLLMENT_TOKEN")
    require(not _exists(session, select(ClientEnrollmentReceipt.install_id).where(
        ClientEnrollmentReceipt.completed_at.is_(None), ClientEnrollmentReceipt.expires_at > now)),
        "UNFINISHED_ENROLLMENT")
    require(not _exists(session, select(ClientFlowUpdateProvisioningToken.id).where(
        ClientFlowUpdateProvisioningToken.used_at.is_(None), ClientFlowUpdateProvisioningToken.revoked_at.is_(None),
        ClientFlowUpdateProvisioningToken.expires_at > now)), "LIVE_UPDATE_PROVISIONING")
    require(not _exists(session, select(ClientFlowRollbackPermit.id).where(
        ClientFlowRollbackPermit.state == "issued", ClientFlowRollbackPermit.expires_at > now)), "LIVE_ROLLBACK_PERMIT")
    require(not _exists(session, select(ClientFlowRolloutTarget.id).where(
        ClientFlowRolloutTarget.state.in_(["approved", "consumed"]))), "ROLLOUT_TARGET_AUTHORITY")
    require(not _exists(session, select(ClientFlowRolloutWave.id).where(
        ClientFlowRolloutWave.state.in_(["approved", "running", "completed", "failed"]))), "ROLLOUT_WAVE_AUTHORITY")
    require(not _exists(session, select(ClientFlowRolloutWave.id).where(
        ClientFlowRolloutWave.state.in_(["draft", "paused"]), ClientFlowRolloutWave.expires_at > now)),
        "LIVE_DRAFT_OR_PAUSED_WAVE")
    require(not _exists(session, select(ClientFlowPhysicalAcceptance.id)), "UNEXPECTED_PHYSICAL_ACCEPTANCE")
    return control, old, projected


def verify_archive(pin, *, destination=None, opener=urlopen):
    """Stream exact public GitHub archive bytes; bounded length; no tokens."""
    url = pin["archive_url"]
    require(url.startswith("https://github.com/kulvib/display-planiq/releases/download/"), "UNTRUSTED_ARCHIVE_URL")
    digest = hashlib.sha256()
    count = 0
    with opener(url, timeout=60) as response:
        final = urlsplit(response.geturl())
        require(final.scheme == "https" and final.hostname in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
            "github-releases.githubusercontent.com"}, "UNTRUSTED_ARCHIVE_REDIRECT")
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            require(count <= pin["size"], "ARCHIVE_SIZE_EXCEEDED")
            digest.update(chunk)
            if destination is not None:
                destination.write(chunk)
    require(count == pin["size"] and digest.hexdigest() == pin["sha256"], "ARCHIVE_BYTES_MISMATCH")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-viborg1-local-preflight", action="store_true")
    args = parser.parse_args()
    require(args.apply == args.confirm_viborg1_local_preflight, "EXPLICIT_APPLY_AND_LOCAL_ATTESTATION_REQUIRED")
    require(ROOT == Path("/opt/display") and os.environ.get("CLIENTFLOW_RELEASE_ARTIFACT_DIR") == str(STORE),
            "WRONG_RENDER_SOURCE_OR_STORE")
    require(load_catalog() == closed_baseline_catalog(), "EXACT_CLOSED_CATALOG_REQUIRED")
    from service1.db import engine
    require(engine.dialect.name == "postgresql" and engine.url.database == "display"
            and engine.url.query.get("host") == "/run/display-postgres"
            and engine.url.host is None, "WRONG_LOCAL_DATABASE")
    inventory = archive_inventory()
    snapshot = inspect_store(STORE)
    remaining, published = remaining_rotation(snapshot, inventory)
    with Session(engine) as session, session.begin():
        _, old, _ = _control_and_dependencies(session)
        require(not old or not published and remaining == list(REMOVE), "OLD_CONTROL_REQUIRES_ORIGINAL_STORE")
    print(json.dumps({"mode": "apply" if args.apply else "dry_run",
        "control_rebind_required": old, "remaining_removals": remaining,
        "successor_published": published, "deployment_authorized": False}, sort_keys=True), flush=True)
    if not args.apply:
        print("ROTATION_PREFLIGHT=PASS; NO_MUTATION")
        return 0
    if published:
        require_retained_store()
        print("ROTATION_ALREADY_COMPLETE=PASS; DEPLOYMENT_AUTHORIZED=NO")
        return 0

    # Archive proof FIRST, including the new artifact; retain no temporary
    # archive on the PostgreSQL/release disk. No GitHub token is needed.
    temp_root = Path("/tmp")
    require(temp_root.stat().st_dev != STORE.stat().st_dev, "TEMP_ON_PERSISTENT_STORE")
    require(shutil.disk_usage(temp_root).free >= inventory[SUCCESSOR_ID]["size"] + 64 * 1024 * 1024,
            "INSUFFICIENT_EPHEMERAL_DISK")
    with tempfile.TemporaryDirectory(prefix="clientflow-1251-", dir=temp_root) as tmp:
        for identifier in REMOVE:
            verify_archive(inventory[identifier])
            print(f"ARCHIVE_BYTES_VERIFIED={identifier}", flush=True)
        bundle = Path(tmp) / "approved-1251.tar"
        with bundle.open("xb") as target:
            verify_archive(inventory[SUCCESSOR_ID], destination=target)
            target.flush()
            os.fsync(target.fileno())
        print(f"ARCHIVE_BYTES_VERIFIED={SUCCESSOR_ID}", flush=True)

        # Recheck after network I/O, then rebind closed control atomically.
        remaining, published = remaining_rotation(inspect_store(STORE), inventory)
        require(not published, "CONCURRENT_PUBLICATION")
        with Session(engine) as session, session.begin():
            control, old, projected = _control_and_dependencies(session)
            require(not old or remaining == list(REMOVE), "OLD_CONTROL_REQUIRES_ORIGINAL_STORE")
            if old:
                control.stable_release_id = projected["stable_release_id"]
                control.stable_bundle_sha256 = projected["stable_bundle_sha256"]
                control.revision = 2
                control.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                control.updated_by_user_id = None  # Render operator, not an impersonated HTTP user.
                session.add(control)
                add_audit_log(session, action="clientflow_closed_baseline_rebound",
                    entity_type="clientflow_release_control", entity_id=1,
                    entity_label="1245 → closed 1250", severity="critical", is_critical=True,
                    details={"authority": "render_operator_shell", "old_release_id": OLD_ID,
                             "new_release_id": BASELINE_ID, "revision": 2, "fleet_open": False,
                             "fresh_install_open": False, "cutover_enabled": False,
                             "deployment_authorized": False})
        print("CLOSED_CONTROL_REBIND=PASS", flush=True)

        for identifier in remaining:
            # Existing prune locks and checks the exact oldest inode/bytes;
            # DB row locks prevent concurrent System/deployment orders.
            with Session(engine) as session, session.begin():
                _, old, _ = _control_and_dependencies(session)
                require(not old, "CONTROL_REBIND_NOT_COMMITTED")
                result = prune_one_oldest(STORE, expected_release_id=identifier,
                    expected_sha256=inventory[identifier]["sha256"], confirm_prune=True,
                    confirm_no_dependencies=True)
                require(result["deleted"] is True, "PRUNE_DID_NOT_COMPLETE")
            print(json.dumps(result, sort_keys=True), flush=True)
        rest, already = remaining_rotation(inspect_store(STORE), inventory)
        require(not rest and not already, "EXPECTED_TWO_PREDECESSORS")
        approval = approval_lock_1251()
        with Session(engine) as session, session.begin():
            _, old, _ = _control_and_dependencies(session)
            require(not old, "CONTROL_REBIND_NOT_COMMITTED")
            path, size, digest = publish(bundle, STORE,
                expected_bundle_sha256=approval["approved_bundle_sha256"],
                expected_approval_reference=approval["approval_reference"],
                expected_source_commit=approval["source_commit"])
            require(path.stem == SUCCESSOR_ID and size == approval["approved_bundle_size"],
                    "PUBLICATION_IDENTITY_MISMATCH")
            verify_publication(STORE, release_id=SUCCESSOR_ID, size_bytes=size, sha256=digest)
            require_retained_store()
            add_audit_log(session, action="clientflow_1251_store_rotation",
                entity_type="clientflow_release_control", entity_id=1,
                entity_label="1248 / 1250 / 1251", severity="critical", is_critical=True,
                details={"authority": "render_operator_shell", "retained": sorted(RETAINED_IDS),
                         "github_archives_verified": list(REMOVE), "bundle_sha256": digest,
                         "deployment_authorized": False})
    print(json.dumps(inspect_store(STORE), sort_keys=True), flush=True)
    print("ROTATION=PASS; RELEASE_COUNT=3; DEPLOYMENT_AUTHORIZED=NO")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never echo credential-bearing DB URLs, response headers, or secrets.
        reason = str(exc) if isinstance(exc, RotationDenied) else type(exc).__name__
        print("ROTATION_STOP=" + reason, file=sys.stderr, flush=True)
        raise SystemExit(2)
