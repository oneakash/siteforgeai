"""runtime model overrides (chat + embedding)

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE model_overrides (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id  uuid REFERENCES projects(id) ON DELETE CASCADE,   -- NULL = global
            agent       text,                                            -- NULL = any agent
            tier        text CHECK (tier IN ('reasoning','fast')),       -- NULL = any tier
            purpose     text NOT NULL DEFAULT 'chat' CHECK (purpose IN ('chat','embedding')),
            model_ref   text NOT NULL,                                   -- 'provider:model_id'
            updated_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_model_override_scope UNIQUE NULLS NOT DISTINCT (project_id, agent, tier, purpose)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE model_overrides")
