"""Authenticated boot observation never turns an unrelated reboot into command success."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientCommand, ClientDomainCredential, ClientDomainStatus
from service1.models import Client
from service1.shared_domain import _reconcile_command_state, claim_shared_command
from service1.system_control import power_projection_from_command, queue_system_command, utcnow


def _setup(*, capable: bool, action: str = "reboot", claimed: bool = True,
           last_boot: str = "new-boot", status_boot: str | None = "new-boot"):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        client = Client(name="Power-recovery", status="approved", last_boot_id=last_boot)
        s.add(client)
        s.flush()
        cid = client.id
        credential = ClientDomainCredential(
            id=str(uuid.uuid4()), client_id=cid, domain="system", secret_hash="test-only",
            token_version=0, created_at=utcnow(),
        )
        s.add(credential)
        s.flush()
        s.add(ClientDomainStatus(
            id=str(uuid.uuid4()), client_id=cid, domain="system", credential_id=credential.id,
            observed_state="online", boot_id=status_boot, status_payload={"safe_reboot_recovery": capable},
            reported_at=utcnow(),
        ))
        command = queue_system_command(
            s, client_id=cid, command_type=action,
            payload={"source": "control_room", "requested_boot_id": "old-boot"},
            requested_by_user_id=None, ttl_seconds=300, idempotency_prefix="test-reboot",
        )
        s.flush()
        command_id = command.id
        if claimed:
            command.status = "claimed"
            command.claimed_by_credential_id = credential.id
            command.claim_token_hash = "a" * 64
            command.claimed_at = utcnow() - timedelta(seconds=10)
            command.lease_expires_at = utcnow() + timedelta(seconds=120)
            command.attempt_count = 1
            s.add(command)
        s.commit()
    return engine, cid, command_id


def _reconcile(engine, client_id, command_id):
    with Session(engine) as s:
        _reconcile_command_state(s, client_id=client_id, domain="system", now=utcnow())
        s.commit()
        return s.get(ClientCommand, command_id)


def test_old_system_agent_cannot_reissue_claimed_reboot_after_boot_change():
    engine, cid, command_id = _setup(capable=False)
    row = _reconcile(engine, cid, command_id)
    assert row.status == "failed"
    assert row.error_code == "reboot_completion_unverified_after_boot"
    assert row.claim_token_hash is None
    assert power_projection_from_command(row, current_boot_id="new-boot", status_online=True)["state"] == "normal"


def test_unclaimed_reboot_is_cancelled_after_unrelated_boot_even_on_capable_agent():
    engine, cid, command_id = _setup(capable=True, claimed=False)
    row = _reconcile(engine, cid, command_id)
    assert row.status == "cancelled"
    assert row.result is None
    assert row.error_code == "reboot_completion_unverified_after_boot"


def test_capable_agent_replays_only_same_command_with_recovery_only():
    engine, cid, command_id = _setup(capable=True)
    row = _reconcile(engine, cid, command_id)
    assert row.status == "queued"
    assert row.payload["recovery_only"] is True
    assert row.payload["recovery_boot_id"] == "new-boot"
    assert row.payload["requested_boot_id"] == "old-boot"
    assert row.attempt_count == 1
    with Session(engine) as s:
        credential = s.exec(select(ClientDomainCredential).where(ClientDomainCredential.client_id == cid)).one()
        claimed = claim_shared_command(s, credential=credential, lease_seconds=60)
        assert claimed["claimed"]["command"]["id"] == command_id
        assert claimed["claimed"]["command"]["payload"]["recovery_only"] is True


def test_capability_must_be_reported_after_current_boot():
    engine, cid, command_id = _setup(capable=True, status_boot="old-boot")
    row = _reconcile(engine, cid, command_id)
    assert row.status == "failed"


@pytest.mark.parametrize("action", ["shutdown", "update_os", "update_firmware", "change_hostname"])
def test_unrelated_system_commands_not_converted_to_reboot_recovery(action):
    engine, cid, command_id = _setup(capable=True, action=action)
    row = _reconcile(engine, cid, command_id)
    assert row.command_type == action
    assert row.payload.get("recovery_only") is None


def test_expired_reboot_stays_expired_and_does_not_get_reclaimed():
    engine, cid, command_id = _setup(capable=True)
    with Session(engine) as s:
        row = s.get(ClientCommand, command_id)
        row.requested_at = utcnow() - timedelta(seconds=400)
        row.expires_at = utcnow() - timedelta(seconds=2)
        s.add(row)
        s.commit()
    row = _reconcile(engine, cid, command_id)
    assert row.status == "expired"
    assert row.error_code == "command_expired"
    assert not row.payload.get("recovery_only")


def test_new_boot_immediately_ends_rebooting_ui_without_fabricating_command_success():
    engine, cid, command_id = _setup(capable=False)
    with Session(engine) as s:
        row = s.get(ClientCommand, command_id)
        assert row.status == "claimed"
        view = power_projection_from_command(row, current_boot_id="new-boot", status_online=True)
        assert view["state"] == "normal"
        assert view["pending_reboot"] is False
        assert view["last_power_event"] is None
        assert row.status == "claimed"
        assert power_projection_from_command(row, current_boot_id="old-boot", status_online=True)["state"] == "rebooting"
        assert power_projection_from_command(row, current_boot_id="new-boot", status_online=False)["state"] == "rebooting"


def test_system_agent_new_boot_vetoes_old_queued_reboot_before_status_agent_catches_up():
    engine, cid, command_id = _setup(
        capable=False, claimed=False, last_boot="old-boot", status_boot="new-boot",
    )
    with Session(engine) as s:
        credential = s.exec(select(ClientDomainCredential).where(ClientDomainCredential.client_id == cid)).one()
        assert claim_shared_command(s, credential=credential, lease_seconds=60) == {"claimed": None}
        assert s.get(ClientCommand, command_id).status == "queued"


def test_normal_reboot_claim_allowed_only_for_same_reported_boot():
    engine, cid, command_id = _setup(
        capable=False, claimed=False, last_boot="old-boot", status_boot="old-boot",
    )
    with Session(engine) as s:
        credential = s.exec(select(ClientDomainCredential).where(ClientDomainCredential.client_id == cid)).one()
        claim = claim_shared_command(s, credential=credential, lease_seconds=60)
        assert claim["claimed"]["command"]["id"] == command_id
        assert claim["claimed"]["command"]["payload"]["requested_boot_id"] == "old-boot"
