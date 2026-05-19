"""Add participants table, extend chat_sessions and chat_messages."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "add_participants"
down_revision = "add_invitation_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if "participants" not in inspector.get_table_names():
        op.create_table(
            "participants",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("type", sa.String(length=10), nullable=False),
            sa.Column("ref_id", sa.String(length=36), nullable=False),
            sa.Column("display_name", sa.String(length=100), nullable=False),
            sa.Column("avatar_url", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("type", "ref_id", name="uq_participants_type_ref"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("participants")}
    if "ix_participants_ref_id" not in existing_indexes:
        op.create_index("ix_participants_ref_id", "participants", ["ref_id"], unique=False)

    def add_column_if_missing(table_name: str, column: sa.Column) -> None:
        existing = {col["name"] for col in inspector.get_columns(table_name)}
        if column.name not in existing:
            op.add_column(table_name, column)

    add_column_if_missing("chat_sessions", sa.Column("participant_id", sa.String(length=36), nullable=True))
    add_column_if_missing("chat_sessions", sa.Column("peer_agent_id", sa.String(length=36), nullable=True))
    add_column_if_missing("chat_sessions", sa.Column("external_conv_id", sa.String(length=200), nullable=True))
    add_column_if_missing("chat_messages", sa.Column("participant_id", sa.String(length=36), nullable=True))

    if is_sqlite:
        user_rows = bind.execute(sa.text("SELECT id, display_name, avatar_url FROM users")).fetchall()
        agent_rows = bind.execute(sa.text("SELECT id, name, avatar_url FROM agents")).fetchall()
        for user_id, display_name, avatar_url in user_rows:
            bind.execute(
                sa.text(
                    "INSERT OR IGNORE INTO participants (id, type, ref_id, display_name, avatar_url) "
                    "VALUES (:id, 'user', :ref_id, :display_name, :avatar_url)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ref_id": str(user_id),
                    "display_name": display_name or "User",
                    "avatar_url": avatar_url,
                },
            )
        for agent_id, name, avatar_url in agent_rows:
            bind.execute(
                sa.text(
                    "INSERT OR IGNORE INTO participants (id, type, ref_id, display_name, avatar_url) "
                    "VALUES (:id, 'agent', :ref_id, :display_name, :avatar_url)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ref_id": str(agent_id),
                    "display_name": name,
                    "avatar_url": avatar_url,
                },
            )
        bind.execute(sa.text("""
            UPDATE chat_sessions
            SET participant_id = (
                SELECT id FROM participants
                WHERE participants.type = 'user' AND participants.ref_id = chat_sessions.user_id
                LIMIT 1
            )
            WHERE participant_id IS NULL
        """))
        bind.execute(sa.text("""
            UPDATE chat_messages
            SET participant_id = (
                SELECT id FROM participants
                WHERE participants.type = 'user' AND participants.ref_id = chat_messages.user_id
                LIMIT 1
            )
            WHERE participant_id IS NULL
        """))
        return

    user_columns = {
        row[0]
        for row in bind.execute(sa.text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
        """)).fetchall()
    }
    has_username = "username" in user_columns
    has_identities = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'identities')"
    )).scalar()

    if has_identities:
        bind.execute(sa.text("""
            INSERT INTO participants (id, type, ref_id, display_name, avatar_url)
            SELECT gen_random_uuid(), 'user', u.id, COALESCE(u.display_name, i.username, 'User'), u.avatar_url
            FROM users u
            LEFT JOIN identities i ON u.identity_id = i.id
            ON CONFLICT DO NOTHING
        """))
    elif has_username:
        bind.execute(sa.text("""
            INSERT INTO participants (id, type, ref_id, display_name, avatar_url)
            SELECT gen_random_uuid(), 'user', id, COALESCE(display_name, username, 'User'), avatar_url
            FROM users
            ON CONFLICT DO NOTHING
        """))
    else:
        bind.execute(sa.text("""
            INSERT INTO participants (id, type, ref_id, display_name, avatar_url)
            SELECT gen_random_uuid(), 'user', id, COALESCE(display_name, 'User'), avatar_url
            FROM users
            ON CONFLICT DO NOTHING
        """))

    bind.execute(sa.text("""
        INSERT INTO participants (id, type, ref_id, display_name, avatar_url)
        SELECT gen_random_uuid(), 'agent', id, name, avatar_url
        FROM agents
        ON CONFLICT DO NOTHING
    """))

    bind.execute(sa.text("""
        UPDATE chat_sessions cs
        SET participant_id = p.id
        FROM participants p
        WHERE p.type = 'user' AND p.ref_id = cs.user_id
        AND cs.participant_id IS NULL
    """))
    bind.execute(sa.text("""
        UPDATE chat_messages cm
        SET participant_id = p.id
        FROM participants p
        WHERE p.type = 'user' AND p.ref_id = cm.user_id
        AND cm.participant_id IS NULL
    """))


def downgrade() -> None:
    op.drop_column("chat_messages", "participant_id")
    op.drop_column("chat_sessions", "external_conv_id")
    op.drop_column("chat_sessions", "peer_agent_id")
    op.drop_column("chat_sessions", "participant_id")
    op.drop_table("participants")
