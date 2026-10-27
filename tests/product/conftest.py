from pathlib import Path
import shutil

from alembic import command
from alembic.config import Config
import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def _migrated_template(tmp_path_factory):
    """A single real migration to head per session; each test gets a copy of the closed file."""
    path = tmp_path_factory.mktemp("migrated") / "template.sqlite3"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESS_DATABASE_URL", f"sqlite:///{path}")
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    assert not path.with_name(path.name + "-wal").exists()
    return path


@pytest.fixture
def migrated_database(tmp_path, monkeypatch, _migrated_template):
    target = tmp_path / "synthetic.sqlite3"
    shutil.copyfile(_migrated_template, target)
    url = f"sqlite:///{target}"
    monkeypatch.setenv("HARNESS_DATABASE_URL", url)
    return url, Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def _legacy_close(monkeypatch):
    """Simulates the previous producer to verify its frozen operations and their reconciliation.

    The new T004 tests use the real producer, without this fixture.
    """
    from my_harness.storage import closure
    from my_harness.storage.transition import TransitionRepository
    original = closure.prepare
    monkeypatch.setattr(closure, 'prepare', lambda context, state, git:
                        None if state['phase']['status'] == 'CLOSED' else original(context, state, git))
    monkeypatch.setattr(TransitionRepository, '_retired', lambda self: None)


def pytest_configure(config):
    config.addinivalue_line('markers', 'unconfirmed_work_language: keep the real admission gate of D167 for roots '
                                       'without a confirmed work language')


@pytest.fixture(autouse=True)
def _confirmed_work_language(request, monkeypatch):
    """Most tests are not about languages (D167): a root without a work language gets a synthetic `en` confirmation,
    written as a real row, when the service installs its project (as an operator confirmation would before any work)
    or, for tests of the storage alone, when its first job is admitted. Before an Alembic downgrade, only these
    synthetic rows are removed, so the round trips of older revisions keep working while 0025 still refuses to drop
    a real confirmation. Tests of the gate itself opt out with `@pytest.mark.unconfirmed_work_language`."""
    if request.node.get_closest_marker('unconfirmed_work_language'):
        return
    from my_harness.services.managed_runtime import ManagedRuntime
    from my_harness.storage import work_language
    capture, bind = work_language.capture, ManagedRuntime.with_work_language

    def confirm(session, root):
        if work_language.get(session, root) is None:
            work_language.associate(session, root=str(root), project_id='synthetic', work_language='en',
                                    source='migration', confirmation={'synthetic': 'tests/product/conftest.py'},
                                    now='2026-01-01T00:00:00.000000+00:00')

    def confirmed_capture(session, root):
        confirm(session, root)
        return capture(session, root)

    def confirmed_bind(runtime, project):
        from my_harness.storage.backup import is_read_only_archive
        if not is_read_only_archive(runtime.engine):
            with runtime.repository._write() as session:
                confirm(session, project.context.root)
        return bind(runtime, project)
    def downgrade(config, revision, *args, **kwargs):
        import os
        import sqlite3
        from contextlib import closing
        url = os.environ.get('HARNESS_DATABASE_URL', '')
        database = url.removeprefix('sqlite:///')
        synthetic = ("FROM project_work_languages WHERE json_extract(confirmation, '$.synthetic') "
                     "= 'tests/product/conftest.py'")
        if url.startswith('sqlite:///') and os.path.exists(database):
            # Read-only first: a database without synthetic rows is not even opened for writing.
            with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as db:
                found = (db.execute("SELECT name FROM sqlite_master WHERE name = 'project_work_languages'").fetchone()
                         and db.execute('SELECT count(*) ' + synthetic).fetchone()[0])
            if found:
                with closing(sqlite3.connect(database)) as db, db:
                    db.execute('DELETE ' + synthetic)
        return original_downgrade(config, revision, *args, **kwargs)
    from alembic import command
    original_downgrade = command.downgrade
    monkeypatch.setattr(work_language, 'capture', confirmed_capture)
    monkeypatch.setattr(ManagedRuntime, 'with_work_language', confirmed_bind)
    monkeypatch.setattr(command, 'downgrade', downgrade)
