"""H5.7 journeys: real API/session, SQLite and Git; only agent/command ports are fake.

Restart means a new application lifespan over the same database. Fault injection
is deterministic; real process crashes remain covered by the CLI/Git suites.
"""
from dataclasses import replace
import time

import pytest
from fastapi.testclient import TestClient

from my_harness.api.app import create_app
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.core.engine.permissions import LAYERS
from my_harness.core.engine.validation import CommandResult
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from test_bootstrap import DATA
from test_managed_api import (LOCAL, RUN, STOPPED, VERSIONS, Ports, action, all_events,
    config, edit, git, main_snapshot, make_context, review, settle,
    submit, JournalError, repo, task, url)


def open_app(url, tmp_path, managed):
    return TestClient(create_app(url, tmp_path / 'ui', managed=managed),
                      base_url=LOCAL, headers={'X-My-Harness': '1'})


def login(http):
    assert http.post('/api/session', json={'key': http.app.state.sessions.path.read_text()}).status_code == 200


def get_run(http, run_id):
    response = http.get(f'/api/managed/runs/{run_id}')
    assert response.status_code == 200, response.text
    return response.json()


def commit(http, run_id):
    current = get_run(http, run_id)
    assert current['status'] == 'ACCEPTANCE_READY', current['history'].get('stop')
    response = action(http, run_id, 'commit', current['version'], 'commit-final')
    assert response.status_code == 202, response.text
    result = settle(http, run_id)
    assert result['status'] == 'COMMITTED'
    cycle = result['history']['latest_cycle']
    assert cycle['validation']['evidence']['fingerprint'] == cycle['fingerprint']
    assert cycle['review']['verdict'] == 'ACCEPT'
    assert result['commit']['commit'] == result['commit']['expected_commit']
    return result


def test_session_restart_preserves_action_identity_and_rejects_changed_content(tmp_path, url, repo, task):
    before = main_snapshot(repo)
    base = git(task.root, 'rev-parse', 'HEAD')
    ports = Ports([edit, review()])
    with open_app(url, tmp_path, config(task, ports)) as http:
        assert submit(http, 'start').status_code == 401
        assert ports.roles() == []
        login(http)
        job = submit(http, 'start').json()
        ready = settle(http, job['run_id'])
        events = all_events(http, job['run_id'])
        cookie = dict(http.cookies)
        assert http.delete('/api/session').status_code == 204
        assert action(http, job['run_id'], 'commit', ready['version'], 'commit-stale').status_code == 401
        assert git(task.root, 'rev-parse', 'HEAD') == base
    idle = Ports([review()])
    with open_app(url, tmp_path, config(task, idle)) as http:
        http.cookies.update(cookie)
        assert http.get('/api/managed/projects').status_code == 401
        login(http)
        assert submit(http, 'start').json()['id'] == job['id']
        assert all_events(http, job['run_id']) == events
        assert idle.roles() == []
        task.path('app/main.txt').write_text('external edit after review\n')
        assert action(http, job['run_id'], 'commit', ready['version'], 'commit-stale').status_code == 202
        invalid = settle(http, job['run_id'])
        assert invalid['status'] != 'COMMITTED'
        assert git(task.root, 'rev-parse', 'HEAD') == base
        assert idle.roles() == []
        assert action(http, job['run_id'], 'revalidate', invalid['version'], 'new-evidence').status_code == 202
        ready_again = settle(http, job['run_id'])
        assert ready_again['history']['latest_cycle']['fingerprint'] != ready['history']['latest_cycle']['fingerprint']
        final = commit(http, job['run_id'])
        assert git(task.root, 'show', 'HEAD:app/main.txt') == 'external edit after review'
        assert git(task.root, 'rev-list', '--count', f'{base}..HEAD') == '1'
        assert http.get(f"/api/managed/runs/{job['run_id']}/cycles").json()['items'][0] == ready['history']['latest_cycle']
    assert idle.roles() == ['reviewer']
    assert main_snapshot(repo) == before


