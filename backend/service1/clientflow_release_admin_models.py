"""Additive, default-closed release authorization control plane.

These records do not replace the existing ClientFlow deployment or cryptographic
release approval. Rollout targets are inert until a separately reviewed cutover.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _json():
    return JSON().with_variant(JSONB(), "postgresql")


class ClientFlowReleaseControl(SQLModel, table=True):
    __tablename__ = "clientflow_release_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_clientflow_release_control_singleton"),
        CheckConstraint("revision >= 1", name="ck_clientflow_release_control_revision"),
        CheckConstraint("length(stable_bundle_sha256) = 64", name="ck_clientflow_release_control_sha256"),
    )

    id: int = Field(primary_key=True)
    stable_release_id: str = Field(max_length=160)
    stable_bundle_sha256: str = Field(max_length=64)
    # A read-only *bootstrap* control; no API opens either hold in phase A.
    fresh_install_open: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false")))
    fleet_open: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false")))
    cutover_enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false")))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    updated_at: datetime
    updated_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")


class ClientFlowRolloutWave(SQLModel, table=True):
    __tablename__ = "clientflow_rollout_wave"
    __table_args__ = (
        CheckConstraint("kind IN ('pilot','controlled')", name="ck_clientflow_rollout_wave_kind"),
        CheckConstraint("state IN ('draft','approved','running','paused','completed','failed','cancelled')", name="ck_clientflow_rollout_wave_state"),
        CheckConstraint("length(bundle_sha256) = 64", name="ck_clientflow_rollout_wave_sha256"),
        CheckConstraint("expires_at > created_at", name="ck_clientflow_rollout_wave_expiry"),
        CheckConstraint("revision >= 1", name="ck_clientflow_rollout_wave_revision"),
        Index("ix_clientflow_rollout_wave_state_expiry", "state", "expires_at"),
        Index("ix_clientflow_rollout_wave_created", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    kind: str = Field(max_length=16)
    state: str = Field(default="draft", max_length=16)
    release_id: str = Field(max_length=160)
    bundle_sha256: str = Field(max_length=64)
    source_version: str = Field(max_length=40)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    created_by_user_id: int = Field(foreign_key="user.id")
    approved_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime
    expires_at: datetime
    approved_at: Optional[datetime] = None
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))


class ClientFlowRolloutTarget(SQLModel, table=True):
    __tablename__ = "clientflow_rollout_target"
    __table_args__ = (
        CheckConstraint("state IN ('draft','approved','consumed','revoked')", name="ck_clientflow_rollout_target_state"),
        CheckConstraint("expires_at > created_at", name="ck_clientflow_rollout_target_expiry"),
        UniqueConstraint("wave_id", "client_id", name="uq_clientflow_rollout_target_wave_client"),
        Index("ix_clientflow_rollout_target_client_state", "client_id", "state"),
        Index("ix_clientflow_rollout_target_wave", "wave_id"),
        Index(
            "uq_clientflow_rollout_target_active_client", "client_id", unique=True,
            postgresql_where=text("state = 'approved'"),
            sqlite_where=text("state = 'approved'"),
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    wave_id: str = Field(sa_column=Column(String(36), ForeignKey("clientflow_rollout_wave.id", ondelete="RESTRICT"), nullable=False))
    client_id: int = Field(foreign_key="client.id")
    state: str = Field(default="draft", max_length=16)
    created_at: datetime
    expires_at: datetime
    consumed_deployment_id: Optional[str] = Field(default=None, foreign_key="clientflow_deployment.id")


class ClientFlowPhysicalAcceptance(SQLModel, table=True):
    __tablename__ = "clientflow_physical_acceptance"
    __table_args__ = (
        CheckConstraint("length(bundle_sha256) = 64", name="ck_clientflow_physical_acceptance_sha256"),
        CheckConstraint("decision IN ('accepted','rejected')", name="ck_clientflow_physical_acceptance_decision"),
        Index("ix_clientflow_physical_acceptance_release", "release_id", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    release_id: str = Field(max_length=160)
    bundle_sha256: str = Field(max_length=64)
    client_id: int = Field(foreign_key="client.id")
    actor_user_id: int = Field(foreign_key="user.id")
    decision: str = Field(max_length=16)
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_json(), nullable=False))
    created_at: datetime
