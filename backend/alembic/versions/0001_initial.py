"""initial schema: projects, tasks, artifacts, memories, site_versions, audit_log

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UUID_PK = dict(server_default=sa.text("gen_random_uuid()"), primary_key=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "projects",
        sa.Column("id", pg.UUID, **UUID_PK),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("brand_name", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("niche", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="created"),
        sa.Column("phase", sa.Text, nullable=False, server_default="planning"),
        sa.Column("thread_id", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_projects_user", "projects", ["user_id"])

    # Task ledger: one row per planned task. (project_id, task_key) is the
    # idempotency key that prevents duplicate execution after recovery.
    op.create_table(
        "tasks",
        sa.Column("id", pg.UUID, **UUID_PK),
        sa.Column("project_id", pg.UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_key", sa.Text, nullable=False),
        sa.Column("agent", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("depends_on", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input", pg.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "task_key", name="uq_tasks_project_key"),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','skipped','superseded')",
            name="ck_tasks_status",
        ),
    )

    # Versioned agent outputs. task_id UNIQUE => a double write is a no-op.
    op.create_table(
        "artifacts",
        sa.Column("id", pg.UUID, **UUID_PK),
        sa.Column("project_id", pg.UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", pg.UUID, sa.ForeignKey("tasks.id", ondelete="SET NULL"), unique=True),
        sa.Column("kind", sa.Text, nullable=False),  # niche_report, brand_guideline, wireframe...
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("content", pg.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "kind", "version", name="uq_artifacts_project_kind_version"),
    )

    # Long-term memory: relational row is the source of truth; the vector is a
    # rebuildable retrieval index.
    op.create_table(
        "memories",
        sa.Column("id", pg.UUID, **UUID_PK),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("project_id", pg.UUID, sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("kind", sa.Text, nullable=False),  # brand_decision, audience, keyword, preference...
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(1536)),
        sa.Column("embedding_model", sa.Text),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("superseded_by", pg.UUID, sa.ForeignKey("memories.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_memories_active_lookup", "memories", ["project_id", "kind"],
        postgresql_where=sa.text("is_active"),
    )
    op.execute(
        "CREATE INDEX ix_memories_embedding_hnsw ON memories "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "site_versions",
        sa.Column("id", pg.UUID, **UUID_PK),
        sa.Column("project_id", pg.UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("document", pg.JSONB, nullable=False),  # the Site Document
        sa.Column("checksum", sa.Text, nullable=False),
        sa.Column("changed_sections", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Text, nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "version", name="uq_site_versions_project_version"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("project_id", pg.UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.Text, nullable=False),  # user | manager | <agent name> | system
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_audit_project_ts", "audit_log", ["project_id", "ts"])


def downgrade() -> None:
    for t in ("audit_log", "site_versions", "memories", "artifacts", "tasks", "projects"):
        op.drop_table(t)