def test_quarantine_survives_restart_and_recovery_never_repeats_executor(tmp_path, url, task):
    ports = Ports([edit, JournalError('Injected E2E checkpoint failure')])
    with open_app(url, tmp_path, config(task, ports)) as http:
        login(http)
        job = submit(http).json()
        failed = settle(http, job['run_id'])
        assert failed['status'] == 'RECOVERY_REQUIRED'
        events = all_events(http, job['run_id'])
    restarted = Ports([review()])
    with open_app(url, tmp_path, config(task, restarted)) as http:
        login(http)
        time.sleep(.1)  # permit several supervisor polls, proving restart alone does not retry
        assert get_run(http, job['run_id']) == failed
        assert all_events(http, job['run_id']) == events
        assert restarted.requested == 0
        assert action(http, job['run_id'], 'revalidate', failed['version'], 'early').status_code == 409
        held = http.get(f"/api/managed/jobs/{job['id']}").json()
        body = dict(owner_token=held['owner_token'], expected_version=failed['version'],
                    reason='Synthetic owner stopped; no subprocess was launched')
        path = f"/api/managed/jobs/{job['id']}/confirm-stopped"
        assert http.post(path, json={**body, 'owner_token': 'wrong'}).status_code == 409
        stopped = http.post(path, json=body)
        assert stopped.status_code == 200
        assert restarted.roles() == []
        assert action(http, job['run_id'], 'revalidate', stopped.json()['version'], 'recover').status_code == 202
        settle(http, job['run_id'])
        commit(http, job['run_id'])
        attempts = http.get(f"/api/managed/runs/{job['run_id']}/attempts").json()['items']
        assert [(a['role'], a['status']) for a in attempts] == [
            ('executor', 'COMPLETED'), ('reviewer', 'INTERRUPTED'), ('reviewer', 'COMPLETED')]
        assert len({a['id'] for a in attempts}) == 3
    assert restarted.roles() == ['reviewer']


def test_denial_restart_replacement_and_explicit_retry(tmp_path, url, task):
    task = replace(task, policy=replace(task.policy, max_revision_cycles=3))
    authority = freeze({layer: {'tools': ['Bash(test-runner check)']} for layer in LAYERS})
    versions = {**VERSIONS, 'permission_authority': authority}
    ports = Ports([AgentResult(None, True, 1, error='Synthetic permission stop'), edit, review()])
    def configured():
        return ManagedConfig((ManagedProject('synthetic', task, versions),),
            ports_factory=lambda c, v: ports(c, VERSIONS),
            commit_factory=lambda c, v: ports.writer(c, VERSIONS), supervisor=True, poll_seconds=.02)
    with open_app(url, tmp_path, configured()) as http:
        login(http)
        job = submit(http).json()
        stopped = settle(http, job['run_id'])
        attempts = http.get(f"/api/managed/runs/{job['run_id']}/attempts").json()['items']
        path = f"/api/managed/runs/{job['run_id']}/permissions"
        body = dict(expected_version=stopped['version'], kind='tools', target='Bash(test-runner check)',
                    operation='use', arguments=[], requested_by='synthetic executor', source_attempt_id=attempts[0]['id'],
                    reason='Synthetic exact request', ttl_seconds=3600)
        response = http.post(path, json=body)
        assert response.status_code == 201, response.text
        permission = response.json()
        def decision(http, row, choice):
            return http.post(path + f"/{row['id']}/decision", json=dict(
                expected_version=get_run(http, job['run_id'])['version'], expected_request_version=row['version'],
                fingerprint=row['fingerprint'], decision=choice, scope='once', reason='Explicit E2E decision', confirmed=True))
        assert decision(http, permission, 'deny').status_code == 200
        assert ports.roles() == ['executor']
    with open_app(url, tmp_path, configured()) as http:
        login(http)
        denied = get_run(http, job['run_id'])
        assert action(http, job['run_id'], 'retry_executor', denied['version'], 'denied-retry').status_code == 202
        stopped = settle(http, job['run_id'])
        assert ports.roles() == ['executor']
        assert 'commit' not in stopped['actions']
        response = http.post(path, json={**body, 'expected_version': stopped['version'], 'supersedes': permission['id']})
        assert response.status_code == 201, response.text
        replacement = response.json()
        assert decision(http, permission, 'grant').status_code == 409
        assert decision(http, replacement, 'grant').status_code == 200
        assert ports.roles() == ['executor']
        granted = get_run(http, job['run_id'])
        assert action(http, job['run_id'], 'retry_executor', granted['version'], 'allowed-retry').status_code == 202
        settle(http, job['run_id'])
        commit(http, job['run_id'])
        ledger = http.get(path).json()
        assert [p['status'] for p in ledger] == ['SUPERSEDED', 'CONSUMED']
        assert ledger[1]['consumed_by'] == ports.agents.requests[1].id
    assert ports.roles() == ['executor', 'executor', 'reviewer']


