"""Immutable authorization binding and durable audit for one-shot manual rollbacks."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


class ClientFlowRollbackPermit(SQLModel, table=True):
    __tablename__ = "clientflow_rollback_permit"
    __table_args__ = (
        CheckConstraint("state IN ('issued','revoked','succeeded','failed')", name="ck_clientflow_rollback_permit_state"),
        CheckConstraint("from_sequence > to_sequence AND to_sequence > 0", name="ck_clientflow_rollback_permit_sequences"),
        CheckConstraint("expires_at > issued_at", name="ck_clientflow_rollback_permit_expiry"),
        Index("ix_clientflow_rollback_permit_client_id", "client_id"),
        Index("ix_clientflow_rollback_permit_expires_at", "expires_at"),
        Index("ix_clientflow_rollback_permit_client_state", "client_id", "state"),
    )
    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    credential_id: str = Field(foreign_key="clientflow_update_credential.id", max_length=36)
    admin_id: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    from_release_id: str = Field(max_length=160)
    from_sequence: int
    to_release_id: str = Field(max_length=160)
    to_sequence: int
    release_approval_reference: str = Field(max_length=200)
    bundle_sha256: str = Field(max_length=64)
    reason_sha256: str = Field(max_length=64)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    policy_revision: int
    signing_key_id: str = Field(max_length=32)
    signed_envelope: str = Field(sa_column=Column(Text, nullable=False))
    issued_at: datetime
    expires_at: datetime
    state: str = Field(default="issued", max_length=16)
    reported_at: datetime | None = None
    revoked_at: datetime | None = None


class ClientFlowRollbackEvent(SQLModel, table=True):
    __tablename__ = "clientflow_rollback_event"
    __table_args__ = (
        Index("ix_clientflow_rollback_event_permit", "permit_id", "received_at"),
        Index("ix_clientflow_rollback_event_client", "client_id", "received_at"),
    )
    id: str = Field(primary_key=True, max_length=36)
    permit_id: str = Field(sa_column=Column(String(36), ForeignKey("clientflow_rollback_permit.id", ondelete="RESTRICT"), nullable=False))
    client_id: int = Field(foreign_key="client.id")
    event_type: str = Field(max_length=32)
    actor_user_id: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    credential_id: str | None = Field(default=None, sa_column=Column(String(36), ForeignKey("clientflow_update_credential.id", ondelete="SET NULL"), nullable=True))
    occurred_at: datetime | None = None
    received_at: datetime
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_json_type(), nullable=False))
