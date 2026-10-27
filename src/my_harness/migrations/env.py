from alembic import context

from my_harness.storage.database import database_url, make_engine
from my_harness.storage.models import Base


if context.is_offline_mode():
    context.configure(url=context.config.attributes.get("database_url") or database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(context.config.attributes.get("database_url") or database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata,
                              transactional_ddl=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
