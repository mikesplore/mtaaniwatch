"""Add auditable coordinator report triage fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_report_triage"
down_revision: Union[str, None] = "0008_report_disposition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("location_uncertain", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("reports", sa.Column("triage_reason", sa.String(length=500), nullable=True))
    op.add_column("reports", sa.Column("triage_actor", sa.String(length=120), nullable=True))
    op.add_column("reports", sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("reports", "location_uncertain", server_default=None)
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
    op.create_index("ix_report_review_events_report_id", "report_review_events", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_report_review_events_report_id", table_name="report_review_events")
    op.drop_table("report_review_events")
    op.drop_column("reports", "triaged_at")
    op.drop_column("reports", "triage_actor")
    op.drop_column("reports", "triage_reason")
    op.drop_column("reports", "location_uncertain")
