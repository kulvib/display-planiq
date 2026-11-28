"""Read-only native RDP release eligibility, separate from transport authority.

No credential, session or tunnel is issued here. Fleet eligibility is consumed
only by authenticated managed-session admission and bounded revalidation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from .client_presence import load_client_presence
from .clientflow_deployments import active_deployment, unacknowledged_recovery_failure
from .clientflow_release_artifacts import _artifact_path
from .clientflow_release_admin_models import ClientFlowPhysicalAcceptance, ClientFlowReleaseControl
from .clientflow_release_security_policy import require_centrally_eligible_release
from .clientflow_releases import deployment_release_snapshot, load_catalog, resolve_release
from .clientflow_pilot_1250 import (
    approval_lock_1250, match_approved_artifact, pilot_release, require_pilot_holds,
)
from .clientflow_standard_release import (
    BASELINE_ID, BASELINE_SEQUENCE, BASELINE_VERSION, require_cutover_authority,
)
from .clientflow_update_models import ClientFlowDeployment, ClientFlowDeploymentEvent
from .clientflow_pilot_1251 import (
    SUCCESSOR_ID, SUCCESSOR_VERSION, SUCCESSOR_SEQUENCE, require_closed_baseline,
    successor_release, match_successor_artifact, match_successor_order, closed_baseline_catalog,
)
from .clientflow_closed_standard_1251 import (
    require_closed_standard_control, require_completed_successor,
)
from .enrollment_models import ClientEnrollmentReceipt
from .models import Client, EnrollmentToken
from .remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential


def _artifact_fingerprint(path: Path) -> tuple:
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid)


@lru_cache(maxsize=2)
def _verified_baseline_artifact(path: Path, fingerprint: tuple, physical_test: bool = False) -> dict:
    release = pilot_release() if physical_test else resolve_release(BASELINE_VERSION)
    if (release.get("release_id") != BASELINE_ID or release.get("version") != BASELINE_VERSION
            or release.get("release_sequence") != BASELINE_SEQUENCE):
        raise ValueError("baseline identity mismatch")
    artifact = deployment_release_snapshot(release)
    if _artifact_path(BASELINE_ID) != path or _artifact_fingerprint(path) != fingerprint:
        raise ValueError("artifact changed during verification")
    return {**artifact, "target_version": BASELINE_VERSION,
            "target_release_sequence": BASELINE_SEQUENCE}


def canonical_baseline_artifact(*, physical_test: bool = False) -> dict:
    # Do not rehash hundreds of MB on every session recheck. File replacement,
    # mutation, permission change or deletion invalidates cached verification.
    path = _artifact_path(BASELINE_ID)
    fingerprint = _artifact_fingerprint(path)
    artifact = _verified_baseline_artifact(path, fingerprint, physical_test)
    if _artifact_fingerprint(path) != fingerprint:
        raise ValueError("artifact changed after verification")
    return dict(artifact)


def matches_completed_update(row: Any, *, client_id: int, artifact: dict) -> bool:
    return bool(row is not None
        and row.client_id == client_id and row.state == "succeeded" and row.completed_at is not None
        and row.target_release_id == row.observed_release_id == artifact["target_release_id"]
        and row.target_release_sequence == row.observed_release_sequence == artifact["target_release_sequence"]
        and row.target_version == artifact["target_version"]
        and row.bundle_sha256 == artifact["bundle_sha256"] and row.bundle_size == artifact["bundle_size"]
        and row.release_approval_reference == artifact["release_approval_reference"]
        and row.release_candidate_sha256 == artifact["release_candidate_sha256"]
        and row.source_commit == artifact["source_commit"])


def matches_completed_enrollment(token: Any, receipt: Any, *, client: Client, artifact: dict) -> bool:
    return bool(token is not None and receipt is not None
        and token.id == client.enrollment_token_id and token.used_by_client_id == client.id
        and token.used_at is not None and token.revoked_at is None
        and receipt.client_id == client.id and receipt.completed_at is not None
        and token.fresh_install_release_id == artifact["target_release_id"]
        and token.fresh_install_version == artifact["target_version"]
        and token.fresh_install_release_sequence == artifact["target_release_sequence"]
        and token.fresh_install_bundle_sha256 == artifact["bundle_sha256"]
        and token.fresh_install_bundle_size == artifact["bundle_size"]
        and token.fresh_install_approval_reference == artifact["release_approval_reference"]
        and token.fresh_install_candidate_sha256 == artifact["release_candidate_sha256"]
        and token.fresh_install_source_commit == artifact["source_commit"])


@lru_cache(maxsize=2)
def _verified_successor_artifact(path: Path, fingerprint: tuple) -> dict:
    artifact = {**deployment_release_snapshot(successor_release()),
                "target_version": SUCCESSOR_VERSION, "target_release_sequence": SUCCESSOR_SEQUENCE}
    match_successor_artifact(artifact)
    if _artifact_path(SUCCESSOR_ID) != path or _artifact_fingerprint(path) != fingerprint:
        raise ValueError("successor artifact changed during verification")
    return artifact


def canonical_successor_artifact() -> dict:
    path = _artifact_path(SUCCESSOR_ID)
    fingerprint = _artifact_fingerprint(path)
    artifact = _verified_successor_artifact(path, fingerprint)
    if _artifact_fingerprint(path) != fingerprint:
        raise ValueError("successor artifact changed after verification")
    return dict(artifact)


def _closed_baseline_eligibility(session, *, client, catalog, control, latest, version):
    require_closed_baseline(catalog, control.model_dump(), control.revision)
    if client.id != 3 or client.name != "Viborg1" or client.ubuntu_version != "26.04":
        return "cutover_closed"
    baseline = canonical_baseline_artifact(physical_test=True)
    match_approved_artifact(approval_lock_1250(), baseline)
    require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=BASELINE_SEQUENCE)
    if version == BASELINE_VERSION and matches_completed_update(latest, client_id=3, artifact=baseline):
        return "physical_test_eligible"
    if not match_successor_order(latest, client_id=3) or latest.completed_at is None:
        return "update_evidence_mismatch"
    predecessors = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.client_id == 3,
        ClientFlowDeployment.target_release_id == BASELINE_ID,
    ).limit(2)).all()
    if len(predecessors) != 1 or not matches_completed_update(predecessors[0], client_id=3, artifact=baseline):
        return "update_evidence_mismatch"
    if version == SUCCESSOR_VERSION:
        require_centrally_eligible_release(release_id=SUCCESSOR_ID, release_sequence=SUCCESSOR_SEQUENCE)
        artifact = canonical_successor_artifact()
        return ("physical_test_eligible" if latest.observed_previous_release_id == BASELINE_ID
                and matches_completed_update(latest, client_id=3, artifact=artifact)
                else "update_evidence_mismatch")
    if version != BASELINE_VERSION:
        return "canonical_runtime_unavailable"
    if latest.state in {"failed", "cancelled"}:
        # These terminal states precede activation; fresh 1250 presence and
        # exact historical successful deployment still have to match.
        return "physical_test_eligible"
    if latest.state == "rolled_back":
        rows = session.exec(select(ClientFlowDeploymentEvent).where(
            ClientFlowDeploymentEvent.deployment_id == latest.id,
            ClientFlowDeploymentEvent.event_type == "rolled_back",
        ).limit(2)).all()
        if (len(rows) == 1 and rows[0].credential_id is not None
                and rows[0].payload.get("failed_release_id") == SUCCESSOR_ID
                and rows[0].payload.get("restored_release_id") == BASELINE_ID):
            return "physical_test_eligible"
    # Never infer recovery from a reported version following recovery_failed.
    return "update_evidence_mismatch"


@lru_cache(maxsize=2)
def _verified_1252_artifact(path: Path, fingerprint: tuple) -> dict:
    from .clientflow_pilot_1252 import candidate_release, match_candidate_artifact
    artifact = {**deployment_release_snapshot(candidate_release()),
                "target_version": "1.4.2", "target_release_sequence": 1252}
    match_candidate_artifact(artifact)
    if _artifact_fingerprint(path) != fingerprint:
        raise ValueError("1252 artifact changed during verification")
    return artifact


def canonical_1252_artifact() -> dict:
    from .clientflow_1252_transition import CANDIDATE_ID
    path = _artifact_path(CANDIDATE_ID)
    fingerprint = _artifact_fingerprint(path)
    artifact = _verified_1252_artifact(path, fingerprint)
    if _artifact_path(CANDIDATE_ID) != path or _artifact_fingerprint(path) != fingerprint:
        raise ValueError("1252 artifact changed after verification")
    return dict(artifact)


def _candidate_1252_eligibility(session, *, latest, version):
    from .clientflow_1252_authority import require_candidate_access, require_candidate_history, recovery_events, RECOVERY_PAYLOAD
    from .clientflow_1252_transition import PREDECESSOR_ID
    require_candidate_access(session, latest)
    require_candidate_history(session, latest)
    if version == "1.4.2":
        artifact = canonical_1252_artifact()
        return ("physical_test_eligible" if latest.observed_previous_release_id == PREDECESSOR_ID
                and matches_completed_update(latest, client_id=3, artifact=artifact)
                else "update_evidence_mismatch")
    if version != SUCCESSOR_VERSION or latest.state not in {"failed", "cancelled", "rolled_back"}:
        return "update_evidence_mismatch"
    events = recovery_events(session, latest)
    if (len(events) != 1 or events[0].credential_id is not None or events[0].payload != RECOVERY_PAYLOAD
            or events[0].received_at < latest.completed_at):
        return "update_evidence_mismatch"
    match_successor_artifact(canonical_successor_artifact())
    return "physical_test_eligible"


def _closed_standard_eligibility(session, *, client, catalog, control, latest, version):
    # A closed selector is not a fleet grant. Preserve only the exact
    # already installed Viborg1 across the old/new control binding.
    require_closed_standard_control(catalog, control.model_dump(), allow_predecessor=True)
    if client.id != 3 or client.name != "Viborg1" or client.ubuntu_version != "26.04":
        return "cutover_closed"
    from .clientflow_1252_transition import is_candidate_order
    if latest is not None and is_candidate_order(latest):
        return _candidate_1252_eligibility(session, latest=latest, version=version)
    if version != SUCCESSOR_VERSION:
        return "cutover_closed"
    predecessors = session.exec(select(ClientFlowDeployment).where(
        ClientFlowDeployment.client_id == 3,
        ClientFlowDeployment.target_release_id == BASELINE_ID,
    ).limit(2)).all()
    if len(predecessors) != 1:
        return "update_evidence_mismatch"
    require_completed_successor(latest, predecessors[0], client_id=3)
    require_centrally_eligible_release(release_id=SUCCESSOR_ID, release_sequence=SUCCESSOR_SEQUENCE)
    match_successor_artifact(canonical_successor_artifact())
    return "physical_test_eligible"


ADMITTED_RELEASE_MODES = frozenset({"eligible", "physical_test_eligible", "legacy_pilot_eligible"})


def release_eligibility(session: Session, *, client_id: int) -> str:
    """Return a bounded reason code; unknown evidence never implies eligibility."""
    if type(client_id) is not int or client_id <= 0:
        return "invalid_identity"
    client = session.get(Client, client_id)
    rd_client = session.get(RemoteDesktopClient, client_id)
    if (client is None or client.deleted_at is not None or client.status != "approved"
            or rd_client is None or rd_client.status != "approved"):
        return "client_not_approved"
    credential = session.exec(select(RemoteDesktopCredential.id).where(
        RemoteDesktopCredential.client_id == client_id,
        RemoteDesktopCredential.revoked_at.is_(None),
    )).first()
    if credential is None:
        return "credential_unavailable"
    control = session.get(ClientFlowReleaseControl, 1)
    if control is None:
        return "cutover_closed"
    try:
        catalog = load_catalog()
        if (active_deployment(session, client_id=client_id) is not None
                or unacknowledged_recovery_failure(session, client_id=client_id) is not None):
            return "installation_in_progress_or_failed"
        presence = load_client_presence(session, client).status
        if not presence.is_online:
            return "canonical_runtime_unavailable"
        latest = session.exec(select(ClientFlowDeployment).where(
            ClientFlowDeployment.client_id == client_id,
        ).order_by(ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()
        if catalog.get("catalog_sequence") == SUCCESSOR_SEQUENCE:
            return _closed_standard_eligibility(session, client=client, catalog=catalog,
                control=control, latest=latest, version=presence.agent_version)
        if control.stable_release_id != BASELINE_ID:
            # Closed historical policy is not a fleet grant. Only the exact
            # existing physical test host may cross the pre-acceptance boundary.
            # During the closed catalog/control rebind, preserve only the
            # already proven 1250 physical host. Do not revive 1248 admission
            # or create any deployment from the historical catalog.
            if catalog.get("catalog_sequence") == BASELINE_SEQUENCE:
                from .clientflow_release_pilot_stage_1248 import load_staged_catalog_1248
                if catalog != closed_baseline_catalog() or presence.agent_version != BASELINE_VERSION:
                    return "cutover_closed"
                require_pilot_holds(load_staged_catalog_1248(), control.model_dump(), control.revision)
            else:
                require_pilot_holds(catalog, control.model_dump(), control.revision)
            if client_id != 3 or client.name != "Viborg1" or client.ubuntu_version != "26.04":
                return "cutover_closed"
            if presence.agent_version == "1.3.47":
                require_centrally_eligible_release(release_id="clientflow-1.3.47-seq-1248", release_sequence=1248)
                if latest is not None and latest.target_release_sequence >= BASELINE_SEQUENCE:
                    return "update_evidence_mismatch"
                return "legacy_pilot_eligible"
            if presence.agent_version != BASELINE_VERSION:
                return "canonical_runtime_unavailable"
            # Physical test must precede physical acceptance, but not signed
            # artifact approval, successful deployment or canonical presence.
            approval = approval_lock_1250()
            artifact = canonical_baseline_artifact(physical_test=True)
            match_approved_artifact(approval, artifact)
            require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=BASELINE_SEQUENCE)
            return ("physical_test_eligible" if matches_completed_update(latest, client_id=client_id, artifact=artifact)
                    else "update_evidence_mismatch")
        if control.cutover_enabled is False and control.fleet_open is False:
            return _closed_baseline_eligibility(session, client=client, catalog=catalog,
                control=control, latest=latest, version=presence.agent_version)
        if control.cutover_enabled is not True or control.fleet_open is not True:
            return "cutover_closed"
        if presence.agent_version != BASELINE_VERSION:
            return "canonical_runtime_unavailable"
        artifact = canonical_baseline_artifact()
        require_centrally_eligible_release(release_id=BASELINE_ID, release_sequence=BASELINE_SEQUENCE)
        acceptances = session.exec(select(ClientFlowPhysicalAcceptance).where(
            ClientFlowPhysicalAcceptance.release_id == BASELINE_ID,
            ClientFlowPhysicalAcceptance.bundle_sha256 == control.stable_bundle_sha256,
        ).limit(2)).all()
        if len(acceptances) != 1:
            return "physical_acceptance_unavailable"
        acceptance = acceptances[0]
        require_cutover_authority(catalog=catalog, control=control.model_dump(),
            artifact=artifact, acceptance=acceptance.model_dump(), expected_revision=control.revision,
            expected_release_id=BASELINE_ID, expected_bundle_sha256=control.stable_bundle_sha256,
            now=datetime.now(timezone.utc))
        pilot = session.exec(select(ClientFlowDeployment).where(
            ClientFlowDeployment.client_id == acceptance.client_id,
            ClientFlowDeployment.target_release_id == BASELINE_ID,
            ClientFlowDeployment.bundle_sha256 == artifact["bundle_sha256"],
            ClientFlowDeployment.state == "succeeded",
        ).order_by(ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()
        if not matches_completed_update(pilot, client_id=acceptance.client_id, artifact=artifact):
            return "physical_deployment_unverified"
        if unacknowledged_recovery_failure(session, client_id=acceptance.client_id) is not None:
            return "physical_deployment_unverified"
        if latest is not None:
            return "eligible" if matches_completed_update(latest, client_id=client_id, artifact=artifact) else "update_evidence_mismatch"
        token = session.get(EnrollmentToken, client.enrollment_token_id) if client.enrollment_token_id is not None else None
        receipt = session.exec(select(ClientEnrollmentReceipt).where(
            ClientEnrollmentReceipt.client_id == client_id,
        )).first()
        return "eligible" if matches_completed_enrollment(token, receipt, client=client, artifact=artifact) else "enrollment_evidence_mismatch"
    except (RuntimeError, ValueError, TypeError, KeyError, OSError):
        return "release_evidence_unavailable"
