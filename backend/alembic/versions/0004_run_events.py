"""run_events: durable, ordered progress events (replayable by the UI after a refresh)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE run_events (
          id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          ts         timestamptz NOT NULL DEFAULT now(),
          type       text NOT NULL,          -- phase | task | log
          stage      text,                   -- phase name or task key
          status     text,                   -- running | completed | failed | ...
          message    text NOT NULL,          -- human-readable, shown in the UI
          data       jsonb NOT NULL DEFAULT '{}'
        )
    """)
    # the SSE endpoint's only query: "events of this project after id N, in order"
    op.execute("CREATE INDEX ix_run_events_project_id ON run_events (project_id, id)")


def downgrade() -> None:
    op.execute("DROP TABLE run_events")
