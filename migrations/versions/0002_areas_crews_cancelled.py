"""Add demo areas and crews; allow cancelled tasks."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_areas_crews"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "crews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("home_area_id", sa.Integer(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["home_area_id"], ["areas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("reports", sa.Column("area_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_reports_area_id_areas", "reports", "areas", ["area_id"], ["id"])
    op.add_column("tasks", sa.Column("crew_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tasks_crew_id_crews", "tasks", "crews", ["crew_id"], ["id"])

    op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value without rebuilding the enum type.
    op.drop_constraint("fk_tasks_crew_id_crews", "tasks", type_="foreignkey")
    op.drop_column("tasks", "crew_id")
    op.drop_constraint("fk_reports_area_id_areas", "reports", type_="foreignkey")
    op.drop_column("reports", "area_id")
    op.drop_table("crews")
    op.drop_table("areas")
