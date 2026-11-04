"""D278/D302: confirmed inbox facts and ordinary HTTP commands, with synthetic projects only."""
from datetime import datetime
from hashlib import sha256

from fastapi.testclient import TestClient as AnonymousClient
from my_harness.api.app import create_app
from my_harness.services.managed_runtime import ManagedConfig
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.knowledge import KnowledgeRepository
from my_harness.storage.models import ManagedEventRow, ManagedRunRow
from session_client import TestClient
from test_autonomous_roadmap import BOUNDS, REQUEST, FakeRoadmap, start, world as autonomy_world  # noqa: F401
from test_managed import context, repository  # noqa: F401
from test_managed_api import LOCAL, client, config, make_context
from test_permissions import request as permission_request, setup as permission_world  # noqa: F401
from test_structured_phases import evaluation, prepared, structured  # noqa: F401

INBOX = '/api/managed/inbox'
CSRF = {'X-My-Harness': '1'}
SECRET = 'sk-synthetic012345678901234567890'


def listing(http, **params):
    response = http.get(INBOX, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def detail(http, item, project=None):
    response = http.get(f"{INBOX}/{item['id']}", params={'project': project or item['project_id']})
    assert response.status_code == 200, response.text
    return response.json()


def mark(http, item, project=None):
    return http.post(f"{INBOX}/{item['id']}/read", json={'project_id': project or item['project_id']}, headers=CSRF)


def test_committed_manual_facts_read_state_stale_ready_and_archive(structured, migrated_database, tmp_path):
    w = structured
    phase_id = prepared(w)
    url = migrated_database[0]
    managed = config(w.context, w.ports, supervisor=False)
    phase_path = f'/api/managed/phases/{phase_id}'
    foreign = KnowledgeRepository(w.repository.engine).project(str(tmp_path / 'foreign'))
    with client(url, tmp_path, managed) as http:
        first = listing(http, project='synthetic', limit=1)
        assert len(first['items']) == 1 and first['next_before']
        [ready] = first['items']
        [task] = listing(http, project=w.project, before=first['next_before'], limit=1)['items']
        assert ready['topic'] == 'phase_ready' and not ready['resolved'] and ready['current_state'] == 'READY_TO_CLOSE'
        assert task['topic'] == 'task_completed' and task['kind'] == 'notification' and task['resolved']
        assert task['evidence_id'] and task['operation_id'] and task['run_id']
        assert listing(http, project=foreign)['items'] == []
        assert http.get(f"{INBOX}/{ready['id']}", params={'project': foreign}).status_code == 404
        assert mark(http, ready, foreign).status_code == 404
        assert http.get(INBOX, params={'project': foreign, 'before': task['id']}).status_code == 404
        assert http.get(INBOX, params={'limit': 101}).status_code == 422
        assert http.get(INBOX, params={'kind': 'unknown'}).status_code == 422

        read = mark(http, ready).json()
        assert read['read_at'] and not read['resolved'] and mark(http, ready).json() == read
        assert ready['id'] not in {i['id'] for i in listing(http, state='unread')['items']}
        assert listing(http, state='unresolved')['items'] == [read]

        # Structured phase events already have trace mirrors. A repeated commit delivery names the same effect.
        with w.repository._write() as session:
            run = session.get(ManagedRunRow, task['run_id'])
            original = session.get(ManagedEventRow, int(task['event_id']))
            w.repository._event(session, run, original.kind, original.payload)
        assert listing(http, kind='notification')['items'] == [task]

        current = http.get(phase_path).json()
        close = {'action': 'close', 'expected_version': current['version'], 'confirmed': True,
                 'binding_sha256': current['ready']['binding_sha256'], 'reason': 'Synthetic confirmation.', 'ttl_seconds': 3600}
        assert http.post(f'{phase_path}/questions', json={'expected_version': current['version'],
                         'text': f'Which output is intended? {SECRET}'}).status_code == 201
        refused = http.post(f'{phase_path}/actions', json=close, headers={'Idempotency-Key': 'stale-ready'})
        assert refused.status_code == 409, refused.text
        assert detail(http, ready)['current_state'] == 'BLOCKED'
        [item] = listing(http, kind='question')['items']
        reply = detail(http, item)
        assert SECRET not in str(reply) and reply['context'] == ['Which output is intended? [REDACTED]']
        assert 'root' not in reply and 'payload' not in reply
        binding = reply['response']
        path = f"{phase_path}/questions/{item['request_id']}/answer"
        body = {'expected_version': binding['version'], 'expected_question_version': binding['request_version'],
                'answer': 'Keep the documented output.', 'confirmed': True}
        assert http.post(path, json={**body, 'confirmed': False}).status_code == 422
        assert http.post(path, json={**body, 'expected_question_version': 99}).status_code == 409
        assert http.post(path, json=body).status_code == 200
        assert http.post(path, json=body).status_code == 409
        assert detail(http, item)['resolved'] and not detail(http, item)['read_at']

        w.check(phase_id, evaluation(w, phase_id))
        latest = http.get(phase_path).json()
        closed = http.post(f'{phase_path}/actions',
                           json={**close, 'expected_version': latest['version'],
                                 'binding_sha256': latest['ready']['binding_sha256']},
                           headers={'Idempotency-Key': 'current-ready'})
        assert closed.status_code == 202, closed.text
        w.run()
        notices = listing(http, kind='notification')['items']
        assert {i['topic'] for i in notices} == {'task_completed', 'phase_closed'}
        [closure] = [i for i in notices if i['topic'] == 'phase_closed']
        assert closure['current_state'] == 'CLOSED' and closure['run_id'] != task['run_id']
        assert detail(http, ready)['resolved'] and detail(http, ready)['read_at'] == read['read_at']

    with client(url, tmp_path, managed) as http:
        assert detail(http, ready)['read_at'] == read['read_at']
        assert listing(http, kind='notification')['items'] == notices
    create_backup(url.removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = tmp_path / 'restored/state.sqlite3'
    before = sha256(restored.read_bytes()).hexdigest()
    app = create_app(f'sqlite:///{restored}', managed=ManagedConfig(supervisor=False))
    with TestClient(app, base_url=LOCAL) as http:
        archived = detail(http, item)
        assert archived['context'] == reply['context'] and archived['response'] is None
        assert archived['registered_project_id'] is None and detail(http, ready)['read_at'] == read['read_at']
        assert {i['id'] for i in listing(http, kind='notification')['items']} == {i['id'] for i in notices}
        assert mark(http, item).status_code == 409
        assert http.post(path, json=body, headers=CSRF).status_code == 409
    assert sha256(restored.read_bytes()).hexdigest() == before


def test_permission_binding_expiry_and_http_protection(permission_world, migrated_database, tmp_path):
    w = permission_world
    url = migrated_database[0]
    repo, _, run_id, _, _, context = w
    expired = permission_request(w, kind='network', ttl_seconds=60)
    pending = permission_request(w)
    app = create_app(url, managed=config(context, supervisor=False))
    with AnonymousClient(app, base_url=LOCAL) as anonymous:
        assert anonymous.get(INBOX).status_code == 401
        assert anonymous.post(f"{INBOX}/run-permission:{pending['id']}/read",
                              json={'project_id': 'synthetic'}, headers=CSRF).status_code == 401
    with TestClient(app, base_url=LOCAL) as http:
        rows = {i['request_id']: i for i in listing(http, kind='permission', mode='manual')['items']}
        item = rows[pending['id']]
        assert item['run_id'] == run_id and not item['resolved']
        path = f"{INBOX}/{item['id']}/read"
        body = {'project_id': 'synthetic'}
        assert http.post(path, json=body).status_code == 403
        assert http.post(path, json=body, headers={**CSRF, 'Origin': 'https://foreign.invalid'}).status_code == 403
        assert http.get(INBOX, headers={'Host': 'foreign.invalid'}).status_code == 403
        assert mark(http, item).status_code == 200 and not detail(http, item)['resolved']
        bind = detail(http, item)['response']
        values = {'expected_version': bind['version'], 'expected_request_version': bind['request_version'],
                  'fingerprint': bind['proof'], 'decision': 'grant', 'scope': 'once',
                  'reason': 'Synthetic decision.', 'confirmed': True}
        decide = f"/api/managed/runs/{run_id}/permissions/{pending['id']}/decision"
        assert http.post(decide, json={**values, 'fingerprint': '0' * 64}, headers=CSRF).status_code == 409
        assert http.post(decide, json=values, headers=CSRF).json()['status'] == 'GRANTED'
        assert http.post(decide, json=values, headers=CSRF).status_code == 409
        assert detail(http, item)['resolved'] and detail(http, item)['response'] is None

        expiring = rows[expired['id']]
        bind = detail(http, expiring)['response']
        app.state.runtime.repository.clock = lambda: datetime.fromisoformat(expired['expires_at'])
        assert detail(http, expiring)['resolved'] and detail(http, expiring)['response'] is None
        late = http.post(f"/api/managed/runs/{run_id}/permissions/{expired['id']}/decision",
                         json={**values, 'expected_version': bind['version'], 'fingerprint': bind['proof']}, headers=CSRF)
        assert late.status_code == 409, late.text
        assert repo.get_run(run_id).status != 'RUNNING'


def test_autonomous_questions_stop_and_explicit_resume(autonomy_world, context, migrated_database, tmp_path, monkeypatch):
    w = autonomy_world
    fake = FakeRoadmap(w.root, ['P001'])
    fake.after_adopt['P001'] = lambda phase: phase['questions'].append('synthetic-blocker')
    fake.task_script['P001-T001'] = ['failed']
    service, run = start(w, fake, request={**REQUEST, 'bounds': {**BOUNDS, 'task_attempts': 1}})
    other = tmp_path / 'other-project'
    other.mkdir()
    from dataclasses import replace
    managed = config(context, supervisor=False)
    managed = replace(managed, projects=managed.projects + config(make_context(other), project='other', supervisor=False).projects)
    with client(migrated_database[0], tmp_path, managed) as http:
        monkeypatch.setattr(http.app.state.runtime, 'autonomous_roadmap', lambda: service)
        [item] = listing(http, mode='autonomous', kind='question')['items']
        assert item['run_id'] == run['id'] and item['request_id'] == run['questions'][0]['id']
        assert listing(http, mode='manual')['items'] == []
        assert mark(http, item).status_code == 200 and not detail(http, item)['resolved']
        run_path = f"/api/managed/projects/synthetic/autonomous/runs/{run['id']}"
        question_path = f"{run_path}/questions/{item['request_id']}/answer"
        payload = {'expected_version': detail(http, item)['response']['request_version'], 'text': 'Synthetic answer.'}
        assert http.get(run_path.replace('/synthetic/', '/other/')).status_code == 404
        assert http.post(question_path.replace('/synthetic/', '/other/'), json=payload,
                         headers={'Idempotency-Key': 'wrong-project'}).status_code == 404
        assert http.post(f'{run_path}/resume', json={'expected_version': run['version']}).status_code == 409
        assert http.post(question_path, json={**payload, 'expected_version': 99},
                         headers={'Idempotency-Key': 'stale'}).status_code == 409
        header = {'Idempotency-Key': 'same-answer'}
        answered = http.post(question_path, json=payload, headers=header)
        assert answered.status_code == 200, answered.text
        assert http.post(question_path, json=payload, headers=header).json() == answered.json()
        assert detail(http, item)['resolved'] and detail(http, item)['read_at']
        still_waiting = http.get(run_path).json()
        assert still_waiting['status'] == 'WAITING_FOR_OWNER'
        fake.phases['P001']['questions'].clear()
        failed = http.post(f'{run_path}/resume', json={'expected_version': still_waiting['version']}).json()
        assert failed['status'] == 'FAILED'
        [stop] = listing(http, kind='lifecycle')['items']
        assert stop['topic'] == 'failed' and not stop['resolved']
        assert http.post(f'{run_path}/resume', json={'expected_version': still_waiting['version']}).status_code == 409
        limit = http.post(f'{run_path}/resume', json={'expected_version': failed['version']}).json()
        assert limit['status'] == 'LIMIT_REACHED'
        assert detail(http, stop)['resolved'] and detail(http, stop)['current_state'] == 'LIMIT_REACHED'
        revise = {**REQUEST, 'bounds': {**BOUNDS, 'task_attempts': 2}}
        preview = http.post(f'{run_path}/revision-preview', json={'request': revise, 'expected_version': limit['version']})
        assert preview.status_code == 200, preview.text
        assert preview.json()['run_version'] == limit['version']
        assert http.post(f'{run_path}/revision-preview', json={'request': revise, 'expected_version': failed['version']}).status_code == 409
        confirm = {'request': revise, 'preview_sha256': preview.json()['preview_sha256'], 'reason': 'Confirm new bound.',
                   'confirmed': True, 'acknowledgement_version': service.policy.acknowledgement_version}
        completed = http.post(f'{run_path}/revise', json=confirm, headers={'Idempotency-Key': 'revise'})
        assert completed.status_code == 200, completed.text
        assert completed.json()['status'] == 'COMPLETED'
        assert listing(http, kind='lifecycle', state='unresolved')['items'] == []
