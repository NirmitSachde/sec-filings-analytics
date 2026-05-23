"""Initial schema with pgvector extension and all schemas.

Revision ID: 001
Revises: None
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS ref")
    op.execute("CREATE SCHEMA IF NOT EXISTS mart")
    op.execute("CREATE SCHEMA IF NOT EXISTS vec")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS vec CASCADE")
    op.execute("DROP SCHEMA IF EXISTS mart CASCADE")
    op.execute("DROP SCHEMA IF EXISTS ref CASCADE")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")
    op.execute("DROP EXTENSION IF EXISTS vector")
