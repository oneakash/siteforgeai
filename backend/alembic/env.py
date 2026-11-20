from sqlalchemy import create_engine

from alembic import context
from app.config import SQLALCHEMY_URL

config = context.config
target_metadata = None  # hand-written migrations; no autogenerate


def run_migrations_offline() -> None:
    context.configure(url=SQLALCHEMY_URL, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(SQLALCHEMY_URL)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
