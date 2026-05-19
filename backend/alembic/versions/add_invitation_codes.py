"""Add invitation_codes table."""

from alembic import op
import sqlalchemy as sa

revision = "add_invitation_codes"
down_revision = "add_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "invitation_codes" not in inspector.get_table_names():
        op.create_table(
            "invitation_codes",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("code", sa.String(length=32), nullable=False, unique=True),
            sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("invitation_codes")}
    if "idx_invitation_codes_code" not in existing_indexes:
        op.create_index("idx_invitation_codes_code", "invitation_codes", ["code"], unique=False)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invitation_codes")
