"""P013-T007: synthetic documentary intakes, fake reviewers, temporary Git/SQLite; no stack commands."""
from dataclasses import replace
import json
import sys

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.core.engine.context import IntakeContext
from my_harness.core.engine.contracts import ContractError, context_snapshot
from my_harness.core.engine.definition import text_hash
from my_harness.core.engine.serialization import restore_context
from my_harness.services.profile_proposal import validate
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.models import ConfigurationOperationRow, RegisteredProjectRow
from my_harness.storage.onboarding import OnboardingDrafts
from my_harness.i18n import emission, message
from test_definition import World, answer
from test_managed_api import IDENTITY, VERSIONS, Ports, make_context, client
from test_project_onboarding import checkout, git
from my_harness.adapters.git import GitWorkspace
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject

DOCS = {
    'docs/SPECIFICATION.md': '# Specification\n\nA synthetic Go calculator.\n',
    'docs/ARCHITECTURE.md': '# Architecture\n\nGo modules; validate with go test ./...; no persistence.\n',
    'AGENTS.md': '# Rules\n\nRead docs first. Planned validation: go test ./... (not checked).\n',
}
SOURCES = {'go.mod': 'module example.invalid/synthetic\n\ngo 1.25\n',
           'main.go': 'package main\nfunc main() {}\n'}


def candidate(docs=DOCS):
    source = {'path': 'docs/ARCHITECTURE.md', 'sha256': text_hash(docs['docs/ARCHITECTURE.md'])}
    return {'name': 'own-go', 'rationale': 'Go follows the documented architecture.',
            'profile': {'preparation': [], 'validations': [{'argv': ['go', 'test', './...'], 'timeout_seconds': 120}],
                        'allowed_command_prefixes': [], 'protected_paths': ['go.mod', 'go.sum'],
                        'sensitive_paths': ['.env', '.env.*'], 'data_model_paths': [],
                        'executor_instructions': 'Implement the documented calculator in Go.'},
            'tools': [{'name': 'go', 'requirement': 'Go 1.25 toolchain; installation deferred.'}],
            'evidence': [{'kind': 'validation', 'index': 0, 'purpose': 'test', 'sources': [source],
                          'reason': 'Compile packages and run their Go tests.'}]}


def response(docs=DOCS, profile=True, **kwargs):
    return {**answer(docs, **kwargs), 'profile': candidate(docs) if profile is True else profile}


@pytest.fixture(params=['definition', 'onboarding'])
def intake(request, migrated_database, tmp_path):
    kind = request.param
    root = tmp_path / 'synthetic project'
    if kind == 'onboarding':
        checkout(root, SOURCES)
    else:
        root.mkdir()
    base = make_context(root)
    context = IntakeContext(root, base.policy)
    engine = make_engine(migrated_database[0])
    repo = SQLiteManagedRepository(engine)
    writer = GitWorkspace(IDENTITY)
    ports = Ports()
    worker = LocalSupervisor(repo, ports, commit_factory=lambda c, v: writer)
    world = World(context, repo, writer, worker, ports)
    cid = world.planning.create(context, kind=kind, title='Synthetic Go project', writer=writer,
                                brief='A calculator in a stack selected from architecture.' if kind == 'definition' else None)
    yield world, cid, kind
    engine.dispose()


def apply_documents(world, cid):
    for proposal in world.view(cid)['proposals']:
        if proposal['kind'] == 'draft' and proposal['status'] == 'PROPOSED':
            world.planning.apply(world.context, cid, proposal['id'], world.view(cid)['version'],
                                 proposal_sha256=proposal['proposal_sha256'], confirmed=True, writer=world.writer)


def profile(world, cid):
    return next(p for p in world.view(cid)['proposals'] if p['kind'] == 'profile' and p['status'] == 'PROPOSED')


def preview(world, cid, proposal=None):
    p = proposal or profile(world, cid)
    return world.planning.profile_preview(world.context, cid, p['id'], world.view(cid)['version'],
                                          p['proposal_sha256'], world.writer)


