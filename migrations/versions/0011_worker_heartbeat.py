"""Track inbox poller liveness and most recent processing outcome."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_worker_heartbeat"
down_revision: Union[str, None] = "0010_location_uncertain_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("last_processed_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
