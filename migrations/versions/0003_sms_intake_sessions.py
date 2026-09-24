"""Add persistence for SMS intake confirmation sessions."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_sms_intake"
down_revision: Union[str, None] = "0002_areas_crews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sms_intake_sessions",
        sa.Column("sender_phone", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("candidate", sa.JSON(), nullable=False),
        sa.Column("last_message_id", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sender_phone"),
    )


def downgrade() -> None:
    op.drop_table("sms_intake_sessions")