def confirm(world, cid, shown=None, key='adopt'):
    shown = shown or preview(world, cid)
    return world.planning.confirm_profile(world.context, cid, shown['proposal_id'], shown['expected_version'],
        proposal_sha256=shown['proposal_sha256'], preview_sha256=shown['preview_sha256'],
        reason='Reviewed exact Go draft', key=key, writer=world.writer)


def test_profileless_intake_proposes_and_adopts_without_configuration_or_commands(intake):
    world, cid, kind = intake
    assert not hasattr(world.context, 'profile')
    assert restore_context(context_snapshot(world.context)) == world.context
    before = {p.relative_to(world.context.root).as_posix(): p.read_bytes()
              for p in world.context.root.rglob('*') if p.is_file()}
    job, turn = world.turn(cid, response())
    assert turn['status'] == 'ANSWERED', turn
    request = world.repo.get_run(job.run_id).history.attempts[0].request
    frozen_prompt = json.loads(request.prompt_snapshot_json)
    assert frozen_prompt['parts'][0]['version']['name'] == (
        'define-project-profile' if kind == 'definition' else 'onboard-project-profile')
    assert 'profile' in frozen_prompt['output_schema']['required']
    assert frozen_prompt['language']['work_language'] == 'en'
    payload = json.loads(profile(world, cid)['content'])
    assert payload['tools_status'] == 'DEFERRED' and payload['preparation_status'] == 'NOT_CHECKED'
    assert not preview(world, cid)['ready']  # Proposed documents have not been adopted.
    apply_documents(world, cid)
    shown = preview(world, cid)
    assert shown['ready'], shown
    result = confirm(world, cid, shown)
    assert result['configuration_state'] == 'PROFILE_PROPOSED'
    assert confirm(world, cid, shown) == result
    with Session(world.repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(ConfigurationOperationRow)) == 0
    assert world.ports.roles() == ['definition'] and world.worker.run_once() is None
    if kind == 'onboarding':
        assert {p.relative_to(world.context.root).as_posix(): p.read_bytes()
                for p in world.context.root.rglob('*') if p.is_file()} == before
        assert (OnboardingDrafts.of(world.repo.engine, cid).base / 'AGENTS.md').exists()
    else:
        assert not (world.context.root / '.git').exists()
    with pytest.raises(Conflict):
        world.repo.submit(world.context, 'P001-T001', 'P001', 'Forbidden', VERSIONS, key='task')
    if kind == 'definition':
        assert not world.bootstrap.preview(world.context, {'conversation_id': cid}, VERSIONS, world.writer)['ready']


@pytest.mark.parametrize('fault', ['extra', 'tools', 'validation', 'shell', 'cwd', 'formatter', 'evidence',
                                   'missing-architecture', 'shape', 'secret', 'prefix-evidence'])
def test_invalid_profile_stops_the_turn_without_retry(intake, fault):
    world, cid, _ = intake
    result = response()
    p = result['profile']
    if fault == 'extra':
        p['grant_global_write'] = True
    elif fault == 'tools':
        p['tools'] = []
    elif fault == 'validation':
        p['profile']['validations'][0]['argv'] = ['go', '--version']
    elif fault == 'shell':
        p['profile']['validations'][0]['argv'] = ['sh', '-c', 'true']
    elif fault == 'cwd':
        p['profile']['validations'][0]['cwd'] = '../elsewhere'
    elif fault == 'formatter':
        p['profile'].update(formatter_argv=['go', 'fmt'], formatter_paths=['**/*.go'])
    elif fault == 'evidence':
        p['evidence'][0]['sources'][0]['sha256'] = '0' * 64
    elif fault == 'missing-architecture':
        result['drafts'] = []
    elif fault == 'shape':
        result['profile'] = 'Run go test'
    elif fault == 'secret':
        p['profile']['executor_instructions'] = 'sk-secret-synthetic'
    elif fault == 'prefix-evidence':
        p['profile']['allowed_command_prefixes'] = [['go', 'run']]
    _, turn = world.turn(cid, result)
    assert turn['status'] == 'FAILED', turn
    assert world.view(cid)['proposals'] == [] and world.worker.run_once() is None


