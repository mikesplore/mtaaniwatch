"""Retain the SMS conversation link for later resident notifications."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_report_sms_link_id"
down_revision: Union[str, None] = "0005_incident_clusters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("sms_link_id", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "sms_link_id")
