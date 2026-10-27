"""D218 synthetic generic preparation. T009 documentary/configuration handoff is seeded explicitly.

Real temporary Git/SQLite and native command transport; fake Go executable and executor, no providers/network.
"""
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import pwd
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from my_harness.adapters.preparation import verify_receipt
from my_harness.core.engine.context import IntakeContext
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.core.engine.definition import text_hash
from my_harness.core.engine.journal import JournalError
from my_harness.services.configuration_setup import toml_document
from my_harness.services.profile_preparation import CONTRACT, ProfilePreparation, validate_plan
from my_harness.services.profile_proposal import validate
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.configuration import ConfigurationRepository
from my_harness.storage.models import (
    PlanningConversationRow as Conversation, PlanningTurnRow as Turn, PlanningProposalRow as Proposal,
    ProjectBootstrapRow as Bootstrap, ProjectPreparationOperationRow as Operation,
    ProjectPreparationStepRow as Step, ManagedProcessRow as Process, CheckoutLockRow as Lock,
)
from test_project_preparation import preparation, operator, setup, web  # noqa: F401
from test_configuration import change, save, active_global, project_data
from test_profile_proposals import candidate, DOCS
from test_managed_api import git


def technical():
    return {'write_paths': ['app/main.go', 'go.mod', '.prepare/**'], 'local_paths': ['.prepare/**'], 'environment_paths': [],
            'dependencies': [], 'network': [], 'scripts': False,
            'executor_selection': {'model': 'synthetic-executor', 'effort': 'medium', 'reason': 'Small preparation'},
            'instructions': 'Write the synthetic Go calculator and module manifest only.'}


class Executor:
    def __init__(self):
        self.calls = []
        self.effect = lambda root: ((root / 'app').mkdir(exist_ok=True),
            (root / 'app/main.go').write_text('package main\nfunc main() {}\n'),
            (root / 'go.mod').write_text('module example.invalid/synthetic\n\ngo 1.25\n'))
        self.versions = {'agent_adapter': 'synthetic-preparation', 'cli_config_sha256': 'a' * 64}

    def frozen_versions(self):
        return self.versions

    def bind_preparation(self, journal, versions):
        assert self.versions == versions
        self.journal = journal

    def invoke(self, context, request):
        self.calls.append(request)
        self.effect(context.root)
        return AgentResult(freeze({'result': 'Prepared synthetic Go files'}), True, 0)

    def close(self):
        pass


