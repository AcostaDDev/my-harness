"""P002-T023/Q4: canonical read-only map documents, isolation and a checkout-free restored copy."""
from pathlib import Path
from fastapi.testclient import TestClient as AnonymousClient
from session_client import TestClient
from my_harness.api.app import create_app
from my_harness.services.managed_runtime import ManagedConfig
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.knowledge import KnowledgeRepository
from test_managed_api import LOCAL, client, config, make_context
from test_work_map import world, table_marks  # noqa: F401
from test_structured_phases import structured, prepared  # noqa: F401
from test_managed import context, repository  # noqa: F401
from test_git import repo as git_repo  # noqa: F401


def read_documents(http, project, path=None, status=200):
    response = http.get(f'/api/managed/map/projects/{project}/documents', params={'path': path} if path else {})
    assert response.status_code == status, response.text
    return response.json()


def test_map_documents_canonical_isolated_and_restored_without_checkout(world, tmp_path, monkeypatch):
    w = world
    path = Path(w.url.removeprefix('sqlite:///'))
    before = table_marks(path)
    with client(w.url, tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        tree = read_documents(http, w.project)
        assert tree['source'] == 'canonical' and tree['content'] is None
        assert tree['revision_id'] == KnowledgeRepository(w.repository.engine).head(w.project).id
        paths = [file['path'] for file in tree['tree']['files']]
        assert 'docs/NEXT_STEPS.md' in paths and 'docs/ROADMAP.md' in paths
        assert all(file['editable'] is False for file in tree['tree']['files'])
        assert all(p.endswith('.md') for p in paths)
        assert 'portable' not in tree and 'files' not in tree
        document = read_documents(http, 'synthetic', 'docs/NEXT_STEPS.md')
        bundle = http.get('/api/managed/projects/synthetic/knowledge/documents/bundle').json()['result']
        assert document['content'] == bundle['files']['docs/NEXT_STEPS.md']
        assert document['path'] == 'docs/NEXT_STEPS.md'
        read_documents(http, 'foreign-project', status=404)
        for invalid in ('../../secret.md', 'docs/.harness/knowledge.json', '/etc/passwd', 'absent.md'):
            read_documents(http, w.project, invalid, status=404)
    assert table_marks(path) == before
    create_backup(path, tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = tmp_path / 'restored/state.sqlite3'
    w.context.root.rename(tmp_path / 'offline-synthetic-checkout')
    assert not w.context.root.exists()
    marks = table_marks(restored)
    app = create_app(f'sqlite:///{restored}', tmp_path / 'archive-ui', managed=ManagedConfig(supervisor=False))
    # Make any accidental runtime composition fail: restored consultation must remain SQLite-only.
    from my_harness.services.managed_runtime import ManagedRuntime
    monkeypatch.setattr(ManagedRuntime, 'project', lambda *args: (_ for _ in ()).throw(AssertionError('checkout composition')))
    with TestClient(app, base_url=LOCAL) as http:
        assert read_documents(http, w.project) == tree
        assert read_documents(http, w.project, 'docs/NEXT_STEPS.md') == document
        read_documents(http, 'foreign-project', status=404)
        refused = http.post(f'/api/managed/projects/{w.project}/knowledge/documents/adopt', json={}, headers={'X-My-Harness': '1'})
        assert refused.status_code == 409
    assert table_marks(restored) == marks
    with AnonymousClient(app, base_url=LOCAL) as http:
        assert http.get(f'/api/managed/map/projects/{w.project}/documents').status_code == 401
    with AnonymousClient(app, base_url='http://foreign.invalid') as http:
        assert http.get(f'/api/managed/map/projects/{w.project}/documents').status_code in (400, 403)


def test_map_documents_legacy_archive_never_requests_checkout(world, tmp_path):
    # A persisted run-root identity with no knowledge is still navigable, but has no canonical docs.
    from sqlalchemy import text
    w = world
    legacy_root = str(tmp_path / 'legacy-checkout')
    Path(legacy_root).mkdir()
    with w.repository.engine.begin() as db:
        db.execute(text("UPDATE managed_runs SET root = :root WHERE id = (SELECT id FROM managed_runs LIMIT 1)"), {'root': legacy_root})
        run = db.scalar(text('SELECT id FROM managed_runs WHERE root = :root'), {'root': legacy_root})
    with client(w.url, tmp_path, config(make_context(legacy_root), w.ports, supervisor=False)) as http:
        ordinary = read_documents(http, 'run:' + run)
        assert ordinary['source'] == 'checkout' and ordinary['tree']['files'] == []
    with client(w.url, tmp_path, ManagedConfig(supervisor=False)) as http:
        assert read_documents(http, 'run:' + run)['source'] == 'unavailable'
    create_backup(w.url.removeprefix('sqlite:///'), tmp_path / 'legacy-backup', writers_stopped=True)
    restore_backup(tmp_path / 'legacy-backup', tmp_path / 'legacy-restored')
    restored = tmp_path / 'legacy-restored/state.sqlite3'
    app = create_app(f'sqlite:///{restored}', tmp_path / 'legacy-ui', managed=ManagedConfig(supervisor=False))
    with TestClient(app, base_url=LOCAL) as http:
        assert read_documents(http, 'run:' + run)['source'] == 'unavailable'
