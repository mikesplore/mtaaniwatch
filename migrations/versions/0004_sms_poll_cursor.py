"""Persist the Africa's Talking inbox polling cursor."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_sms_poll_cursor"
down_revision: Union[str, None] = "0003_sms_intake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sms_poll_cursors",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("last_received_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("sms_poll_cursors")
