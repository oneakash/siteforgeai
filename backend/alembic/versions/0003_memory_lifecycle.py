"""memory lifecycle: scopes, topic keys, dedupe hash, supersede bookkeeping

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memories
          ADD COLUMN scope         text NOT NULL DEFAULT 'project',
          ADD COLUMN session_id    text,
          ADD COLUMN topic_key     text,          -- stable identity of a FACT (e.g. 'brand.palette'); NULL = event/log entry
          ADD COLUMN content_hash  text,
          ADD COLUMN source        jsonb NOT NULL DEFAULT '{}',
          ADD COLUMN superseded_at timestamptz,
          ADD CONSTRAINT ck_memories_scope CHECK (scope IN ('user','project','session')),
          ADD CONSTRAINT ck_memories_scope_ids CHECK (
              (scope = 'user'    AND project_id IS NULL AND session_id IS NULL) OR
              (scope = 'project' AND project_id IS NOT NULL AND session_id IS NULL) OR
              (scope = 'session' AND project_id IS NOT NULL AND session_id IS NOT NULL))
    """)
    # At most ONE active memory per (owner, scope, topic): contradictions are impossible by construction.
    op.execute("""
        CREATE UNIQUE INDEX uq_memories_active_topic ON memories
          (scope, user_id, COALESCE(project_id::text, ''), COALESCE(session_id, ''), topic_key)
          WHERE is_active AND topic_key IS NOT NULL
    """)
    op.execute(
        "CREATE INDEX ix_memories_topic_prefix ON memories (project_id, topic_key text_pattern_ops) WHERE is_active"
    )
    op.execute("CREATE INDEX ix_memories_hash ON memories (content_hash) WHERE is_active")
    op.execute("CREATE INDEX ix_memories_metadata ON memories USING gin (metadata jsonb_path_ops)")


def downgrade() -> None:
    for ix in (
        "ix_memories_metadata",
        "ix_memories_hash",
        "ix_memories_topic_prefix",
        "uq_memories_active_topic",
    ):
        op.execute(f"DROP INDEX {ix}")
    op.execute("""ALTER TABLE memories DROP CONSTRAINT ck_memories_scope_ids, DROP CONSTRAINT ck_memories_scope,
        DROP COLUMN superseded_at, DROP COLUMN source, DROP COLUMN content_hash, DROP COLUMN topic_key,
        DROP COLUMN session_id, DROP COLUMN scope""")
