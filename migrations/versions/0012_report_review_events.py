"""Ensure the report review event table exists on upgraded databases."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_report_review_events"
down_revision: Union[str, None] = "0011_worker_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("report_review_events"):
        op.create_table(
            "report_review_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("report_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("reason", sa.String(length=500), nullable=False),
            sa.Column("actor", sa.String(length=120), nullable=False),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("report_review_events")}
    if "ix_report_review_events_report_id" not in indexes:
        op.create_index("ix_report_review_events_report_id", "report_review_events", ["report_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("report_review_events"):
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("report_review_events")}
        if "ix_report_review_events_report_id" in indexes:
            op.drop_index("ix_report_review_events_report_id", table_name="report_review_events")
        op.drop_table("report_review_events")
