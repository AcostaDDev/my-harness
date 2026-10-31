"""P002-T005 (D286): owner routes of the typed knowledge operations (E13, E20 of the T005 record; TM18).

Synthetic project and knowledge on temporary SQLite; the real app, session exchange, guards and backup/restore.
"""
from contextlib import closing
import sqlite3

from fastapi.testclient import TestClient as AnonymousClient
from session_client import TestClient

from my_harness.api.app import create_app
from my_harness.api.schemas import KnowledgeAdoptCreate, KnowledgeDraftChangesCreate, KnowledgeDraftOpenCreate
from my_harness.core.engine.domain_catalogue import CATALOGUE
from my_harness.services.managed_runtime import ManagedConfig
from my_harness.storage.backup import create_backup, restore_backup
from test_managed_api import LOCAL, config, make_context

H = {'X-My-Harness': '1'}


def dump(path):
    with closing(sqlite3.connect(path)) as db:
        return {t: db.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() for t in (
            'knowledge_revisions', 'knowledge_revision_members', 'domain_commands')}


def journey(http):
    base = '/api/managed/projects/synthetic/knowledge/drafts'
    absent = http.get('/api/managed/projects/synthetic/knowledge').json()
    assert absent['revision'] is None and absent['knowledge_project_id'] is None
    opened = http.post(base, json={'expected_revision_id': None}, headers={**H, 'Idempotency-Key': 'o1'})
    assert opened.status_code == 201, opened.text
    draft = opened.json()
    again = http.post(base, json={'expected_revision_id': None}, headers={**H, 'Idempotency-Key': 'o1'})
    assert again.json()['replayed'] is True and again.json()['draft_id'] == draft['draft_id']
    applied = http.post(f"{base}/{draft['draft_id']}/changes", headers={**H, 'Idempotency-Key': 'a1'}, json={
        'expected_draft_sha256': draft['draft_sha256'], 'changes': [
            {'op': 'put', 'kind': 'requirement', 'code': 'R001', 'provenance': 'known',
             'content': {'title': 'Sign in', 'statement': '  Kept verbatim.  ', 'status': 'active'}}]})
    assert applied.status_code == 200, applied.text
    preview = http.post(f"{base}/{draft['draft_id']}/adoption/preview", headers=H).json()
    assert preview['reason_required'] is True and preview['classification'][0]['class'] == 'owner_only'
    adopted = http.post(f"{base}/{draft['draft_id']}/adopt", headers={**H, 'Idempotency-Key': 'ad1'}, json={
        'expected_revision_id': None, 'preview_sha256': preview['preview_sha256'], 'reason': 'First.'})
    assert adopted.status_code == 200 and adopted.json()['origin'] == 'owner_confirmed'
    project = draft['knowledge_project_id']
    head = http.get(f'/api/managed/knowledge/projects/{project}').json()
    items = http.get(f'/api/managed/knowledge/projects/{project}/revisions/1/items').json()
    item = http.get(f"/api/managed/knowledge/projects/{project}/revisions/1/items/{items['items'][0]['item_id']}")
    assert head['revision']['number'] == 1 and item.json()['item']['content']['statement'] == '  Kept verbatim.  '
    return project, draft['draft_id'], head


