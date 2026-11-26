"""Read-only native RDP release eligibility, separate from transport authority.

No credential, session, tunnel or fleet permission is issued here. The active
pilot gate remains unchanged until the generic host lifecycle is physically
verified. Query this only on explicit administrator admission checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from .client_presence import load_client_presence
from .clientflow_deployments import active_deployment, unacknowledged_recovery_failure
from .clientflow_release_admin_models import ClientFlowPhysicalAcceptance, ClientFlowReleaseControl
from .clientflow_release_security_policy import require_centrally_eligible_release
from .clientflow_releases import deployment_release_snapshot, load_catalog, resolve_release
from .clientflow_standard_release import (
    BASELINE_ID, BASELINE_SEQUENCE, BASELINE_VERSION, require_cutover_authority,
)
from .clientflow_update_models import ClientFlowDeployment
from .enrollment_models import ClientEnrollmentReceipt
from .models import Client, EnrollmentToken
from .remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential


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
    if (control is None or control.stable_release_id != BASELINE_ID
            or control.cutover_enabled is not True or control.fleet_open is not True):
        return "cutover_closed"
    try:
        catalog = load_catalog()
        artifact = deployment_release_snapshot(resolve_release(BASELINE_VERSION))
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
        if (active_deployment(session, client_id=client_id) is not None
                or unacknowledged_recovery_failure(session, client_id=client_id) is not None):
            return "installation_in_progress_or_failed"
        presence = load_client_presence(session, client).status
        if not presence.is_online or presence.agent_version != BASELINE_VERSION:
            return "canonical_runtime_unavailable"
        latest = session.exec(select(ClientFlowDeployment).where(
            ClientFlowDeployment.client_id == client_id,
        ).order_by(ClientFlowDeployment.requested_at.desc(), ClientFlowDeployment.id.desc()).limit(1)).first()
        if latest is not None:
            return "eligible" if matches_completed_update(latest, client_id=client_id, artifact=artifact) else "update_evidence_mismatch"
        token = session.get(EnrollmentToken, client.enrollment_token_id) if client.enrollment_token_id is not None else None
        receipt = session.exec(select(ClientEnrollmentReceipt).where(
            ClientEnrollmentReceipt.client_id == client_id,
        )).first()
        return "eligible" if matches_completed_enrollment(token, receipt, client=client, artifact=artifact) else "enrollment_evidence_mismatch"
    except (RuntimeError, ValueError, TypeError, KeyError, OSError):
        return "release_evidence_unavailable"
