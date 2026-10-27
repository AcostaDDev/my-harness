"""T010: later revisions, original receipts and synthetic assistance only."""
import copy
import json
import shutil

import pytest
from sqlalchemy.orm import Session

from session_client import TestClient
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.services.configuration_assistance import ConfigurationAssistance
from my_harness.storage.models import ConfigurationOperationRow as Operation
from test_configuration import setup, active_global
from test_configuration_api import app_for, store, request_for
from test_project_configuration import journey, documents, save_profile, prepare, activation, BASE
from test_project_onboarding import git

GLOBAL = '/api/managed/configuration'
ASSIST = GLOBAL + '/assistance'


def activated(journey):
    http, runtime, *_ = journey
    documents(journey); save_profile(journey); prepare(journey)
    body = later_activation(http)
    assert http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'active'}).status_code == 200
    return http, runtime


def later_activation(http):
    state = http.get(BASE + '/configuration').json()
    body = {'revision': state['saved']['revision'], 'sha256': state['saved']['sha256'],
            'expected_version': state['version'], 'reason': 'Review later activation'}
    shown = http.post(BASE + '/configuration/activation/preview', json=body)
    assert shown.status_code == 200, shown.text
    return {**body, 'preview_sha256': shown.json()['sha256']}


def save_edit(http, form, key='edit'):
    state = http.get(BASE + '/configuration').json()
    body = request_for(state, form)
    shown = http.post(BASE + '/configuration/preview', json=body)
    assert shown.status_code == 200, shown.text
    saved = http.post(BASE + '/configuration/save', json={**body, 'preview_sha256': shown.json()['sha256']},
                      headers={'Idempotency-Key': key})
    assert saved.status_code == 200, saved.text
    return shown.json(), saved.json()


def prepare_later(journey):
    http, runtime, *_ = journey
    state = http.get(BASE + '/configuration').json()
    prep = {'contract': 'project-profile-preparation-1', 'expected_version': 1, 'mode': 'offline',
        'configuration_revision': state['saved']['revision'], 'configuration_sha256': state['saved']['sha256'],
        'proposal_id': state['proposal_id'], 'proposal_sha256': state['proposal_sha256']}
    shown = http.post(BASE + '/preparation/preview', json=prep)
    assert shown.status_code == 200, shown.text
    confirmed = http.post(BASE + '/preparation/confirm', json={'change': prep,
        'preview_sha256': shown.json()['preview_sha256'], 'confirmed': True, 'reason': 'Reviewed later preparation'},
        headers={'Idempotency-Key': 'later-prepare'})
    assert confirmed.status_code == 200, confirmed.text
    runtime.preparation.run_once()
    operation = runtime.preparation.repository.read(confirmed.json()['id'])
    assert operation['status'] == 'COMPLETED', operation['diagnostic']
    return operation


def test_later_agent_change_reuses_original_receipt_without_restart(journey):
    http, runtime = activated(journey)
    original = copy.deepcopy(runtime.project_configuration.active_receipt('own', runtime.setup.repository.read('project:own')['active']))
    state = http.get(BASE + '/configuration').json()
    form = state['form']; form['agents']['reviewer']['model'] = 'later-reviewer'
    shown, _ = save_edit(http, form)
    assert not shown['effects']['projects'][0]['preparation_required']
    body = later_activation(http)
    result = http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'later-active'})
    assert result.status_code == 200, result.text
    assert runtime.project('own').context.policy.reviewer_model == 'later-reviewer'
    assert runtime.setup.state()['mode'] == 'READY'
    assert runtime.project_configuration.active_receipt('own', runtime.setup.repository.read('project:own')['active']) == original
    assert len(journey[6].calls) == 1


