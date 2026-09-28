"""Persist language and completion state for Voice callbacks."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_voice_intake_sessions"
down_revision: Union[str, None] = "0012_report_review_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("voice_intake_sessions"):
        op.create_table(
            "voice_intake_sessions",
            sa.Column("session_id", sa.String(length=100), nullable=False),
            sa.Column("caller_number", sa.String(length=32), nullable=False),
            sa.Column("language", sa.String(length=2), nullable=False),
            sa.Column("recording_processed", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("session_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("voice_intake_sessions"):
        op.drop_table("voice_intake_sessions")