@pytest.mark.parametrize('failure', ['tests', 'review'])
def test_managed_execute_block_revalidate_commit(tmp_path, url, repo, failure):
    root = repo
    (root / '.gitignore').write_text('.harness/runs/\n.harness/managed-mode.json\n')
    git(root, 'add', '.gitignore')
    git(root, 'commit', '-qm', 'Synthetic managed marker exclusion')
    context = make_context(root)
    blocked = {**review(), 'verdict': 'BLOCKED'}
    ports = Ports([edit, review() if failure == 'tests' else blocked, review()],
                  [CommandResult(1, stderr='Synthetic failed assertion')] if failure == 'tests' else [])
    with open_app(url, tmp_path, config(context, ports)) as http:
        login(http)
        job = submit(http).json()
        stopped = settle(http, job['run_id'])
        base = git(root, 'rev-parse', 'HEAD')
        assert stopped['status'] != 'ACCEPTANCE_READY'
        assert action(http, job['run_id'], 'commit', stopped['version'], 'refused-commit').status_code == 409
        assert git(root, 'rev-parse', 'HEAD') == base
        cycle = stopped['history']['latest_cycle']
    with open_app(url, tmp_path, config(context, ports)) as http:
        login(http)
        assert get_run(http, job['run_id'])['history']['latest_cycle'] == cycle
        assert action(http, job['run_id'], 'revalidate', stopped['version'], 'explicit-revalidation').status_code == 202
        settle(http, job['run_id'])
        commit(http, job['run_id'])
        assert http.get('/api/legacy/projects').status_code == 404
    assert ports.roles().count('executor') == 1


def test_create_confirm_restart_then_first_task_and_commit(tmp_path, url):
    """D088: v1 creation is retired; creation goes through the definition conversation, with a restart in between."""
    from test_definition import BRIEF, answer
    root = tmp_path / 'empty'
    root.mkdir()
    context = replace(make_context(root), documents='v2')
    def implement(ctx, request):
        ctx.path('app').mkdir(exist_ok=True)
        ctx.path('app/main.txt').write_text('Synthetic first task implemented.\n')
        return {'result': 'synthetic first task'}
    ports = Ports([answer(), implement, review()])
    managed = replace(config(context, ports), projects=(ManagedProject('synthetic', context, VERSIONS, bootstrap_enabled=True),))
    base = '/api/managed/projects/synthetic'
    with open_app(url, tmp_path, managed) as http:
        login(http)
        assert http.post(base + '/bootstrap/preview', json=DATA).status_code == 404
        created = http.post(base + '/planning', json={'kind': 'definition', 'title': 'Sintético', 'brief': BRIEF},
                            headers={'Idempotency-Key': 'definition'})
        assert created.status_code == 201, created.text
        cid = created.json()['id']
        turn = http.post(base + f'/planning/{cid}/messages', json={'expected_version': 0, 'text': 'Propón'},
                         headers={'Idempotency-Key': 'turn'})
        assert turn.status_code == 202, turn.text
        settle(http, turn.json()['run_id'])
        for proposal in http.get(base + f'/planning/{cid}').json()['proposals']:
            version = http.get(base + f'/planning/{cid}').json()['version']
            applied = http.post(base + f"/planning/{cid}/proposals/{proposal['id']}/apply", json={
                'expected_version': version, 'proposal_sha256': proposal['proposal_sha256'], 'confirmed': True})
            assert applied.status_code == 200, applied.text
        shown = http.post(base + f'/planning/{cid}/accept/preview').json()
        assert shown['ready'], shown['blockers']
        body = {'preview_sha256': shown['preview_sha256'], 'confirmed': True, 'reason': 'Reviewed exact preview',
                'resume_operation_id': None, 'expected_version': None}
        refused = http.post(base + f'/planning/{cid}/accept', json={**body, 'confirmed': False},
                            headers={'Idempotency-Key': 'create'})
        assert refused.status_code == 422 and not (root / '.git').exists()
        accepted = http.post(base + f'/planning/{cid}/accept', json=body, headers={'Idempotency-Key': 'create'})
        assert accepted.status_code == 202, accepted.text
        settle(http, accepted.json()['run_id'])
        operation = http.get(base + '/bootstrap').json()['definition_operation']
        assert operation['status'] == 'COMPLETED'
        assert ports.roles() == ['definition']
    with open_app(url, tmp_path, managed) as http:
        login(http)
        retried = http.post(base + f'/planning/{cid}/accept', json=body, headers={'Idempotency-Key': 'create'})
        assert retried.json()['id'] == accepted.json()['id']
        assert ports.roles() == ['definition']
        response = submit(http, 'first-task', body={**RUN, 'text': shown['task_text']})
        assert response.status_code == 202, response.text
        settle(http, response.json()['run_id'])
        final = commit(http, response.json()['run_id'])
        assert final['history']['acceptance']['changed_paths'] == ['app/main.txt']
        assert git(root, 'rev-list', '--count', 'HEAD') == '2'
        assert {'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', 'docs/DDBB-DIAGRAM.md'} <= set(git(root, 'ls-files').splitlines())
        assert http.get('/api/managed/phases/' + operation['phase_id']).json()['status'] == 'ACTIVE'