def test_technical_edit_requires_new_preparation_and_retains_prior_evidence(journey):
    http, runtime = activated(journey)
    root = journey[2].context.root
    # The prior documentary acceptance and receipt remain frozen. A separately committed update precedes
    # a profile change; editing the old accepted proposal is never used as a shortcut.
    doc = root / 'docs/ARCHITECTURE.md'
    doc.write_text(doc.read_text() + '\nPreserve the documented CLI when preparing later revisions.\n')
    git(root, 'add', 'docs/ARCHITECTURE.md'); git(root, 'commit', '-qm', 'Document later profile requirements')
    response = http.post(BASE + '/configuration/edit-base', json={})
    assert response.status_code == 200, response.text
    form = response.json()['form']
    form['profile']['executor_instructions'] += ' Preserve the documented CLI.'
    _, saved = save_edit(http, form)
    state = http.get(BASE + '/configuration').json()
    body = {'revision': state['saved']['revision'], 'sha256': state['saved']['sha256'],
            'expected_version': state['version'], 'reason': 'Review later technical revision'}
    assert http.post(BASE + '/configuration/activation/preview', json=body).status_code == 409
    operation = prepare_later(journey)
    assert operation['receipt']['configuration']['revision'] == 2
    body = later_activation(http)
    assert http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'technical-active'}).status_code == 200
    assert len(journey[6].calls) == 2


def test_global_edit_derives_private_references_and_promotes_whole_set(journey):
    http, runtime = activated(journey)
    before = http.get(BASE + '/configuration').json()
    global_state = http.get(GLOBAL).json()
    form = global_state['form']; form['git']['author_name'] = 'Later synthetic author'
    store(http, form, key='global-later')
    state = http.get(GLOBAL).json()
    assert {r['scope'] for r in state['activation_references']} == {'global', 'project:own'}
    derived = http.get(BASE + '/configuration').json()
    assert derived['active'] == before['active'] and derived['saved']['revision'] == 2
    assert derived['form']['profile'] == before['form']['profile']
    body = {'references': state['activation_references'], 'reason': 'Review global and private derived reference'}
    shown = http.post(GLOBAL + '/activation/preview', json=body)
    assert shown.status_code == 200, shown.text
    result = http.post(GLOBAL + '/activate', json={**body, 'preview_sha256': shown.json()['sha256']},
        headers={'Idempotency-Key': 'global-later-active'})
    assert result.status_code == 200, result.text
    assert runtime.setup.state()['mode'] == 'RESTART_REQUIRED'
    with TestClient(app_for(journey[7])) as restarted:
        assert restarted.get(GLOBAL).json()['mode'] == 'READY'
        assert restarted.get(BASE + '/configuration').json()['active']['revision'] == 2
        assert restarted.get(BASE).json()['configuration_state'] == 'ACTIVE'


class FakeAssistance:
    def __init__(self):
        self.calls = []
        self.effect = None
        self.data = []
    def frozen_versions(self):
        return {'agent_adapter': 'synthetic-assistance', 'cli_config_sha256': 'a' * 64}
    def close(self):
        pass
    def bind_preparation(self, journal, versions):
        self.journal = journal
    def invoke(self, context, request):
        self.calls.append((context, request))
        assert request.selection.model == self.data[-1]['agents']['reviewer']['model'] or request.role == 'executor'
        if self.effect:
            self.effect(context, request)
        candidate = json.loads(request.prompt.split('\n', 1)[1])['candidate']
        return AgentResult(freeze({'text': candidate, 'rationale': 'Synthetic reasoned proposal', 'questions': []}
            if request.role == 'configuration' else {'result': 'Inspected only in private scratch'}), True, 0)


@pytest.fixture
def assistance(setup, monkeypatch):
    repo, data, _ = setup
    data['git']['executable'] = shutil.which('git')
    active_global(repo, data)
    fake = FakeAssistance()
    def adapter(self, active):
        fake.data.append(copy.deepcopy(active))
        return fake
    monkeypatch.setattr(ConfigurationAssistance, 'adapter', adapter)
    with TestClient(app_for(repo)) as http:
        http.headers['X-My-Harness'] = '1'
        yield http, fake, repo


def assistance_body(http, role='reviewer'):
    state = http.get(GLOBAL).json()
    candidate = copy.deepcopy(state['form'])
    candidate['agents']['reviewer']['model'] = 'untrusted-candidate-client'
    return {'scope': 'global', 'candidate': {'form': candidate, 'validated': True}, 'expected_version': state['version'],
        'active_sha256': state['active']['sha256'], 'base_sha256': state['working_sha256'],
        'message': 'Explain a suitable later configuration', 'role': role, 'documents': [],
        **({'selection': {'model': 'synthetic-executor', 'effort': 'medium'}} if role == 'executor' else {})}


def confirm_assistance(http, body, key='assist'):
    shown = http.post(ASSIST + '/preview', json=body)
    assert shown.status_code == 200, shown.text
    confirmed = {**body, 'preview_sha256': shown.json()['sha256'], 'confirmed': True}
    result = http.post(ASSIST + '/confirm', json=confirmed, headers={'Idempotency-Key': key})
    assert result.status_code == 200, result.text
    return confirmed, result.json()