def test_missing_context_asks_questions_without_a_fake_profile(intake):
    world, cid, _ = intake
    _, turn = world.turn(cid, response({}, None, questions=[{'text': 'Which architecture?', 'blocking': True}]))
    assert turn['status'] == 'ANSWERED' and world.view(cid)['questions'][0]['blocking']
    assert world.view(cid)['proposals'] == []


@pytest.mark.parametrize('language', ['en', 'es'])
def test_profile_adoption_requires_applied_documents_but_not_informational_pending_items(intake, language):
    world, cid, _ = intake
    notices = ['Review the initial profile.', 'Prepare the local environment after the documentary commit.']
    world.turn(cid, response(pending=notices))
    with emission(language):
        shown = preview(world, cid)
        assert shown['blockers'] == [message('profile_proposal.documents_required', language,
                                             paths=', '.join(sorted(DOCS)))]
        with pytest.raises(Conflict):
            confirm(world, cid, shown)
        # Applying one proposal is insufficient and must not be labelled as an invalid profile.
        first = next(p for p in world.view(cid)['proposals'] if p['kind'] == 'draft')
        world.apply(cid, first)
        shown = preview(world, cid)
        remaining = sorted(set(DOCS) - {first['path']})
        assert shown['blockers'] == [message('profile_proposal.documents_required', language,
                                             paths=', '.join(remaining))]
        apply_documents(world, cid)
        shown = preview(world, cid)
        assert shown['ready'] and not shown['blockers']
        adopted = confirm(world, cid, shown)
        assert adopted['configuration_state'] == 'PROFILE_PROPOSED'
    assert world.view(cid)['pending'] == notices
    assert world.ports.roles() == ['definition'] and not world.ports.runner.calls
    with Session(world.repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(ConfigurationOperationRow)) == 0


def test_profile_adoption_blocks_open_questions_but_accepts_explicit_deferral(intake):
    world, cid, _ = intake
    world.turn(cid, response(questions=[{'text': 'Which deployment target?', 'blocking': True}],
                             pending=['Preparation will be reviewed separately.']))
    apply_documents(world, cid)
    assert preview(world, cid)['blockers'] == [message('profile_proposal.questions', 'en')]
    question = world.view(cid)['questions'][0]
    world.planning.defer(cid, world.view(cid)['version'], question_id=question['id'],
                         reason='Local development only; deployment is a later phase.')
    shown = preview(world, cid)
    assert shown['ready'], shown
    assert confirm(world, cid, shown)['configuration_state'] == 'PROFILE_PROPOSED'


def test_changed_private_document_has_a_document_diagnostic_and_preserves_profile(intake):
    world, cid, kind = intake
    world.turn(cid, response())
    apply_documents(world, cid)
    p = profile(world, cid)
    area = world.context.root if kind == 'definition' else OnboardingDrafts.of(world.repo.engine, cid).base
    (area / 'docs/ARCHITECTURE.md').write_text('# Explicit user edit after the proposal\n')
    shown = preview(world, cid)
    assert shown['blockers'] == [message('profile_proposal.documents_changed', 'en',
                                        paths='docs/ARCHITECTURE.md')]
    with pytest.raises(Conflict):
        confirm(world, cid, shown)
    assert profile(world, cid) == p


def test_profile_edit_with_pending_notices_still_requires_documents_and_exact_adoption(intake):
    world, cid, _ = intake
    world.turn(cid, response(pending=['Prepare dependencies after adoption.']))
    original = profile(world, cid)
    changed = json.loads(original['content'])['candidate']
    changed['rationale'] = 'Reviewed the documented Go toolchain for initial local development.'
    with pytest.raises(Conflict):
        world.planning.edit_profile(world.context, cid, original['id'], world.view(cid)['version'],
            original['proposal_sha256'], changed, 'Reviewed initial profile', 'before-documents', writer=world.writer)
    assert profile(world, cid) == original
    apply_documents(world, cid)
    edited = world.planning.edit_profile(world.context, cid, original['id'], world.view(cid)['version'],
        original['proposal_sha256'], changed, 'Reviewed initial profile', 'after-documents', writer=world.writer)
    assert profile(world, cid)['id'] == edited['proposal_id']
    shown = preview(world, cid)
    assert shown['ready']
    assert confirm(world, cid, shown)['proposal_id'] == edited['proposal_id']
    assert world.view(cid)['pending'] == ['Prepare dependencies after adoption.']
    assert world.ports.roles() == ['definition'] and not world.ports.runner.calls


