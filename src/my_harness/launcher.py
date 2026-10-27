"""Installed entry point: explicit SQLite, separate preparation and fixed loopback."""
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from my_harness.i18n import current, message
from my_harness.storage.database import make_engine
from my_harness.storage.schema import require_schema


def local_database(value: str, language: str | None = None) -> tuple[Path, str]:
    language = language or current()  # the CLI passes its own; other callers follow the emission
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(message('cli.database_not_absolute', language))
    return path, URL.create('sqlite', database=str(path)).render_as_string(hide_password=False)


def initialize(value: str, language: str | None = None) -> None:
    language = language or current()
    path, url = local_database(value, language)
    # Exclusive: never migrate or overwrite an existing database (including links).
    if any(Path(str(path) + suffix).exists() or Path(str(path) + suffix).is_symlink()
           for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError(message('cli.auxiliary_files', language))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb'):
            pass
    except FileExistsError as error:
        raise ValueError(message('cli.destination_exists', language)) from error
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).parent / 'migrations').replace('%', '%%'))
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')


def serve(value: str, port: int, config: str | None = None, language: str | None = None, *,
          configuration_dir: str | None = None, state_dir: str | None = None) -> None:
    language = language or current()
    import uvicorn
    from my_harness.api.app import create_app
    from my_harness.services.managed_runtime import CONFIG_ENV

    if config is not None and os.environ.get(CONFIG_ENV):
        raise ValueError(message('cli.config_conflict', language, variable=CONFIG_ENV))
    path, url = local_database(value, language)
    if not 1 <= port <= 65535:
        raise ValueError(message('cli.port_range', language))
    if not path.is_file():
        raise ValueError(message('cli.database_missing', language))
    assets = Path(__file__).parent / 'web'
    if not (assets / 'index.html').is_file():
        raise ValueError(message('cli.assets_missing', language))
    engine = make_engine(url)
    try:
        require_schema(engine)
    except RuntimeError as error:
        raise RuntimeError(message('cli.schema_incompatible', language)) from error
    finally:
        engine.dispose()
    directory = Path(configuration_dir) if configuration_dir else path.parent / 'configuration'
    # Restored query mode takes priority in the runtime, before loading any external file.
    uvicorn.run(create_app(url=url, configuration_dir=directory, state_dir=Path(state_dir) if state_dir else path.parent,
                          config_source=Path(config) if config else None),
                host='127.0.0.1', port=port, workers=1, proxy_headers=False, access_log=False)