@pytest.mark.parametrize('role', ['reviewer', 'executor'])
def test_assistance_freezes_active_pair_scratch_scope_and_exact_replay(assistance, role):
    http, fake, repo = assistance
    before = repo.read()
    body = assistance_body(http, role)
    assert not fake.calls
    confirmed, result = confirm_assistance(http, body)
    assert len(fake.calls) == 1 and result['status'] == 'APPLIED'
    assert repo.read() == before
    context, request = fake.calls[0]
    assert context.root.is_relative_to(repo.state_dir) and not context.root.is_relative_to(repo.directory)
    assert all(data['agents']['reviewer']['model'] == 'synthetic' for data in fake.data)
    assert result['result']['authority_changed'] is False
    assert http.post(ASSIST + '/confirm', json=confirmed, headers={'Idempotency-Key': 'assist'}).json() == result
    assert len(fake.calls) == 1
    assert http.post(ASSIST + '/confirm', json={**confirmed, 'message': 'Different'},
        headers={'Idempotency-Key': 'assist'}).status_code == 409


def test_assistance_stale_confirmation_no_calls_and_explicit_recovery(assistance):
    http, fake, repo = assistance
    body = assistance_body(http)
    shown = http.post(ASSIST + '/preview', json=body).json()
    assert http.post(ASSIST + '/confirm', json={**body, 'preview_sha256': 'b' * 64, 'confirmed': True},
        headers={'Idempotency-Key': 'stale'}).status_code == 409
    assert not fake.calls
    def uncertain(context, request):
        fake.journal.process_intent(request.id, {'adapter_version': 'cli-14'})
        raise RuntimeError('Simulated crash before process identity')
    fake.effect = uncertain
    confirmed, result = confirm_assistance(http, body)
    assert result['status'] == 'RECOVERY_REQUIRED'
    observed = http.get(GLOBAL + '/operations/' + result['id']).json()['result']['journal']
    assert observed['owner_closed'] and observed['process']['status'] == 'PENDING'
    assert http.post(ASSIST + '/' + result['id'] + '/recover', json={'writers_stopped': False}).status_code == 409
    recovered = http.post(ASSIST + '/' + result['id'] + '/recover', json={'writers_stopped': True})
    assert recovered.status_code == 200 and recovered.json()['result']['recovered_without_retry']
    assert len(fake.calls) == 1
    assert repo.read()['status'] == 'READY'


def test_assistance_rejects_unknown_context_and_security_boundaries(assistance):
    http, fake, _ = assistance
    body = assistance_body(http)
    assert http.post(ASSIST + '/preview', json={**body, 'documents': ['../outside']}).status_code == 422
    assert http.post(ASSIST + '/preview', json={**body, 'role': 'shell'}).status_code == 422
    assert http.post(ASSIST + '/preview', json=body, headers={'Origin': 'https://foreign.invalid'}).status_code == 403
    del http.headers['X-My-Harness']
    assert http.post(ASSIST + '/preview', json=body).status_code == 403
    assert not fake.calls


def test_agent_revision_with_pending_job_keeps_frozen_versions_and_refuses_activation(journey):
    http, runtime = activated(journey)
    admitted = http.post(BASE + '/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': 'Synthetic task'},
        headers={'Idempotency-Key': 'frozen-task'})
    assert admitted.status_code == 202, admitted.text
    before = runtime.repository.get_run(admitted.json()['run_id'])
    state = http.get(BASE + '/configuration').json()
    form = state['form']; form['agents']['reviewer']['model'] = 'next-reviewer'
    shown, _ = save_edit(http, form)
    assert shown['effects']['jobs'] and shown['effects']['admitted_jobs_keep_frozen_configuration']
    state = http.get(BASE + '/configuration').json()
    response = http.post(BASE + '/configuration/activation/preview', json={
        'revision': state['saved']['revision'], 'sha256': state['saved']['sha256'],
        'expected_version': state['version'], 'reason': 'Review later activation'})
    assert response.status_code == 409, response.text
    after = runtime.repository.get_run(admitted.json()['run_id'])
    assert after.versions_json == before.versions_json and after.history == before.history
    assert runtime.project('own').context.policy.reviewer_model != 'next-reviewer'


