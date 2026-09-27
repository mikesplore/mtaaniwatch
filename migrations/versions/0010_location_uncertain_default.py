"""Keep new reports certain by default at the database level."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_location_uncertain_default"
down_revision: Union[str, None] = "0009_report_triage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.alter_column(
        "reports",
        "location_uncertain",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
    )


def downgrade() -> None:
    op.alter_column(
        "reports",
        "location_uncertain",
        existing_type=sa.Boolean(),
        server_default=None,
    )
