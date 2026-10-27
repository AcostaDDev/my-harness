import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url

from my_harness.i18n import tr


def database_url() -> str:
    return os.environ.get("HARNESS_DATABASE_URL", "sqlite:///.local/harness.sqlite3")


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise ValueError(tr('database.local_file'))
    # The directory is created when connecting, never when exporting OpenAPI.
    engine = create_engine(url, connect_args={"check_same_thread": False, "autocommit": False})

    @event.listens_for(engine, "do_connect")
    def prepare_directory(dialect, connection_record, args, params):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, connection_record):
        previous = connection.autocommit
        connection.autocommit = True
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            from my_harness.storage.backup import RESTORED_USER_VERSION
            cursor.execute("PRAGMA user_version")
            version = cursor.fetchone()[0]
            if version not in (0, RESTORED_USER_VERSION):
                raise RuntimeError(tr('database.restore_version'))
            restored = version == RESTORED_USER_VERSION
            if restored:
                cursor.execute("PRAGMA query_only=ON")
            else:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()
            connection.autocommit = previous

    return engine
