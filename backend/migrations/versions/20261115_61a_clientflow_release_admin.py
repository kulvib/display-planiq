"""Create default-closed, additive ClientFlow release administration state.

Revision ID: 20261115_61a_cf_release_admin
Revises: 20261024_60a_incidents

No existing authorizations, signed client credentials, deployments or release
artifacts are changed. No flag or policy is opened by this migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261115_61a_cf_release_admin"
down_revision = "20261024_60a_incidents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clientflow_release_control",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("stable_release_id", sa.String(160), nullable=False),
        sa.Column("stable_bundle_sha256", sa.String(64), nullable=False),
        sa.Column("fresh_install_open", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fleet_open", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cutover_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_clientflow_release_control_singleton"),
        sa.CheckConstraint("revision >= 1", name="ck_clientflow_release_control_revision"),
        sa.CheckConstraint("length(stable_bundle_sha256) = 64", name="ck_clientflow_release_control_sha256"),
    )
    # Explicit conservative bootstrap, not derived from environment or client state.
    op.execute(sa.text("""INSERT INTO clientflow_release_control
      (id, stable_release_id, stable_bundle_sha256, fresh_install_open,
       fleet_open, cutover_enabled, revision, updated_at)
      VALUES (1, 'clientflow-1.3.44-seq-1245',
       '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5',
       false, false, false, 1, CURRENT_TIMESTAMP)"""))
    op.create_table(
        "clientflow_rollout_wave",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("release_id", sa.String(160), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("kind IN ('pilot','controlled')", name="ck_clientflow_rollout_wave_kind"),
        sa.CheckConstraint("state IN ('draft','approved','running','paused','completed','failed','cancelled')", name="ck_clientflow_rollout_wave_state"),
        sa.CheckConstraint("length(bundle_sha256) = 64", name="ck_clientflow_rollout_wave_sha256"),
        sa.CheckConstraint("expires_at > created_at", name="ck_clientflow_rollout_wave_expiry"),
        sa.CheckConstraint("revision >= 1", name="ck_clientflow_rollout_wave_revision"),
    )
    op.create_index("ix_clientflow_rollout_wave_state_expiry", "clientflow_rollout_wave", ["state", "expires_at"])
    op.create_index("ix_clientflow_rollout_wave_created", "clientflow_rollout_wave", ["created_at"])
    op.create_table(
        "clientflow_rollout_target",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wave_id", sa.String(36), sa.ForeignKey("clientflow_rollout_wave.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_deployment_id", sa.String(36), sa.ForeignKey("clientflow_deployment.id"), nullable=True),
        sa.UniqueConstraint("wave_id", "client_id", name="uq_clientflow_rollout_target_wave_client"),
        sa.CheckConstraint("state IN ('draft','approved','consumed','revoked')", name="ck_clientflow_rollout_target_state"),
        sa.CheckConstraint("expires_at > created_at", name="ck_clientflow_rollout_target_expiry"),
    )
    op.create_index("ix_clientflow_rollout_target_client_state", "clientflow_rollout_target", ["client_id", "state"])
    op.create_index("ix_clientflow_rollout_target_wave", "clientflow_rollout_target", ["wave_id"])
    op.create_index("uq_clientflow_rollout_target_active_client", "clientflow_rollout_target", ["client_id"], unique=True,
                    postgresql_where=sa.text("state = 'approved'"), sqlite_where=sa.text("state = 'approved'"))
    op.create_table(
        "clientflow_physical_acceptance",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(160), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("evidence", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(bundle_sha256) = 64", name="ck_clientflow_physical_acceptance_sha256"),
        sa.CheckConstraint("decision IN ('accepted','rejected')", name="ck_clientflow_physical_acceptance_decision"),
    )
    op.create_index("ix_clientflow_physical_acceptance_release", "clientflow_physical_acceptance", ["release_id", "created_at"])


def downgrade():
    raise RuntimeError("ClientFlow release-/audit-data slettes ikke automatisk")