@pytest.fixture
def generic(preparation, monkeypatch):
    service, _, _, folder = preparation
    runtime, root = service.runtime, service.runtime.project('child').context.root
    # This fixture models the handoff T009 will implement; it does not claim a completed intake/UI journey.
    old = runtime.project('child')
    context = IntakeContext(root, old.context.policy, work_language='en')
    runtime.install(replace(old, context=context, versions={**old.versions, 'project_recipe': None}))
    executor = Executor()
    monkeypatch.setattr(ProfilePreparation, '_agent', lambda self, project: executor)
    private = folder / 'configuration'
    private.mkdir(mode=0o700)
    repo = ConfigurationRepository(service.managed, private, state_dir=runtime.registry.registrar.state)
    user = pwd.getpwuid(os.getuid()).pw_name
    agents = {'reviewer': {'provider': 'codex', 'model': 'synthetic-reviewer', 'effort': 'high',
                          'timeout_seconds': 10, 'environment': {'USER': user}},
              'executor': {'provider': 'codex', 'timeout_seconds': 10, 'environment': {'USER': user}}}
    global_data = {'format': 'local-config-9', 'service': {'state_dir': str(runtime.registry.registrar.state), 'supervisor': False},
                   'git': {'executable': sys.executable, 'author_name': 'Synthetic', 'author_email': 'test@example.invalid'},
                   'agents': agents, 'registration': {'roots': [], 'bootstrap_enabled': False}}
    active_global(repo, global_data)
    data = project_data(global_data, repo, root, 'child')
    data['profile_name'] = 'own-go'
    data['profile'] = candidate()['profile']
    data['profile']['validations'][0]['junit'] = {'path': '.prepare/test.xml', 'coverage': 'Synthetic Go tests'}
    data['commands']['environment'] = {'HOME': str(root / '.prepare/home'), 'TMPDIR': str(root / '.prepare/tmp')}
    tool = folder / 'synthetic-go'
    tool.write_text('#!' + sys.executable + '''
from pathlib import Path
import os, sys
root = Path.cwd()
(root/'.prepare/calls').open('a').write(' '.join(sys.argv[1:])+'\\n')
if (root/'.prepare/fail').exists(): raise SystemExit(1)
(root/'.prepare/test.xml').write_text('<testsuite><testcase classname="synthetic" name="go-test"/></testsuite>')
assert os.environ['HOME'] == str(root/'.prepare/home')
assert os.environ['TMPDIR'] == str(root/'.prepare/tmp')
''')
    tool.chmod(0o700)
    data['commands']['executables'] = {'go': str(tool)}
    save(repo, [change(repo, toml_document(data), 'project:child')], key='project-save')
    runtime.setup = SimpleNamespace(repository=repo, legacy=False)
    # The original documentary bootstrap remains synthetic. Seal its exact resulting commit/documents and accepted profile.
    # Add a private-area ignore rule to the fixture's already documentary commit before freezing its final hashes.
    (root / '.gitignore').write_text('.prepare/\n')
    git(root, 'add', '.gitignore')
    git(root, 'commit', '-m', 'Synthetic documentary ignore policy')
    with service.managed._write() as session:
        doc = session.scalar(select(Bootstrap).where(Bootstrap.root == str(root)))
        conversation = session.scalar(select(Conversation).where(Conversation.root == str(root)))
        turn = session.scalar(select(Turn).where(Turn.conversation_id == conversation.id))
        p = candidate()
        p['profile'] = copy.deepcopy(data['profile'])
        p['preparation_plan'] = technical()
        content = freeze({'contract': 'project-profile-proposal-1', 'candidate': p, 'binding': {'documents': {}}})
        proposal = Proposal(id=str(uuid4()), conversation_id=conversation.id, turn_id=turn.id,
            number=100, kind='profile', content=content, reason='Synthetic accepted reviewer plan',
            content_sha256=text_hash(content), proposal_sha256='b' * 64, status='ACCEPTED', version=1,
            decision={'decision': 'profile_draft_adopted'}, created_at=service.managed._now())
        session.add(proposal)
        doc.preview = {**doc.preview, 'profile_proposal_sha256': proposal.proposal_sha256}
        doc.result = {**doc.result, 'commit': git(root, 'rev-parse', 'HEAD'),
                      'documents': {**doc.result['documents'], '.gitignore': text_hash((root / '.gitignore').read_text())}}
        proposal_id = proposal.id
    ref = repo.read('project:child')['saved']
    body = {'contract': CONTRACT, 'expected_version': 1, 'mode': 'offline',
            'configuration_revision': ref['revision'], 'configuration_sha256': ref['sha256'],
            'proposal_id': proposal_id, 'proposal_sha256': 'b' * 64}
    yield service, body, executor, repo, data, tool
    runtime.setup = None


def confirm(fixture, key='prepare', **extra):
    service, body, *_ = fixture
    body = {**body, **extra}
    plan = service.preview('child', body)
    return service.confirm('child', {'change': body, 'preview_sha256': plan['preview_sha256'],
                                    'confirmed': True, 'reason': 'Reviewed exact preparation'}, key)


