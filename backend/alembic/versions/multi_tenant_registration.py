"""Multi-tenant registration migration."""

from alembic import op
import sqlalchemy as sa

revision = "multi_tenant_registration"
down_revision = "add_skill_tenant_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    invitation_columns = {col["name"] for col in inspector.get_columns("invitation_codes")}
    if "tenant_id" not in invitation_columns:
        op.add_column("invitation_codes", sa.Column("tenant_id", sa.String(length=36), nullable=True))

    invitation_indexes = {idx["name"] for idx in inspector.get_indexes("invitation_codes")}
    if "ix_invitation_codes_tenant_id" not in invitation_indexes:
        op.create_index("ix_invitation_codes_tenant_id", "invitation_codes", ["tenant_id"], unique=False)

    op.execute("DELETE FROM invitation_codes")

    if is_sqlite:
        rows = bind.execute(sa.text("""
            SELECT id
            FROM users u
            WHERE u.tenant_id IS NOT NULL
              AND u.role NOT IN ('platform_admin', 'org_admin')
              AND u.created_at = (
                  SELECT MIN(u2.created_at)
                  FROM users u2
                  WHERE u2.tenant_id = u.tenant_id
                    AND u2.role NOT IN ('platform_admin', 'org_admin')
              )
        """)).fetchall()
        for (user_id,) in rows:
            bind.execute(sa.text("UPDATE users SET role = 'org_admin' WHERE id = :id"), {"id": str(user_id)})

        system_tables = set(inspector.get_table_names())
        if "system_settings" in system_tables:
            bind.execute(sa.text("""
                INSERT OR IGNORE INTO system_settings (key, value)
                VALUES ('allow_self_create_company', '{"enabled": true}')
            """))
        return

    op.execute("""
        UPDATE users
        SET role = 'org_admin'
        WHERE id IN (
            SELECT DISTINCT ON (tenant_id) id
            FROM users
            WHERE tenant_id IS NOT NULL
              AND role NOT IN ('platform_admin', 'org_admin')
            ORDER BY tenant_id, created_at ASC
        )
    """)
    op.execute("""
        INSERT INTO system_settings (key, value)
        VALUES ('allow_self_create_company', '{"enabled": true}'::jsonb)
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_invitation_codes_tenant_id")
    op.execute("DELETE FROM system_settings WHERE key = 'allow_self_create_company'")