@pytest.mark.parametrize('field', ['preparation', 'validations', 'allowed_command_prefixes', 'formatter_argv'])
@pytest.mark.parametrize('language', ['en', 'es'])
def test_executable_path_diagnostic_identifies_field_without_candidate_values(field, language):
    p = candidate()
    argv = ['/synthetic/private/bin/tool', '--synthetic-sensitive-argument']
    if field == 'formatter_argv':
        p['profile'].update(formatter_argv=argv, formatter_paths=['**/*.go'])
        location = 'profile.formatter_argv'
    else:
        p['profile'][field] = [argv if field == 'allowed_command_prefixes' else
                               {'argv': argv, 'timeout_seconds': 120}]
        location = f'profile.{field}[0]'
    with emission(language), pytest.raises(ContractError) as error:
        validate(p, {}, [])
    assert str(error.value) == message('profile_proposal.command_executable', language, field=location)
    assert all(value not in str(error.value) for value in argv)


def test_failed_profile_reason_reaches_next_turn_without_adopting_rejected_output(intake):
    world, cid, _ = intake
    rejected = response()
    rejected['profile']['profile']['validations'][0]['argv'][0] = '/synthetic/private/bin/go'
    _, failed = world.turn(cid, rejected)
    assert failed['status'] == 'FAILED' and not world.view(cid)['proposals']
    before = world.repo.get_run(failed['run_id']).history
    _, recovered = world.turn(cid, response())
    assert recovered['status'] == 'ANSWERED'
    prompt = json.loads(world.ports.agents.requests[-1].prompt_snapshot_json)
    previous = json.loads(prompt['parts'][0]['variables']['CONTEXT_JSON'])['previous_turns'][-1]
    assert previous['reasons'] == failed['result']['reasons']
    assert previous['answer'] is None and previous['proposals'] == []
    assert world.repo.get_run(failed['run_id']).history == before
    assert len(world.ports.agents.requests) == 2


def test_container_tool_requirements_do_not_add_indirect_executables():
    p = candidate()
    p['profile']['validations'][0]['argv'] = ['docker', 'compose', 'exec', 'web', 'python', 'manage.py', 'test']
    p['tools'] = [{'name': 'docker', 'requirement': 'Compose and an image containing Python and the test runner.'}]
    frozen = {'project': {'layout': {'docs': 'docs', 'state': 'docs/STATE.md', 'next_steps': 'docs/NEXT_STEPS.md'}},
              'drafts': [{'path': path, 'sha256': text_hash(content)} for path, content in DOCS.items()]}
    assert validate(p, frozen, [])['candidate'] == p
    p['tools'].append({'name': 'python', 'requirement': 'Inside the container only.'})
    with pytest.raises(ContractError, match='direct argv'):
        validate(p, frozen, [])


def test_questions_cas_context_and_document_drift_block_adoption(intake):
    world, cid, kind = intake
    world.turn(cid, response(questions=[{'text': 'Which Go version?', 'blocking': True}]))
    apply_documents(world, cid)
    assert not preview(world, cid)['ready']
    world.turn(cid, response())
    apply_documents(world, cid)
    shown = preview(world, cid)
    assert shown['ready']
    p = profile(world, cid)
    with pytest.raises(Conflict):
        world.planning.profile_preview(world.context, cid, p['id'], 0, p['proposal_sha256'], world.writer)
    assert not world.planning.profile_preview(world.context, cid, p['id'], world.view(cid)['version'],
        p['proposal_sha256'], world.writer, versions={**VERSIONS, 'cli_config_sha256': 'changed'})['ready']
    changed = replace(world.context, policy=replace(world.context.policy, reviewer_model='different'))
    assert not world.planning.profile_preview(changed, cid, p['id'], world.view(cid)['version'],
                                              p['proposal_sha256'], world.writer)['ready']
    area = world.context.root if kind == 'definition' else OnboardingDrafts.of(world.repo.engine, cid).base
    (area / 'docs/ARCHITECTURE.md').write_text('# Architecture edited after review\n')
    assert not preview(world, cid)['ready']
    with pytest.raises(Conflict):
        confirm(world, cid, shown)