def test_global_cancel_preserves_all_authorities_and_allows_revising_derived_draft(journey):
    http, runtime = activated(journey)
    before = http.get(BASE + '/configuration').json()['active']
    form = http.get(GLOBAL).json()['form']; form['git']['author_name'] = 'Candidate one'
    store(http, form, key='global-one')
    form['git']['author_name'] = 'Candidate two'
    store(http, form, key='global-two')
    state = http.get(GLOBAL).json()
    body = {'references': state['activation_references'], 'reason': 'Review complete activation'}
    shown = http.post(GLOBAL + '/activation/preview', json=body)
    assert shown.status_code == 200, shown.text
    scheduled = http.post(GLOBAL + '/activate', json={**body, 'preview_sha256': shown.json()['sha256']},
        headers={'Idempotency-Key': 'schedule-global'})
    assert scheduled.status_code == 200, scheduled.text
    draft = request_for(http.get(GLOBAL).json(), form)
    draft['validated'] = False
    shown = http.post(GLOBAL + '/preview', json=draft)
    assert shown.status_code == 200, shown.text
    saved = http.post(GLOBAL + '/save', json={**draft, 'preview_sha256': shown.json()['sha256']},
        headers={'Idempotency-Key': 'global-draft-while-pending'})
    assert saved.status_code == 200, saved.text
    state = http.get(GLOBAL).json()
    body = {'activation_id': scheduled.json()['id'], 'expected_version': state['version'],
        'expected_versions': state['pending_versions'],
        'reason': 'Cancel entire pending set'}
    cancelled = http.post(GLOBAL + '/cancel', json=body, headers={'Idempotency-Key': 'cancel-global'})
    assert cancelled.status_code == 200, cancelled.text
    assert runtime.setup.state()['mode'] == 'READY'
    assert http.get(BASE + '/configuration').json()['active'] == before
    assert http.get(BASE + '/configuration').json()['pending'] is None
    form['git']['author_name'] = 'Candidate three'
    store(http, form, key='global-three')


def test_live_assistance_keeps_owned_jobs_usable_and_uses_project_policy(journey, monkeypatch):
    http, runtime = activated(journey)
    admitted = http.post(BASE + '/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': 'Frozen task'},
        headers={'Idempotency-Key': 'running-task'})
    assert admitted.status_code == 202, admitted.text
    claim = runtime.repository.claim(lease_seconds=30)
    fake = FakeAssistance()
    def adapter(self, data):
        fake.data.append(data)
        return fake
    monkeypatch.setattr(ConfigurationAssistance, 'adapter', adapter)
    def while_running(context, request):
        with runtime.repository._write() as session:
            runtime.repository._owned(session, claim)
    fake.effect = while_running
    state = http.get(BASE + '/configuration').json()
    body = {'scope': 'project:own', 'candidate': {'form': state['form']}, 'expected_version': state['version'],
        'base_sha256': state['working_sha256'], 'active_sha256': state['active']['sha256'],
        'role': 'reviewer', 'message': 'Explain the own profile', 'documents': ['docs/ARCHITECTURE.md']}
    _, result = confirm_assistance(http, body)
    assert result['status'] == 'APPLIED' and not result['result'].get('failure_type'), result
    assert len(fake.calls) == 1
    assert result['result']['preview']['documents'][0]['path'] == 'docs/ARCHITECTURE.md'


def test_profile_change_without_documentary_update_is_rejected(journey):
    http, runtime = activated(journey)
    result = http.post(BASE + '/configuration/edit-base', json={})
    assert result.status_code == 200, result.text
    form = result.json()['form']; form['profile']['executor_instructions'] += ' Undocumented change.'
    rejected = http.post(BASE + '/configuration/form', json={'form': form})
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'profile_documentary_update_required'


