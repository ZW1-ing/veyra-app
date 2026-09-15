"""add tenant isolation and request tracing

Revision ID: b74d91a2c3e4
Revises: a65c78676778
Create Date: 2026-09-15 12:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b74d91a2c3e4"
down_revision: Union[str, Sequence[str], None] = "a65c78676778"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给会话、文档和用量记录补上租户归属，并给用量记录补请求 ID。"""
    op.add_column(
        "sessions",
        sa.Column("owner_id", sa.String(length=64), nullable=False, server_default="anonymous"),
    )
    op.create_index("ix_sessions_owner_updated", "sessions", ["owner_id", "updated_at"])

    op.add_column(
        "documents",
        sa.Column("owner_id", sa.String(length=64), nullable=False, server_default="anonymous"),
    )
    op.create_index("ix_documents_owner_created", "documents", ["owner_id", "created_at"])

    op.add_column(
        "usage_records",
        sa.Column("owner_id", sa.String(length=64), nullable=False, server_default="anonymous"),
    )
    op.add_column(
        "usage_records",
        sa.Column("request_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_usage_records_owner_created",
        "usage_records",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_owner_created", table_name="usage_records")
    op.drop_column("usage_records", "request_id")
    op.drop_column("usage_records", "owner_id")

    op.drop_index("ix_documents_owner_created", table_name="documents")
    op.drop_column("documents", "owner_id")

    op.drop_index("ix_sessions_owner_updated", table_name="sessions")
    op.drop_column("sessions", "owner_id")