def finish(fixture):
    service, *_ = fixture
    op = confirm(fixture)
    assert service.run_once() == op['id']
    result = service.repository.read(op['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    return result


def test_generic_preview_is_passive_exact_confirmation_and_receipt(generic):
    service, body, executor, repo, data, _ = generic
    root = service.runtime.project('child').context.root
    before = git(root, 'rev-parse', 'HEAD')
    shown = service.preview('child', body)
    assert shown['contract'] == CONTRACT and shown['recipe'] is None
    assert shown['technical']['network'] == [] and shown['steps'][2]['command']['argv'] == ('go', 'test', './...')
    assert not executor.calls and not (root / '.prepare').exists()
    result = finish(generic)
    receipt = result['receipt']
    assert receipt['commit'] != before and git(root, 'rev-parse', 'HEAD') == receipt['commit']
    assert receipt['configuration']['sha256'] == body['configuration_sha256']
    assert receipt['protected_files']['go.mod']
    assert receipt['results'][2]['evidence']['junit']['status'] == 'complete'
    verify_receipt(root, receipt)
    assert len(executor.calls) == 1 and service.run_once() is None
    assert 'configuration_data' not in executor.calls[0].prompt and 'initial_workspace' not in executor.calls[0].prompt
    assert repo.read('project:child')['active'] is None  # Preparation does not activate.
    with Session(service.runtime.engine) as session:
        assert session.get(Lock, str(root)) is None
        process = session.scalar(select(Process).where(Process.preparation_id == result['id']))
        assert process.capture['group_state'] == 'dead'
    # Ordinary code commits preserve evidence; protected files/environment mutations do not.
    (root / 'app/main.go').write_text('package main\nfunc main() { /* next task */ }\n')
    git(root, 'add', 'app/main.go'); git(root, 'commit', '-m', 'Synthetic ordinary task')
    verify_receipt(root, receipt)
    (root / 'go.sum').write_text('new protected file')
    with pytest.raises(JournalError): verify_receipt(root, receipt)


def test_confirmation_replay_conflict_cancel_and_retry_without_effects(generic):
    service, body, executor, *_ = generic
    plan = service.preview('child', body)
    request = {'change': body, 'preview_sha256': plan['preview_sha256'], 'confirmed': True, 'reason': 'Exact'}
    first = service.confirm('child', request, 'same')
    assert service.confirm('child', request, 'same') == first
    with pytest.raises(RegistryError): service.confirm('child', {**request, 'reason': 'other'}, 'same')
    with pytest.raises(RegistryError): service.confirm('child', {**request, 'confirmed': False}, 'different')
    service.control(first['id'], {'expected_version': first['version'], 'plan_sha256': first['plan_sha256']}, 'cancel')
    assert service.run_once() is None and not executor.calls
    successor = confirm(generic, key='successor', previous_id=first['id'], retry_step=0)
    service.run_once()
    assert service.repository.read(successor['id'])['status'] == 'COMPLETED'


@pytest.mark.parametrize('fault', ['network', 'configuration', 'documents', 'tools', 'scope', 'step', 'git-config', 'git-ref'])
def test_changed_authority_blocks_before_executor_or_native_process(generic, fault):
    service, body, executor, repo, data, tool = generic
    if fault == 'network':
        with pytest.raises(RegistryError): service.preview('child', {**body, 'mode': 'network'})
        return
    op = confirm(generic)
    if fault == 'configuration':
        Path(repo.directory / 'projects/child/project.toml').write_text('external change')
    elif fault == 'documents':
        root = service.runtime.project('child').context.root
        (root / 'docs/ARCHITECTURE.md').write_text('foreign documentation')
    elif fault == 'tools': tool.write_text(tool.read_text()+'\n# changed tool\n')
    elif fault == 'scope':
        root = service.runtime.project('child').context.root
        (root / 'foreign.txt').write_text('foreign bytes')
    elif fault == 'git-config':
        git(service.runtime.project('child').context.root, 'config', 'synthetic.foreign', 'changed')
    elif fault == 'git-ref':
        git(service.runtime.project('child').context.root, 'tag', 'foreign-tag')
    else:
        with service.managed._write() as session:
            step = session.scalar(select(Step).where(Step.operation_id == op['id'], Step.number == 1))
            step.spec = {**step.spec, 'write_paths': ['**']}
    service.run_once()
    result = service.repository.read(op['id'])
    assert result['status'] == 'FAILED' and result['receipt'] is None
    assert not executor.calls
    with Session(service.runtime.engine) as session:
        assert not session.scalar(select(Process.id).where(Process.preparation_id == op['id']))


def test_executor_scope_violation_preserves_bytes_without_receipt_or_commit(generic):
    service, _, executor, *_ = generic
    root = service.runtime.project('child').context.root
    initial = git(root, 'rev-parse', 'HEAD')
    executor.effect = lambda root: (root / 'foreign.txt').write_text('outside confirmed plan')
    op = confirm(generic)
    service.run_once()
    failed = service.repository.read(op['id'])
    assert failed['status'] == 'FAILED' and failed['receipt'] is None
    assert (root / 'foreign.txt').read_text() == 'outside confirmed plan'
    assert git(root, 'rev-parse', 'HEAD') == initial
    with pytest.raises(RegistryError):
        service.preview('child', {**generic[1], 'previous_id': op['id'], 'retry_step': 1})


def test_failed_step_recovery_reuses_only_accredited_prefix(generic, monkeypatch):
    service, _, executor, *_ = generic
    original = ProfilePreparation._execute_step
    failed_once = []
    def fail(self, operation_id, token, project, plan, step):
        if step['spec']['kind'] == 'command' and not failed_once:
            failed_once.append(True)
            raise ValueError('Synthetic failure before effects')
        return original(self, operation_id, token, project, plan, step)
    monkeypatch.setattr(ProfilePreparation, '_execute_step', fail)
    op = confirm(generic)
    service.run_once()
    assert service.repository.read(op['id'])['status'] == 'FAILED'
    successor = confirm(generic, key='linked', previous_id=op['id'], retry_step=2)
    service.run_once()
    result = service.repository.read(successor['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    assert len(executor.calls) == 1


def test_lost_technical_commit_adoption_reconciles_without_replaying_commands(generic, monkeypatch):
    service, *_ = generic
    original = ProfilePreparation._commit
    def crash(self, *args):
        original(self, *args)
        raise ValueError('Synthetic crash after Git commit before checkpoint')
    monkeypatch.setattr(ProfilePreparation, '_commit', crash)
    op = confirm(generic)
    service.run_once()
    root = service.runtime.project('child').context.root
    head = git(root, 'rev-parse', 'HEAD')
    calls = (root / '.prepare/calls').read_text()
    monkeypatch.setattr(ProfilePreparation, '_commit', original)
    successor = confirm(generic, key='reconcile', previous_id=op['id'], retry_step=3)
    service.run_once()
    result = service.repository.read(successor['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    assert git(root, 'rev-parse', 'HEAD') == head and (root / '.prepare/calls').read_text() == calls


@pytest.mark.parametrize('fault', ['document-scope', 'git-scope', 'wide-scope', 'external-path',
                                   'environment-scope', 'dependency-hash', 'network-url', 'selection'])
def test_reviewer_plan_cannot_grant_documentary_global_or_unbounded_authority(generic, fault):
    service, _, _, _, data, _ = generic
    context = service.runtime.project('child').context
    from my_harness.services.local_config import _profile
    profile = _profile(data['profile_name'], data['profile'], allow_formatter=True)
    plan = technical()
    if fault == 'document-scope': plan['write_paths'].append('docs/**')
    elif fault == 'git-scope': plan['write_paths'].append('.git/config')
    elif fault == 'wide-scope': plan['write_paths'].append('**')
    elif fault == 'external-path': plan['write_paths'].append('/tmp/global.toml')
    elif fault == 'environment-scope': plan['environment_paths'] = ['foreign/**']
    elif fault == 'dependency-hash':
        plan['dependencies'] = [{'name': 'synthetic', 'version': '1', 'lock_path': 'go.sum', 'sha256': 'unpinned'}]
    elif fault == 'network-url': plan['network'] = ['https://user:password@example.invalid/packages']
    else: plan['executor_selection']['model'] = 'unapproved'
    with pytest.raises((RegistryError, ValueError)): validate_plan(plan, profile, context)


def test_command_failure_never_accredits_or_commits_partial_effects(generic):
    service, _, executor, *_ = generic
    root = service.runtime.project('child').context.root
    before = git(root, 'rev-parse', 'HEAD')
    original = executor.effect
    executor.effect = lambda root: (original(root), (root / '.prepare/fail').write_text('fail command'))
    op = confirm(generic)
    service.run_once()
    result = service.repository.read(op['id'])
    assert result['status'] == 'FAILED' and result['receipt'] is None
    assert git(root, 'rev-parse', 'HEAD') == before
    assert result['steps'][1]['status'] == 'DONE' and result['steps'][2]['status'] == 'STARTED'
    with pytest.raises(RegistryError):
        confirm(generic, key='cannot-adopt-partial-effects', previous_id=op['id'], retry_step=2)


def test_receipt_binding_rejects_new_saved_configuration(generic):
    service, body, _, repo, data, _ = generic
    result = finish(generic)
    project = service.runtime.project('child')
    service.generic().verify_configuration(project, result['receipt'])
    assert service.read('child')['prepared']
    data['commands']['environment']['SYNTHETIC_CHANGED'] = '1'
    save(repo, [change(repo, toml_document(data), 'project:child')], key='changed-project')
    with pytest.raises(RegistryError): service.generic().verify_configuration(project, result['receipt'])
    assert not service.read('child')['prepared']


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_real_cli_transport_journals_preparation_process_without_run_or_attempt(generic, monkeypatch, provider):
    service, _, _, _, _, tool = generic
    from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
    probe = str(Path(__file__).with_name('cli_process_probe.py'))
    configurations = {role: CLIConfig(provider, (sys.executable, probe, provider, 'success'),
                         '0.163.0' if provider == 'codex' else '2.1.304', (), 10)
                      for role in ('reviewer', 'executor')}
    root = service.runtime.project('child').context.root
    def agent(self, project):
        return CLIProcessAdapter(configurations, tool.parent / 'profile-captures')
    monkeypatch.setattr(ProfilePreparation, '_agent', agent)
    # This transport test checks an existing environment and needs no executor edits.
    result = finish(generic)
    with Session(service.runtime.engine) as session:
        processes = session.scalars(select(Process).where(Process.preparation_id == result['id'])).all()
        assert len(processes) == 2  # executor + native validation
        assert all(p.attempt_id is None and p.job_id is None and p.status == 'STOPPED' for p in processes)
        cli = next(p for p in processes if p.spec['adapter_version'] == 'cli-14')
        assert cli.identity and cli.capture['group_state'] == 'dead'
    assert result['receipt']['commit'] == result['plan']['base_head']  # No technical content change, no empty commit.


def test_expired_preparation_never_replays_and_requires_stopped_owner(generic):
    from datetime import timedelta, datetime, timezone
    service, body, executor, *_ = generic
    instant = datetime.now(timezone.utc)
    service.managed.clock = lambda: instant
    op = confirm(generic)
    claim = service.repository.claim(1)
    service.managed.clock = lambda: instant + timedelta(seconds=2)
    service.repository.recover_expired()
    assert service.repository.read(op['id'])['status'] == 'RECOVERY_REQUIRED'
    assert service.run_once() is None and not executor.calls
    with pytest.raises(Exception, match='alive|uncertain'):
        service.preview('child', {**body, 'previous_id': op['id'], 'retry_step': 0})


from test_profile_proposals import intake, apply_documents, preview as profile_preview, confirm as adopt_profile, response  # noqa: E402,F401


def test_reviewer_proposes_preparation_separately_and_adopts_without_execution(intake):
    world, cid, _ = intake
    p = candidate()
    p['preparation_plan'] = technical()
    _, turn = world.turn(cid, response(profile=p))
    assert turn['status'] == 'ANSWERED', turn
    apply_documents(world, cid)
    shown = profile_preview(world, cid)
    assert shown['ready'], shown
    adopted = adopt_profile(world, cid, shown)
    assert adopted['configuration_state'] == 'PROFILE_PROPOSED'
    assert not (world.context.root / '.prepare').exists()
    with Session(world.repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(Operation)) == 0


def test_generic_api_validates_exact_union_and_security_before_confirming(generic):
    from session_client import TestClient
    from my_harness.api.app import create_app
    service, body, *_ = generic
    # Keep the real protected app/session router, substitute only runtime composition with this synthetic fixture.
    application = create_app(str(service.runtime.engine.url), service.runtime.database.parent / 'test-ui',
                             managed=service.runtime.config)
    # managed_router closes over its own runtime; inject the service through that instance's class method.
    from my_harness.services.managed_runtime import ManagedRuntime
    original_start = ManagedRuntime.start
    # Use instance attributes after normal startup; all effects still target the same synthetic temporary database.
    from unittest.mock import patch
    def start(runtime):
        original_start(runtime)
        runtime.preparation = service
    with patch.object(ManagedRuntime, 'start', start):
        with TestClient(application, base_url='http://127.0.0.1:8013', headers={'X-My-Harness': '1'}) as http:
            base = '/api/managed/projects/child/preparation'
            assert http.post(base+'/preview', json={**body, 'argv': ['foreign']}).status_code == 422
            assert http.post(base+'/preview', json=body, headers={'Origin': 'https://foreign.invalid'}).status_code == 403
            shown = http.post(base+'/preview', json=body)
            assert shown.status_code == 200, shown.text
            request = {'change': body, 'preview_sha256': shown.json()['preview_sha256'],
                       'confirmed': True, 'reason': 'Exact generic preparation'}
            assert http.post(base+'/confirm', json=request).status_code == 422
            confirmed = http.post(base+'/confirm', json=request, headers={'Idempotency-Key': 'generic-api'})
            assert confirmed.status_code == 200, confirmed.text
            assert http.post(base+'/confirm', json=request, headers={'Idempotency-Key': 'generic-api'}).json() == confirmed.json()


@pytest.mark.parametrize('cancel', [True, False])
def test_preparation_executor_cancel_or_timeout_stops_group_and_never_issues_receipt(generic, monkeypatch, cancel):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
    service, _, _, _, _, tool = generic
    probe = str(Path(__file__).with_name('cli_process_probe.py'))
    configs = {role: CLIConfig('codex', (sys.executable, probe, 'codex', 'hang'), '0.163.0', (), 10 if cancel else .1)
               for role in ('reviewer', 'executor')}
    monkeypatch.setattr(ProfilePreparation, '_agent', lambda self, project: CLIProcessAdapter(configs, tool.parent / 'hung-captures'))
    op = confirm(generic)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(service.run_once)
        if cancel:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with Session(service.runtime.engine) as session:
                    process = session.scalar(select(Process).where(Process.preparation_id == op['id']))
                    if process and process.identity:
                        break
                time.sleep(.02)
            else:
                pytest.fail('Synthetic preparation executor never started')
            current = service.repository.read(op['id'])
            service.control(op['id'], {'expected_version': current['version'], 'plan_sha256': current['plan_sha256']}, 'cancel')
        assert future.result(timeout=15) == op['id']
    result = service.repository.read(op['id'])
    assert result['status'] == ('CANCELLED' if cancel else 'FAILED') and result['receipt'] is None
    with Session(service.runtime.engine) as session:
        process = session.scalar(select(Process).where(Process.preparation_id == op['id']))
        assert process.status == 'STOPPED' and process.capture['group_state'] == 'dead'
        assert session.get(Lock, result['plan']['root']) is None


def test_preparation_can_add_the_explicit_ignore_policy_before_technical_commit(generic):
    service, _, executor, *_ = generic
    root = service.runtime.project('child').context.root
    git(root, 'rm', '.gitignore'); git(root, 'commit', '-m', 'Synthetic documentary tree without stack files')
    with service.managed._write() as session:
        doc = session.scalar(select(Bootstrap).where(Bootstrap.root == str(root)))
        doc.result = {**doc.result, 'commit': git(root, 'rev-parse', 'HEAD'),
                      'documents': {p: h for p, h in doc.result['documents'].items() if p != '.gitignore'}}
        proposal = session.get(Proposal, generic[1]['proposal_id'])
        payload = json.loads(proposal.content)
        payload['candidate']['preparation_plan']['write_paths'].append('.gitignore')
        proposal.content = freeze(payload)
        proposal.content_sha256 = text_hash(proposal.content)
    original = executor.effect
    executor.effect = lambda root: (original(root), (root / '.gitignore').write_text('.prepare/\n'))
    result = finish(generic)
    assert '.gitignore' in git(root, 'show', '--format=', '--name-only', result['receipt']['commit'])
    assert '.prepare/' not in git(root, 'ls-files')


def test_stable_environment_is_accredited_separately_from_transient_reports(generic):
    service, body, executor, *_ = generic
    root = service.runtime.project('child').context.root
    with service.managed._write() as session:
        proposal = session.get(Proposal, body['proposal_id'])
        payload = json.loads(proposal.content)
        plan = payload['candidate']['preparation_plan']
        plan['write_paths'].append('.prepare/env/**')
        plan['local_paths'].append('.prepare/env/**')
        plan['environment_paths'] = ['.prepare/env/**']
        proposal.content = freeze(payload)
        proposal.content_sha256 = text_hash(proposal.content)
    original = executor.effect
    def prepare(root):
        original(root)
        (root / '.prepare/env').mkdir()
        (root / '.prepare/env/pinned.txt').write_text('synthetic dependency bytes')
    executor.effect = prepare
    result = finish(generic)
    receipt = result['receipt']
    assert '.prepare/env' in receipt['environment']  # Includes the environment directory's identity.
    assert '.prepare/test.xml' not in receipt['environment']
    (root / '.prepare/test.xml').write_text('next validation report')
    verify_receipt(root, receipt)
    (root / '.prepare/env/pinned.txt').write_text('changed dependency')
    with pytest.raises(JournalError): verify_receipt(root, receipt)


@pytest.mark.parametrize('valid', [True, False])
def test_dependency_lock_may_be_generated_only_with_exact_preconfirmed_hash(generic, valid):
    service, body, executor, *_ = generic
    content = 'synthetic-dependency v1.0.0 hash-for-test\n'
    with service.managed._write() as session:
        proposal = session.get(Proposal, body['proposal_id'])
        payload = json.loads(proposal.content)
        plan = payload['candidate']['preparation_plan']
        plan['write_paths'].append('go.sum')
        plan['dependencies'] = [{'name': 'synthetic-dependency', 'version': '1.0.0',
                                 'lock_path': 'go.sum', 'sha256': text_hash(content)}]
        proposal.content = freeze(payload)
        proposal.content_sha256 = text_hash(proposal.content)
    original = executor.effect
    executor.effect = lambda root: (original(root), (root / 'go.sum').write_text(content if valid else 'wrong lock bytes'))
    preview = service.preview('child', body)
    assert preview['dependency_inputs'][0]['base_sha256'] is None
    if valid:
        result = finish(generic)
        assert result['receipt']['protected_files']['go.sum'] == text_hash(content)
    else:
        op = confirm(generic)
        service.run_once()
        result = service.repository.read(op['id'])
        assert result['status'] == 'FAILED' and result['receipt'] is None
        with Session(service.runtime.engine) as session:
            assert not session.scalar(select(Process.id).where(Process.preparation_id == op['id']))


@pytest.mark.parametrize('fault', ['failed-cases', 'stale-report'])
def test_success_exit_requires_successful_fresh_junit(generic, fault):
    service, _, executor, _, _, tool = generic
    source = tool.read_text()
    report = '<testsuite><testcase classname="synthetic" name="go-test"/></testsuite>'
    if fault == 'failed-cases':
        source = source.replace('<testcase classname="synthetic" name="go-test"/>',
            '<testcase classname="synthetic" name="go-test"><failure message="synthetic"/></testcase>')
    else:
        source = '\n'.join(line for line in source.splitlines() if '.prepare/test.xml' not in line) + '\n'
        original = executor.effect
        executor.effect = lambda root: (original(root), (root / '.prepare/test.xml').write_text(report))
    tool.write_text(source)
    op = confirm(generic)
    service.run_once()
    result = service.repository.read(op['id'])
    assert result['status'] == 'FAILED' and result['receipt'] is None
    assert result['steps'][2]['status'] == 'STARTED'


def test_environment_links_allow_only_explicit_byte_bound_tools(generic):
    from my_harness.services.project_preparation import snapshot
    service, body, _, _, _, tool = generic
    root = service.runtime.project('child').context.root
    plan = service.preview('child', body)
    (root / '.prepare').mkdir()
    (root / '.prepare/tool-alias').symlink_to(tool)
    assert snapshot(root, ProfilePreparation._links(plan))['.prepare/tool-alias']['link'] == str(tool)
    foreign = tool.parent / 'foreign-tool'
    foreign.write_text('unapproved external bytes')
    (root / '.prepare/tool-alias').unlink()
    (root / '.prepare/tool-alias').symlink_to(foreign)
    with pytest.raises(ValueError): snapshot(root, ProfilePreparation._links(plan))
