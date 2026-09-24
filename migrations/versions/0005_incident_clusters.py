"""Persist coordinator-reviewed possible incident clusters."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_incident_clusters"
down_revision: Union[str, None] = "0004_sms_poll_cursor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

cluster_review_status = postgresql.ENUM(
    "SUGGESTED", "ACCEPTED", "DISMISSED", name="cluster_review_status", create_type=False
)


def upgrade() -> None:
    cluster_review_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "incident_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=300), nullable=False),
        sa.Column("status", cluster_review_status, nullable=False),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_clusters_fingerprint", "incident_clusters", ["fingerprint"], unique=True
    )
    op.create_table(
        "incident_cluster_reports",
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["incident_clusters.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.PrimaryKeyConstraint("cluster_id", "report_id"),
    )


def downgrade() -> None:
    op.drop_table("incident_cluster_reports")
    op.drop_index("ix_incident_clusters_fingerprint", table_name="incident_clusters")
    op.drop_table("incident_clusters")
    cluster_review_status.drop(op.get_bind(), checkfirst=True)
