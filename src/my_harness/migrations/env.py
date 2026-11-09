from alembic import context

from my_harness.storage.database import database_url, make_engine
from my_harness.storage.models import Base


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=context.config.attributes.get("database_url") or database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (connection := context.config.attributes.get("connection")) is not None:
    run_migrations(connection)
else:
    engine = make_engine(context.config.attributes.get("database_url") or database_url())
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
