"""Add published_pages table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_published_pages"
down_revision: Union[str, None] = "df3da9cf3b27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "published_pages" not in inspector.get_table_names():
        op.create_table(
            "published_pages",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("short_id", sa.String(length=16), nullable=False, unique=True),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("source_path", sa.String(length=500), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=True, server_default=""),
            sa.Column("view_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("published_pages")}
    if "ix_published_pages_short_id" not in existing_indexes:
        op.create_index("ix_published_pages_short_id", "published_pages", ["short_id"], unique=False)
    if "ix_published_pages_agent_id" not in existing_indexes:
        op.create_index("ix_published_pages_agent_id", "published_pages", ["agent_id"], unique=False)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS published_pages")
