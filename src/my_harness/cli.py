"""Index, backup, retention, metrics backfill and explicit version/help; no inference."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
import sqlite3

from sqlalchemy.exc import SQLAlchemyError

from my_harness.storage.database import make_engine
from my_harness.storage.schema import require_schema
from my_harness.storage.backup import create_backup, restore_backup, verify_bundle
from my_harness.storage.retention import preview_retention, apply_retention, inspect_logs
from my_harness.i18n import DEFAULT_LANGUAGE, LANGUAGES, emission, message, supported


def cli_language(explicit: str | None, database: str | None) -> str:
    """D166: `--ui-language` for this invocation; otherwise the preferences of an existing database; otherwise en.

    The database is opened read-only and never created, migrated or repaired; nothing is saved.
    """
    if explicit is not None:
        return explicit
    path = Path(database).expanduser() if database else None
    if path is None or not path.is_absolute() or not path.is_file():
        return DEFAULT_LANGUAGE
    try:
        with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
            row = db.execute('SELECT format, ui_language FROM product_preferences WHERE id = 1').fetchone()
    except sqlite3.Error:
        return DEFAULT_LANGUAGE
    return row[1] if row and row[0] == 'product-preferences-1' and row[1] in LANGUAGES else DEFAULT_LANGUAGE


def build_parser(language: str = DEFAULT_LANGUAGE) -> argparse.ArgumentParser:
    """Own help texts in `language`; argparse's own messages and usage lines stay as the library writes them."""
    def say(key, **params):
        return message(f'cli.help.{key}', language, **params)

    parser = argparse.ArgumentParser(description=say('description'))
    parser.add_argument('--ui-language', choices=LANGUAGES, help=say('ui_language'))
    operations = parser.add_subparsers(dest='operation', required=True)
    command = operations.add_parser('backup-create', help=say('backup_create'))
    command.add_argument('database', help=say('database_positional'))
    command.add_argument('destination')
    command.add_argument('--artifact-root', action='append', default=[], help=say('backup_artifact_root'))
    command.add_argument('--writers-stopped', action='store_true', help=say('writers_stopped'))
    command = operations.add_parser('backup-verify')
    command.add_argument('bundle')
    command = operations.add_parser('backup-restore', help=say('backup_restore'))
    command.add_argument('bundle')
    command.add_argument('destination')
    for name in ('logs-preview', 'logs-apply'):
        command = operations.add_parser(name, help=say('logs_retention'))
        command.add_argument('database')
        command.add_argument('--artifact-root', action='append', required=True)
        command.add_argument('--before', required=True, help=say('logs_before'))
        command.add_argument('--min-bytes', type=int, default=1024 * 1024)
        if name == 'logs-apply':
            command.add_argument('--preview-sha256', required=True)
            command.add_argument('--reason', required=True)
            command.add_argument('--confirmed', action='store_true')
            command.add_argument('--writers-stopped', action='store_true')
    command = operations.add_parser('logs-inspect', help=say('logs_inspect'))
    command.add_argument('database')
    command.add_argument('attempt_id')
    command = operations.add_parser('diagnose-cli', help=say('diagnose_cli'))
    command.add_argument('configuration', help=say('diagnose_configuration'))
    command = operations.add_parser('check-config', help=say('check_config'))
    command.add_argument('configuration', help=say('check_configuration'))
    command.add_argument('--preflight', action='store_true', help=say('preflight'))
    command = operations.add_parser('metrics-backfill', help=say('metrics_backfill'))
    command.add_argument('--database', required=True, help=say('database_existing'))
    command.add_argument('--artifact-root', action='append', default=[], help=say('metrics_artifact_root'))
    command = operations.add_parser('migrate', help=say('migrate'))
    command.add_argument('--database', required=True, help=say('database_existing'))
    command.add_argument('--snapshots', required=True, help=say('snapshots'))
    command.add_argument('--writers-stopped', action='store_true', help=say('writers_stopped'))
    for name in ('init-db', 'serve'):
        command = operations.add_parser(name, help=say('init_db' if name == 'init-db' else 'serve'))
        command.add_argument('--database', required=True, help=say('database'))
        if name == 'serve':
            command.add_argument('--port', type=int, default=8013)
            command.add_argument('--config', help=say('serve_config'))
            command.add_argument('--configuration-dir', help=say('configuration_dir'))
            command.add_argument('--state-dir', help=say('state_dir'))
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # The help is built before the database is known: `--ui-language` or English (D166).
    early = argparse.ArgumentParser(add_help=False)
    early.add_argument('--ui-language')
    parser = build_parser(supported(early.parse_known_args(argv)[0].ui_language))
    args = parser.parse_args(argv)
    language = cli_language(args.ui_language, getattr(args, 'database', None))
    with emission(language):
        return _run(args, language)