def test_new_answer_supersedes_adopted_profile_and_preserves_confirmation_replay(intake):
    world, cid, _ = intake
    world.turn(cid, response())
    apply_documents(world, cid)
    shown = preview(world, cid)
    adopted = confirm(world, cid, shown)
    job, _ = world.turn(cid, response({}, None))
    frozen = world.planning.snapshot(job.run_id)['context']['profile_draft']
    assert frozen['id'] == shown['proposal_id'] and frozen['status'] == 'ACCEPTED'
    assert frozen['content']['candidate']['name'] == 'own-go'
    assert next(p for p in world.view(cid)['proposals'] if p['id'] == shown['proposal_id'])['status'] == 'SUPERSEDED'
    assert confirm(world, cid, shown) == adopted
    with pytest.raises(Conflict):
        confirm(world, cid, {**shown, 'preview_sha256': '0' * 64})


def test_new_head_before_queue_or_go_blocks_intake_reviewer(intake):
    world, cid, kind = intake
    if kind != 'onboarding':
        return  # A definition has no HEAD; its filesystem CAS is covered above.
    job = world.message(cid)
    (world.context.root / 'main.go').write_text('package main\nfunc main() { println(1) }\n')
    git(world.context.root, 'add', 'main.go')
    git(world.context.root, 'commit', '-qm', 'Synthetic drift')
    world.ports.agents.responses.append(response())
    assert world.worker.run_once().status == 'DONE'
    assert world.view(cid)['turns'][-1]['status'] == 'FAILED' and world.ports.roles() == []
    with pytest.raises(Conflict):
        world.message(cid)


def test_http_intake_profile_contract_and_guards(intake, tmp_path):
    world, cid, _ = intake
    config = ManagedConfig((ManagedProject('intake', world.context, VERSIONS, bootstrap_enabled=True),),
                            ports_factory=world.ports, commit_factory=lambda c, v: world.writer)
    with client(str(world.repo.engine.url), tmp_path, config) as http:
        base = f'/api/managed/projects/intake/planning/{cid}'
        state = http.get('/api/managed/projects').json()[0]
        assert state['profile'] is None and state['configuration_state'] == 'PROFILE_REQUIRED'
        # Runtime seals the work language, unlike storage-only fixtures.
        world.context = http.app.state.runtime.project('intake').context
        world.turn(cid, response(pending=['Review preparation separately after the documentary commit.']))
        p = profile(world, cid)
        body = {'proposal_id': p['id'], 'proposal_sha256': p['proposal_sha256'],
                'expected_version': world.view(cid)['version']}
        assert http.post(base + '/profile/preview', json=body,
                         headers={'Origin': 'https://foreign.invalid'}).status_code == 403
        http.headers.pop('X-My-Harness')
        assert http.post(base + '/profile/preview', json=body).status_code == 403
        http.headers['X-My-Harness'] = '1'
        missing = http.post(base + '/profile/preview', json=body)
        assert missing.status_code == 200 and not missing.json()['ready']
        assert missing.json()['blockers'] == [message('profile_proposal.documents_required', 'en',
                                                       paths=', '.join(sorted(DOCS)))]
        blocked = http.post(base + '/profile/confirm', json={**body,
            'preview_sha256': missing.json()['preview_sha256'], 'confirmed': True, 'reason': 'Before documents'},
            headers={'Idempotency-Key': 'http-before-documents'})
        assert blocked.status_code == 409
        assert profile(world, cid)['status'] == 'PROPOSED'
        apply_documents(world, cid)
        body['expected_version'] = world.view(cid)['version']
        shown = http.post(base + '/profile/preview', json=body)
        assert shown.status_code == 200 and shown.json()['ready'], shown.text
        assert http.post(base + '/profile/confirm', json={**body, 'preview_sha256': shown.json()['preview_sha256'],
                          'confirmed': True, 'reason': 'Reviewed'}).status_code == 422
        body.update(preview_sha256=shown.json()['preview_sha256'], confirmed=True, reason='Reviewed')
        saved = http.post(base + '/profile/confirm', json=body, headers={'Idempotency-Key': 'http-profile'})
        assert saved.status_code == 200, saved.text
        assert http.post(base + '/profile/confirm', json=body,
                         headers={'Idempotency-Key': 'http-profile'}).json() == saved.json()
        assert http.post(base + '/profile/preview', json={**body, 'unexpected': True}).status_code == 422
        assert http.get(base).json()['proposals'][-1]['kind'] == 'profile'
        assert http.get('/api/managed/projects/intake').json()['configuration_state'] == 'PROFILE_PROPOSED'


