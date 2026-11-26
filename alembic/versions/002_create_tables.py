"""Create every ORM table (raw, ref, mart) including daily_prices and security_master.

Revision ID: 002
Revises: 001
Create Date: 2026-11-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sec_filings.db import Base
    import sec_filings.models  # noqa: F401  (register every model on Base.metadata)

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    from sec_filings.db import Base
    import sec_filings.models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
