"""Add durable signed manual rollback permits and append-only events.

Revision ID: 20261023_59a_rollback
Revises: 20260929_58a_maintenance
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261023_59a_rollback"
down_revision = "20260929_58a_maintenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clientflow_rollback_permit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=False),
        sa.Column("credential_id", sa.String(36), sa.ForeignKey("clientflow_update_credential.id"), nullable=False),
        sa.Column("admin_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("from_release_id", sa.String(160), nullable=False),
        sa.Column("from_sequence", sa.Integer, nullable=False),
        sa.Column("to_release_id", sa.String(160), nullable=False),
        sa.Column("to_sequence", sa.Integer, nullable=False),
        sa.Column("release_approval_reference", sa.String(200), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("reason_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("policy_revision", sa.Integer, nullable=False),
        sa.Column("signing_key_id", sa.String(32), nullable=False),
        sa.Column("signed_envelope", sa.Text, nullable=False),
        sa.Column("issued_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("reported_at", sa.DateTime),
        sa.Column("revoked_at", sa.DateTime),
        sa.CheckConstraint("state IN ('issued','revoked','succeeded','failed')", name="ck_clientflow_rollback_permit_state"),
        sa.CheckConstraint("from_sequence > to_sequence AND to_sequence > 0", name="ck_clientflow_rollback_permit_sequences"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_clientflow_rollback_permit_expiry"),
    )
    op.create_index("ix_clientflow_rollback_permit_client_id", "clientflow_rollback_permit", ["client_id"])
    op.create_index("ix_clientflow_rollback_permit_expires_at", "clientflow_rollback_permit", ["expires_at"])
    op.create_index("ix_clientflow_rollback_permit_client_state", "clientflow_rollback_permit", ["client_id", "state"])
    op.create_table(
        "clientflow_rollback_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("permit_id", sa.String(36), sa.ForeignKey("clientflow_rollback_permit.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("credential_id", sa.String(36), sa.ForeignKey("clientflow_update_credential.id", ondelete="SET NULL")),
        sa.Column("occurred_at", sa.DateTime),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("details", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    op.create_index("ix_clientflow_rollback_event_permit", "clientflow_rollback_event", ["permit_id", "received_at"])
    op.create_index("ix_clientflow_rollback_event_client", "clientflow_rollback_event", ["client_id", "received_at"])


def downgrade():
    raise RuntimeError("Signeret rollback-audit og forbrugsjournal må ikke fjernes automatisk")