@pytest.mark.parametrize('provider', ['codex', 'claude'])
@pytest.mark.parametrize('role', ['reviewer', 'executor'])
def test_assistance_native_transport_journals_synthetic_process_before_go(setup, tmp_path, provider, role):
    from dataclasses import asdict
    from test_cli_agents import adapter
    repo, data, _ = setup
    port = adapter(tmp_path)
    config = next(value for value in port.agents.values() if value.provider == provider)
    fields = asdict(config)
    fields['environment'] = {**data['agents']['reviewer']['environment'], **dict(config.environment)}
    fields['timeout_seconds'] = 10
    fields['executable'] = list(config.executable)
    fields = {key: fields[key] for key in ('provider', 'executable', 'cli_version', 'environment', 'timeout_seconds')}
    data['agents'] = {'reviewer': {**fields, 'model': 'synthetic-reviewer', 'effort': 'medium'}, 'executor': fields}
    data['git']['executable'] = shutil.which('git')
    active_global(repo, data)
    with TestClient(app_for(repo)) as http:
        http.headers['X-My-Harness'] = '1'
        body = assistance_body(http, role)
        confirmed, result = confirm_assistance(http, body)
        assert result['status'] == 'APPLIED', result
        with Session(repo.managed.engine) as session:
            row = session.get(Operation, result['id'])
            process = row.payload['process']
            assert process['identity'] and process['status'] == 'STOPPED'
            assert process['capture']['group_state'] == 'dead'
            assert process['spec']['agent'] == role
            assert row.payload['snapshot']['output_schema']['type'] == 'object'
        launches = [json.loads(line) for line in (tmp_path / 'launches.jsonl').read_text().splitlines()]
        assert len(launches) == 1
        args = launches[0]['argv']
        if provider == 'codex':
            assert args[args.index('--sandbox') + 1] == ('read-only' if role == 'reviewer' else 'workspace-write')
            assert ('--skip-git-repo-check' in args) == (role == 'reviewer')
        else:
            assert ('--restricted' in args) == (role == 'reviewer')
            assert ('--json-schema' in args) == (role == 'reviewer')
        if role == 'executor':
            assert result['result']['proposal'] == {'result': 'ñ'}
        else:
            # The old generic fixture returns an executor-shaped response. It cannot become a proposal.
            assert result['result']['proposal'] == {'diagnostic': 'configuration_assistance_failed'}
        assert http.post(ASSIST + '/confirm', json=confirmed, headers={'Idempotency-Key': 'assist'}).json() == result
        assert len((tmp_path / 'launches.jsonl').read_text().splitlines()) == 1


def test_plan_edit_requires_new_evidence_and_does_not_replace_active_receipt(journey):
    http, runtime = activated(journey)
    active_ref = runtime.setup.repository.read('project:own')['active']
    original = copy.deepcopy(runtime.project_configuration.active_receipt('own', active_ref))
    response = http.post(BASE + '/configuration/edit-base', json={})
    assert response.status_code == 200, response.text
    form = response.json()['form']
    form['edit']['preparation_plan']['instructions'] += ' Recheck the existing source scope.'
    shown, _ = save_edit(http, form)
    assert shown['effects']['projects'][0]['preparation_required']
    state = http.get(BASE + '/configuration').json()
    body = {'revision': state['saved']['revision'], 'sha256': state['saved']['sha256'],
            'expected_version': state['version'], 'reason': 'Review plan-only change'}
    assert http.post(BASE + '/configuration/activation/preview', json=body).status_code == 409
    operation = prepare_later(journey)
    assert operation['receipt']['operation_id'] != original['operation_id']
    assert runtime.project_configuration.active_receipt('own', active_ref) == original
    body = later_activation(http)
    result = http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'plan-active'})
    assert result.status_code == 200, result.text
    current = runtime.setup.repository.read('project:own')['active']
    assert runtime.project_configuration.active_receipt('own', current) == operation['receipt']


def test_reverting_a_saved_plan_uses_active_evidence_instead_of_latest_preparation(journey):
    http, runtime = activated(journey)
    response = http.post(BASE + '/configuration/edit-base', json={})
    assert response.status_code == 200, response.text
    original = response.json()['form']
    changed = copy.deepcopy(original)
    changed['edit']['preparation_plan']['instructions'] += ' Recheck exact inputs.'
    save_edit(http, changed)
    later = prepare_later(journey)
    assert later['receipt']['configuration']['revision'] == 2
    save_edit(http, original, key='revert-local-plan')
    assert runtime.preparation.read('own')['prepared'] is True
    state = http.get(BASE + '/configuration').json()
    assert state['active']['revision'] == 1 and state['saved']['revision'] == 3
    assert state['configuration_state'] == 'ACTIVE' and state['candidate_state'] == 'READY_TO_ACTIVATE'
    assert http.get(BASE).json()['configuration_state'] == 'ACTIVE'
