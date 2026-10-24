"""Durable superadministrator operational incidents, without raw agent secrets.

Revision ID: 20261024_60a_incidents
Revises: 20261023_59a_rollback
"""
from alembic import op
import sqlalchemy as sa

revision = "20261024_60a_incidents"
down_revision = "20261023_59a_rollback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operational_incident",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(16), nullable=False),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("last_observed_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("first_boot_id", sa.String(128), nullable=True),
        sa.Column("last_boot_id", sa.String(128), nullable=True),
        sa.Column("resolution_evidence", sa.String(32), nullable=True),
        sa.CheckConstraint("domain IN ('status','display','system')", name="ck_operational_incident_domain"),
        sa.CheckConstraint("severity IN ('error','critical')", name="ck_operational_incident_severity"),
    )
    op.create_index("ix_operational_incident_started", "operational_incident", ["started_at"])
    op.create_index("ix_operational_incident_client", "operational_incident", ["client_id", "started_at"])
    op.create_index("ix_operational_incident_active", "operational_incident", ["client_id", "domain", "code"], unique=True,
                    postgresql_where=sa.text("resolved_at IS NULL"), sqlite_where=sa.text("resolved_at IS NULL"))
    op.create_table(
        "operational_incident_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("operational_incident.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("observed_at", sa.DateTime, nullable=False),
        sa.Column("boot_id", sa.String(128), nullable=True),
        sa.CheckConstraint("kind IN ('opened','reboot_observed','recovered')", name="ck_operational_incident_event_kind"),
    )
    op.create_index("ix_operational_incident_event_timeline", "operational_incident_event", ["incident_id", "observed_at"])


def downgrade():
    raise RuntimeError("Driftsfejlhistorik og gendannelsesbevis må ikke slettes automatisk")
