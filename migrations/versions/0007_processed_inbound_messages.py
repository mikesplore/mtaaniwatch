"""Record processed inbound message IDs for idempotent replies."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_processed_inbound_messages"
down_revision: Union[str, None] = "0006_report_sms_link_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_inbound_messages",
        sa.Column("message_key", sa.String(length=180), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("message_key"),
    )


def downgrade() -> None:
    op.drop_table("processed_inbound_messages")
