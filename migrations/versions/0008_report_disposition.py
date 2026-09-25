"""Add auditable report-level disposition for out-of-scope reports."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_report_disposition"
down_revision: Union[str, None] = "0007_processed_inbound_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("disposition", sa.String(length=32), nullable=True))
    op.add_column("reports", sa.Column("disposition_reason", sa.String(length=500), nullable=True))
    op.add_column("reports", sa.Column("disposition_actor", sa.String(length=120), nullable=True))
    op.add_column("reports", sa.Column("disposition_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "disposition_at")
    op.drop_column("reports", "disposition_actor")
    op.drop_column("reports", "disposition_reason")
    op.drop_column("reports", "disposition")