def _run(args, language: str) -> int:
    engine = None
    try:
        if args.operation == 'migrate':
            from dataclasses import asdict
            from my_harness.storage.migrate import migrate_database
            result = migrate_database(args.database, Path(args.snapshots), writers_stopped=args.writers_stopped)
            print(json.dumps(asdict(result), default=str, ensure_ascii=False, indent=2))
            return 0
        if args.operation in ('init-db', 'serve'):
            from my_harness.launcher import initialize, serve
            if args.operation == 'init-db':
                initialize(args.database, language)
            else:
                serve(args.database, args.port, args.config, language,
                      configuration_dir=args.configuration_dir, state_dir=args.state_dir)
            return 0
        if args.operation == 'metrics-backfill':
            from my_harness.launcher import local_database
            from my_harness.storage.metrics import backfill
            path, url = local_database(args.database, language)
            if not path.is_file():
                raise ValueError(message('cli.backfill_missing', language))
            engine = make_engine(url)
            require_schema(engine)
            print(json.dumps(backfill(engine, artifact_roots=args.artifact_root), ensure_ascii=False, indent=2))
            return 0
        if args.operation == 'check-config':
            from my_harness.services.local_config import inspect_local_config, summary
            config, agents = inspect_local_config(args.configuration)
            result = summary(config)
            if args.preflight:
                from my_harness.adapters.cli_agents import access_for
                from my_harness.adapters.cli_diagnostics import preflight_config
                # Defaults and per-role capabilities of each preset; explicit version/help only.
                result['preflight'] = {agent: preflight_config(cli, access=access_for(agent.rsplit('.', 1)[-1]))
                                       for agent, cli in agents.items()}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if not args.preflight or all(r['available'] for r in result['preflight'].values()) else 1
        if args.operation == 'diagnose-cli':
            from my_harness.adapters.cli_diagnostics import diagnose_file
            result = diagnose_file(args.configuration)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if (result.get('preflight') or {}).get('available') else 1
        if args.operation.startswith('logs-'):
            if args.operation == 'logs-inspect':
                result = inspect_logs(args.database, args.attempt_id)
            else:
                kwargs = dict(artifact_roots=args.artifact_root, before=args.before, min_bytes=args.min_bytes)
                if args.operation == 'logs-apply':
                    kwargs.update(preview_sha256=args.preview_sha256, reason=args.reason,
                                  confirmed=args.confirmed, writers_stopped=args.writers_stopped)
                    result = apply_retention(args.database, **kwargs)
                else:
                    result = preview_retention(args.database, **kwargs)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.operation.startswith('backup-'):
            if args.operation == 'backup-create':
                manifest = create_backup(args.database, args.destination, artifact_roots=args.artifact_root,
                                         writers_stopped=args.writers_stopped)
            elif args.operation == 'backup-restore':
                manifest = restore_backup(args.bundle, args.destination)
            else:
                manifest = verify_bundle(args.bundle)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0
    except (OSError, RuntimeError, ValueError, LookupError, SQLAlchemyError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