def test_full_profile_shape_retains_formatter_preparation_junit_and_inventory_evidence():
    frozen = {'project': {'layout': {'docs': 'docs', 'state': 'docs/STATE.md', 'next_steps': 'docs/NEXT_STEPS.md'}},
              'drafts': [{'path': path, 'sha256': text_hash(content)} for path, content in DOCS.items()],
              'inventory': {'entries': [{'path': 'go.mod', 'sha256': text_hash(SOURCES['go.mod']), 'status': 'read'}]},
              'head': 'synthetic-head', 'tree': 'synthetic-tree', 'inventory_sha256': '1' * 64}
    p = candidate()
    p['profile'].update(preparation=[{'argv': ['go', 'mod', 'download'], 'timeout_seconds': 120}],
                        allowed_command_prefixes=[['go', 'run']],
                        formatter_argv=['gofmt', '-w', '--'], formatter_paths=['**/*.go'])
    p['profile']['validations'][0]['junit'] = {'path': '.reports/go.xml', 'coverage': 'Go packages'}
    p['tools'].append({'name': 'gofmt', 'requirement': 'Formatter from the chosen Go toolchain.'})
    for kind, purpose in [('preparation', 'prepare'), ('prefix', 'execute'), ('formatter', 'format')]:
        p['evidence'].append({'kind': kind, 'index': 0, 'purpose': purpose,
                             'sources': [{'path': 'go.mod', 'sha256': text_hash(SOURCES['go.mod'])}],
                             'reason': 'Declared Go module and toolchain.'})
    checked = validate(p, frozen, [])
    assert checked['candidate'] == p and checked['binding']['head'] == 'synthetic-head'
    assert checked['configuration_status'] == 'NOT_SAVED'


def test_v9_registration_without_composition_is_documentary_and_survives_restart(setup, tmp_path, monkeypatch):
    import shutil
    from my_harness.services.local_config import _build
    from test_project_registry import register, confirm as register_confirm
    repo, data, directory = setup
    root = tmp_path / 'empty intake'
    root.mkdir()
    data['registration'] = {'roots': [str(tmp_path)], 'bootstrap_enabled': True}
    data['git']['executable'] = shutil.which('git')
    data['compositions'] = {}
    config = _build(data, directory / 'global.toml', allow_empty_compositions=True, editor=True)[0]
    # A fixed CLI observation stands in for the admitted clients. No version/help or model calls here.
    monkeypatch.setattr(config.registrar, '_resolve_agents', lambda agents: {
        role: replace(agent, cli_version='0.163.0', executable=(sys.executable,))
        for role, agent in agents.items()})
    change = register(root, project_id='intake', composition=None, bootstrap_enabled=True)
    with client(str(repo.managed.engine.url), tmp_path, config) as http:
        shown, saved = register_confirm(http, change)
        assert saved.status_code == 200, saved.text
        assert shown['profile'] is None and shown['row']['composition'] is None
        assert http.app.state.runtime.project('intake').context.__class__ is IntakeContext
        listed = http.get('/api/managed/projects').json()[0]
        assert listed['profile'] is None and listed['configuration_state'] == 'PROFILE_REQUIRED'
        created = http.post('/api/managed/projects/intake/planning', json={
            'kind': 'definition', 'title': 'Go from requirements', 'brief': 'A Go calculator'},
            headers={'Idempotency-Key': 'definition'})
        assert created.status_code == 201, created.text
        with Session(repo.managed.engine) as session:
            row = session.get(RegisteredProjectRow, 'intake')
            assert row.profile is None and row.composition is None
        # A named composition cannot bypass the missing preparation/activation lane.
        refused = http.post('/api/managed/registry/preview', json={
            **change, 'action': 'update', 'expected_version': 1, 'root': None,
            'composition': 'some-example', 'work_language': None})
        assert refused.status_code == 422
    with client(str(repo.managed.engine.url), tmp_path, config) as http:
        assert http.get('/api/managed/projects/intake').json()['configuration_state'] == 'PROFILE_REQUIRED'
    with pytest.raises(RuntimeError, match='0027'):
        command.downgrade(Config('alembic.ini'), '0026_configuration')


