"""Durable, intentionally redacted incident episodes and transition timeline."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlmodel import SQLModel, Field


class OperationalIncident(SQLModel, table=True):
    __tablename__ = "operational_incident"
    __table_args__ = (
        CheckConstraint("domain IN ('status','display','system')", name="ck_operational_incident_domain"),
        CheckConstraint("severity IN ('error','critical')", name="ck_operational_incident_severity"),
        Index("ix_operational_incident_started", "started_at"),
        Index("ix_operational_incident_client", "client_id", "started_at"),
        Index("ix_operational_incident_active", "client_id", "domain", "code", unique=True,
              postgresql_where=text("resolved_at IS NULL"), sqlite_where=text("resolved_at IS NULL")),
    )
    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(sa_column=Column(Integer, ForeignKey("client.id", ondelete="CASCADE"), nullable=False))
    domain: str = Field(max_length=16)
    code: str = Field(max_length=96)
    title: str = Field(max_length=160)
    severity: str = Field(max_length=12)
    started_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    first_boot_id: str | None = Field(default=None, max_length=128)
    last_boot_id: str | None = Field(default=None, max_length=128)
    resolution_evidence: str | None = Field(default=None, max_length=32)


class OperationalIncidentEvent(SQLModel, table=True):
    __tablename__ = "operational_incident_event"
    __table_args__ = (
        CheckConstraint("kind IN ('opened','reboot_observed','recovered')", name="ck_operational_incident_event_kind"),
        Index("ix_operational_incident_event_timeline", "incident_id", "observed_at"),
    )
    id: str = Field(primary_key=True, max_length=36)
    incident_id: str = Field(sa_column=Column(String(36), ForeignKey("operational_incident.id", ondelete="CASCADE"), nullable=False))
    kind: str = Field(max_length=24)
    observed_at: datetime
    boot_id: str | None = Field(default=None, max_length=128)
