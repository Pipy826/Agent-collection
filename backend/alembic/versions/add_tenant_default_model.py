"""Add Tenant.default_model_id + backfill per-tenant to earliest enabled model."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_tenant_default_model"
down_revision: Union[str, None] = "add_agent_bootstrap_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tenant_columns = {col["name"] for col in inspector.get_columns("tenants")}

    if "default_model_id" not in tenant_columns:
        op.add_column("tenants", sa.Column("default_model_id", sa.String(length=36), nullable=True))

    if bind.dialect.name == "sqlite":
        rows = bind.execute(sa.text("""
            SELECT tenant_id, id
            FROM llm_models lm
            WHERE enabled = 1
              AND tenant_id IS NOT NULL
              AND created_at = (
                  SELECT MIN(lm2.created_at)
                  FROM llm_models lm2
                  WHERE lm2.tenant_id = lm.tenant_id
                    AND lm2.enabled = 1
              )
            ORDER BY tenant_id, created_at ASC
        """)).fetchall()
        seen = set()
        for tenant_id, model_id in rows:
            tenant_key = str(tenant_id)
            if tenant_key in seen:
                continue
            seen.add(tenant_key)
            bind.execute(
                sa.text("""
                    UPDATE tenants
                    SET default_model_id = :model_id
                    WHERE id = :tenant_id AND default_model_id IS NULL
                """),
                {"tenant_id": tenant_key, "model_id": str(model_id)},
            )
        return

    op.execute("""
        UPDATE tenants t
        SET default_model_id = m.id
        FROM (
            SELECT DISTINCT ON (tenant_id) tenant_id, id
            FROM llm_models
            WHERE enabled = TRUE AND tenant_id IS NOT NULL
            ORDER BY tenant_id, created_at ASC
        ) m
        WHERE t.id = m.tenant_id AND t.default_model_id IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS default_model_id")