# Reuse only synthetic configuration data (no installed providers).
from test_configuration import setup  # noqa: E402, F401


def test_migration_retains_legacy_registration_and_referencing_audit(migrated_database):
    from sqlalchemy import text
    from my_harness.storage.models import RegisteredProjectEventRow
    url, alembic = migrated_database
    engine = make_engine(url)
    command.downgrade(alembic, '0026_configuration')
    with Session(engine) as session, session.begin():
        session.add(RegisteredProjectRow(id='legacy', version=1, status='ACTIVE', root='/synthetic/legacy',
            composition='web', profile='typescript-web', row={'legacy': True}, row_sha256='1' * 64,
            trust={'confirmed': True}, created_at='synthetic', updated_at='synthetic'))
        session.flush()
        session.add(RegisteredProjectEventRow(project_id='legacy', version=1, action='register', row={'legacy': True},
            row_sha256='1' * 64, previous_sha256=None, preview_sha256='2' * 64, actor={'synthetic': True},
            reason='Synthetic legacy confirmation', recorded_at='synthetic'))
    command.upgrade(alembic, 'head')
    command.check(alembic)
    with Session(engine) as session:
        assert session.get(RegisteredProjectRow, 'legacy').row == {'legacy': True}
        event = session.scalar(select(RegisteredProjectEventRow))
        assert event.reason == 'Synthetic legacy confirmation' and event.row_sha256 == '1' * 64
        assert session.execute(text('PRAGMA foreign_key_check')).all() == []
    command.downgrade(alembic, '0026_configuration')
    command.upgrade(alembic, 'head')
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(RegisteredProjectEventRow)) == 1
    engine.dispose()


def test_versioned_global_authority_restarts_with_profileless_registration(setup, tmp_path, monkeypatch):
    import shutil
    from my_harness.services.local_config import LocalComposer
    from test_configuration_api import app_for, store, schedule
    from test_project_registry import register, confirm as register_confirm
    from session_client import TestClient
    repo, data, _ = setup
    root = tmp_path / 'versioned global intake'
    root.mkdir()
    data['registration'] = {'roots': [str(tmp_path)], 'bootstrap_enabled': True}
    data['git']['executable'] = shutil.which('git')
    monkeypatch.setattr(LocalComposer, '_resolve_agents', lambda self, agents: {
        role: replace(agent, cli_version='0.163.0', executable=(sys.executable,))
        for role, agent in agents.items()})
    with TestClient(app_for(repo)) as http:
        store(http, data)
        schedule(http)
    with TestClient(app_for(repo)) as http:
        assert http.get('/api/managed/configuration').json()['mode'] == 'READY'
        # This fixture's client needs the ordinary local CSRF header on mutations.
        http.headers['X-My-Harness'] = '1'
        _, saved = register_confirm(http, register(root, project_id='intake', composition=None, bootstrap_enabled=True))
        assert saved.status_code == 200, saved.text
    with TestClient(app_for(repo)) as http:
        assert http.get('/api/managed/configuration').json()['mode'] == 'READY'
        project = http.get('/api/managed/projects/intake')
        assert project.status_code == 200 and project.json()['configuration_state'] == 'PROFILE_REQUIRED'
        assert http.app.state.runtime.worker is None
