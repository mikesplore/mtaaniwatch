"""Create initial reports, tasks, and task status history tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


task_status = sa.Enum(
    "REPORTED", "ASSIGNED", "IN_PROGRESS", "RESOLVED", name="task_status"
)


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("landmark", sa.String(length=200), nullable=True),
        sa.Column("impact_reported", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("resident_phone", sa.String(length=32), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_reports_reference", "reports", ["reference"], unique=True)

    task_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("crew_name", sa.String(length=120), nullable=True),
        sa.Column("status", task_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id"),
    )
    op.create_table(
        "task_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("task_status_history")
    op.drop_table("tasks")
    task_status.drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_reports_reference", table_name="reports")
    op.drop_table("reports")