def test_owner_routes_share_the_service_and_keep_every_guard(migrated_database, tmp_path):
    url = migrated_database[0]
    (tmp_path / 'checkout').mkdir()
    app = create_app(url, tmp_path / 'ui', managed=config(make_context(tmp_path / 'checkout')))
    with TestClient(app, base_url=LOCAL) as http:
        project, _draft, _head = journey(http)
        path = '/api/managed/projects/synthetic/knowledge/drafts'
        before = dump(url.removeprefix('sqlite:///'))
        assert http.post(path, json={'expected_revision_id': None}, headers={'Idempotency-Key': 'x'}
                         ).json()['detail']['code'] == 'csrf_header_required'
        assert http.post(path, json={'expected_revision_id': None}, headers=H).status_code == 422  # no key
        cross = http.post(path, json={'expected_revision_id': None},
                          headers={**H, 'Idempotency-Key': 'x', 'Origin': 'http://evil.example'})
        assert cross.json()['detail']['code'] == 'origin_rejected'
        fetched = http.post(path, json={'expected_revision_id': None},
                            headers={**H, 'Idempotency-Key': 'x', 'Sec-Fetch-Site': 'cross-site'})
        assert fetched.status_code == 403 and fetched.json()['detail']['code'] == 'origin_rejected'
        assert http.get(f'/api/managed/knowledge/projects/{project}',
                        headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        forged = http.post(path, json={'expected_revision_id': None, 'project_id': 'other'},
                           headers={**H, 'Idempotency-Key': 'f'})
        assert forged.status_code == 422
        stale = http.post(path, json={'expected_revision_id': None}, headers={**H, 'Idempotency-Key': 's'})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'stale_revision'
        assert http.post('/api/managed/projects/absent/knowledge/drafts', json={'expected_revision_id': None},
                         headers={**H, 'Idempotency-Key': 'u'}).json()['detail']['code'] == 'project_unregistered'
        assert dump(url.removeprefix('sqlite:///'))['knowledge_revisions'] == before['knowledge_revisions']
    with AnonymousClient(app, base_url=LOCAL) as anonymous:
        assert anonymous.get(f'/api/managed/knowledge/projects/{project}').status_code == 401
    with TestClient(app, base_url='http://evil.example') as foreign:
        assert foreign.get('/api/managed/knowledge/projects').status_code == 403


def test_request_models_mirror_the_catalogue_inputs():
    for model, operation, path in ((KnowledgeDraftOpenCreate, 'knowledge.draft.open', set()),
                                   (KnowledgeDraftChangesCreate, 'knowledge.draft.apply', {'draft_id'}),
                                   (KnowledgeAdoptCreate, 'knowledge.adopt', {'draft_id'})):
        assert set(model.model_fields) | path == set(CATALOGUE.current(operation).input['properties'])


def test_restored_archive_reads_knowledge_from_persisted_data_only(migrated_database, tmp_path):
    url = migrated_database[0]
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    app = create_app(url, tmp_path / 'ui', managed=config(make_context(checkout)))
    with TestClient(app, base_url=LOCAL) as http:
        project, draft, head = journey(http)
        http.post('/api/managed/projects/synthetic/knowledge/drafts', headers={**H, 'Idempotency-Key': 'o2'},
                  json={'expected_revision_id': head['revision']['id']})
        expected = {'head': head, 'items': http.get(f'/api/managed/knowledge/projects/{project}/revisions/1/items')
                    .json(), 'draft': http.get(f'/api/managed/knowledge/projects/{project}/drafts/{draft}').json()}
    create_backup(url.removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = tmp_path / 'restored/state.sqlite3'
    before = dump(restored)
    archive = create_app(f'sqlite:///{restored}', tmp_path / 'ui', managed=ManagedConfig(supervisor=True))
    with TestClient(archive, base_url=LOCAL) as http:
        for suffix in ('/history', '/revisions/1', '/revisions/1/search?query=verbatim'):
            response = http.get(f'/api/managed/knowledge/projects/{project}{suffix}')
            assert response.status_code == 200, response.text
        assert http.get('/api/managed/knowledge/projects').json()['items'][0]['id'] == project
        assert http.get(f'/api/managed/knowledge/projects/{project}').json() == expected['head']
        assert http.get(f'/api/managed/knowledge/projects/{project}/revisions/1/items').json() == expected['items']
        assert http.get(f'/api/managed/knowledge/projects/{project}/drafts/{draft}').json() == expected['draft']
        for route in ('drafts', f'drafts/{draft}/changes', f'drafts/{draft}/discard',
                      f'drafts/{draft}/adoption/preview', f'drafts/{draft}/adopt'):
            refused = http.post(f'/api/managed/projects/synthetic/knowledge/{route}', json={},
                                headers={**H, 'Idempotency-Key': 'r'})
            assert refused.status_code == 409 and refused.json()['code'] == 'restored_read_only'
    assert dump(restored) == before


def test_editor_history_preview_search_and_stale_consent(migrated_database, tmp_path):
    url = migrated_database[0]
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    app = create_app(url, tmp_path / 'ui', managed=config(make_context(checkout)))
    with TestClient(app, base_url=LOCAL) as http:
        project, _, head = journey(http)
        read = f'/api/managed/knowledge/projects/{project}'
        base = '/api/managed/projects/synthetic/knowledge/drafts'
        old = http.get(f'{read}/revisions/1').json()
        assert old['revision']['actor']['principal'] == 'owner'
        assert old['contexts'] == [] and old['readiness'] == 'unassociated'
        assert http.get(f'{read}/history').json()['revisions'][0]['id'] == head['revision']['id']
        for suffix in ('/history?actor=forged', '/revisions/1?revision=2', '/revisions/1/search?query=x&query=y'):
            assert http.get(read + suffix).status_code == 422
        found = http.get(f'{read}/revisions/1/search?query=verbatim').json()
        assert found['page']['total'] == 1
        opened = http.post(base, json={'expected_revision_id': head['revision']['id']},
                           headers={**H, 'Idempotency-Key': 'edit-open'}).json()
        path = f"{base}/{opened['draft_id']}"
        change = {'op': 'put', 'kind': 'requirement', 'code': 'R001', 'provenance': 'known',
                  'content': {'title': 'Changed', 'statement': '**Rich**\n```mermaid\ngraph TD; A-->B\n```', 'status': 'active'}}
        body = {'expected_draft_sha256': opened['draft_sha256'], 'changes': [change]}
        applied = http.post(f'{path}/changes', json=body, headers={**H, 'Idempotency-Key': 'edit'}).json()
        preview = http.post(f'{path}/adoption/preview', headers=H).json()
        assert preview['comparison']['items'][0]['before'] == old['members'][0]
        assert preview['comparison']['items'][0]['after']['content'] == change['content']
        assert http.post(f'{path}/changes', json=body, headers={**H, 'Idempotency-Key': 'stale-edit'}).status_code == 409
        consent = {'expected_revision_id': head['revision']['id'], 'preview_sha256': preview['preview_sha256'], 'reason': 'Review'}
        # A later edit invalidates the displayed consent even when the head has not advanced.
        change['content']['title'] = 'Later edit'
        http.post(f'{path}/changes', json={'expected_draft_sha256': applied['draft_sha256'], 'changes': [change]},
                  headers={**H, 'Idempotency-Key': 'later'})
        assert http.post(f'{path}/adopt', json=consent, headers={**H, 'Idempotency-Key': 'stale-consent'}).json()['detail']['code'] == 'preview_stale'
        preview = http.post(f'{path}/adoption/preview', headers=H).json()
        consent['preview_sha256'] = preview['preview_sha256']
        first = http.post(f'{path}/adopt', json=consent, headers={**H, 'Idempotency-Key': 'accepted'})
        assert first.status_code == 200, first.text
        assert http.post(f'{path}/adopt', json=consent, headers={**H, 'Idempotency-Key': 'accepted'}).json()['replayed']
        current = http.get(f'{read}/revisions/2').json()
        assert current['members'][0] == preview['comparison']['items'][0]['after']
        assert http.get(f'{read}/revisions/1').json() == old
        assert http.get('/api/managed/knowledge/projects/foreign/revisions/1').status_code == 404
        assert http.get(f'{read}/revisions/2/search?query=x', headers={'Origin': 'http://evil.example'}).status_code == 403
