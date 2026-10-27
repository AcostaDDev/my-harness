"""H3.1: synthetic templates, offline agents and temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from threading import Barrier

from alembic import command
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.core.engine.prompts import (
    VARIABLES, builtin_catalog, digest, dump_catalog, load_catalog, render, validate,
)
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PromptVersionRow, PromptActivationRow, PromptHeadRow
from my_harness.storage.prompts import PromptRepository
from test_engine import context, harness, edit, review, start
from test_managed_api import client, config, make_context


@pytest.fixture
def prompts(migrated_database):
    engine = make_engine(migrated_database[0])
    yield PromptRepository(engine)
    engine.dispose()


def activate(repo, context, name, suffix, scope='project'):
    d = repo.detail(context, scope, name)
    version = repo.draft(context, scope, name, d['generation'], text=d['effective']['template'] + suffix)
    repo.activate(context, scope, name, d['generation'] + 1, version['id'], 'Synthetic activation')
    return version


@pytest.mark.parametrize('name', tuple(VARIABLES))
def test_external_templates_keep_roles_and_interpolate_once(name):
    template = builtin_catalog()[name]
    variables = {v: 'synthetic-' + v + ' {{UNTRUSTED_DATA}}' for v in VARIABLES[name]}
    result = render(template, variables)
    assert all(value in result for value in variables.values())
    assert '{{UNTRUSTED_DATA}}' in result  # data, never recursive interpolation
    assert template.sha256 == digest(template.template)
    assert not any(stack in template.template for stack in ('Django', 'Docker', 'claude-sonnet-5-5'))
    assert load_catalog(dump_catalog(builtin_catalog())) == builtin_catalog()


def test_unified_prompts_retire_old_folders_without_rewriting_frozen_catalogs():
    catalog = builtin_catalog()
    assert all(old not in template.template for template in catalog.values()
               for old in ('decisions/', 'architecture/', 'research/'))
    names = ('define-project', 'plan-phase', 'reconcile-phase', 'close-phase', 'review-task',
             'execute-task', 'revise-task')
    for name in names:
        assert all(term in catalog[name].template for term in ('AGENTS.md', 'DDBB-DIAGRAM', 'flows/', 'phase/',
                                                              'DECISIONS.md', 'decision_proposals'))
        # Previous synthetic catalog: same variable schema, immutable content and identity.
        old = catalog[name].template + '\nOld layout: decisions/ architecture/ research/\n'
        catalog[name] = replace(catalog[name], template=old, sha256=digest(old), id='builtin-1:' + digest(old))
    frozen = dump_catalog(catalog)
    assert dump_catalog(load_catalog(frozen)) == frozen
    assert all(catalog[name].id != builtin_catalog()[name].id for name in names)


@pytest.mark.parametrize('name', ['define-project-profile', 'onboard-project-profile'])
def test_intake_prompts_explain_direct_executable_aliases_and_failed_turns(name):
    template = builtin_catalog()[name]
    assert all(term in template.template for term in ('Every argv[0]', 'tools.name',
               'distinct direct argv[0]', 'separate private', 'Prior failed turns include reasons'))
    frozen = dump_catalog(builtin_catalog())
    assert dump_catalog(load_catalog(frozen)) == frozen


@pytest.mark.parametrize('text', ['{{UNKNOWN}}', '{{INSTRUCTIONS', '{{ instructions }}', 'no variables', ''])
def test_invalid_variables_refuse_draft_atomically(prompts, context, text):
    with pytest.raises(ValueError):
        prompts.draft(context, 'project', 'execute-task', 0, text=text)
    with Session(prompts.engine) as session:
        assert session.scalar(select(func.count()).select_from(PromptVersionRow)) == 0
        assert session.scalar(select(func.count()).select_from(PromptHeadRow)) == 0


def test_missing_values_and_hash_corruption_block_before_effects(context):
    base = builtin_catalog()['execute-task']
    with pytest.raises(ValueError):
        render(base, {'INSTRUCTIONS': 'x'})
    engine, agents, runner, _ = harness(context, [])
    bad = builtin_catalog()
    bad['execute-task'] = replace(base, template=base.template + '{{UNKNOWN}}')
    engine.prompts = lambda _: bad
    history = start(engine, context)
    assert history.stop.stage == 'prompts'
    assert not agents.requests and not runner.calls and not history.attempts
    bad['execute-task'] = replace(base, sha256='0' * 64)
    assert start(engine, context).stop.stage == 'prompts'
    assert not agents.requests and not runner.calls


def test_hierarchy_draft_activation_rollback_and_restart(prompts, context):
    name = 'execute-task'
    base = builtin_catalog()[name]
    core = activate(prompts, context, name, '\ncore change', 'core')
    profile = activate(prompts, context, name, '\nprofile change', 'profile')
    project = activate(prompts, context, name, '\nproject change')
    assert prompts.catalog(context)[name].id == project['id']
    other_profile = replace(context.profile, name='other-stack')
    assert prompts.catalog(replace(context, profile=other_profile))[name].id == project['id']
    root = context.root.parent / 'other-project'; root.mkdir()
    assert prompts.catalog(replace(context, root=root))[name].id == profile['id']
    assert prompts.catalog(replace(context, root=root, profile=other_profile))[name].id == core['id']
    old = prompts.detail(context, 'project', name)
    copy = prompts.draft(context, 'project', name, old['generation'], from_version=base.id)
    assert copy['id'] != base.id and copy['template'] == base.template
    assert copy['source'] == 'rollback:' + base.id
    assert prompts.catalog(context)[name].id == project['id']  # rollback is a draft
    assert '-project change' in prompts.diff(context, name, project['id'], copy['id'])
    prompts.activate(context, 'project', name, old['generation'] + 1, copy['id'], 'Explicit rollback')
    prompts.engine.dispose()
    restarted = PromptRepository(make_engine(str(prompts.engine.url)))
    assert restarted.catalog(context)[name].id == copy['id']
    assert restarted.detail(context, 'project', name)['activations'][-1]['previous_id'] == project['id']
    assert next(v for v in restarted.detail(context, 'project', name)['versions'] if v['id'] == project['id']) == project
    restarted.engine.dispose()


def test_concurrent_activation_one_winner_no_partial_audit(prompts, context):
    base = builtin_catalog()['execute-task'].template
    a = prompts.draft(context, 'project', 'execute-task', 0, text=base + '\nA')
    b = prompts.draft(context, 'project', 'execute-task', 1, text=base + '\nB')
    barrier = Barrier(2)
    def attempt(version):
        barrier.wait()
        try:
            prompts.activate(context, 'project', 'execute-task', 2, version['id'], 'Concurrent synthetic edit')
            return version['id']
        except Conflict:
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, [a, b]))
    winners = [r for r in results if r]
    assert len(winners) == 1
    d = prompts.detail(context, 'project', 'execute-task')
    assert d['generation'] == 3 and d['active_id'] == winners[0]
    assert len(d['activations']) == 1 and len(d['versions']) == 3


def test_activation_during_attempt_keeps_snapshot_and_future_attempt_uses_new_version(prompts, context):
    saved = []
    new = []
    def execute(ctx, request):
        saved.append(freeze(asdict(request)))
        new.append(activate(prompts, ctx, 'review-task', '\nSynthetic review v2'))
        return edit()(ctx, request)
    engine, agents, _, _ = harness(context, [execute, review()])
    engine.prompts = prompts.catalog
    history = start(engine, context)
    assert history.status == 'acceptance_ready'
    assert freeze(asdict(agents.requests[0])) == saved[0]
    snapshot = json.loads(agents.requests[1].prompt_snapshot_json)
    assert snapshot['parts'][0]['version']['id'] == new[0]['id']
    assert snapshot['rendered_sha256'] == digest(agents.requests[1].prompt)
    assert snapshot['rendered'] == agents.requests[1].prompt
    assert snapshot['output_schema']['required'] == ['task_id', 'verdict']
    assert snapshot['document_references'] == [context.next_steps_file, context.state_file]
    assert load_history(dump_history(history)) == history


def test_restart_stopped_run_pins_catalog_and_preserves_attempts(prompts, context):
    first = activate(prompts, context, 'review-task', '\nVersion before interruption')
    engine, _, _, _ = harness(context, [AgentResult(None, error='Synthetic interruption')])
    engine.prompts = prompts.catalog
    stopped = start(engine, context)
    persisted = dump_history(stopped)
    activate(prompts, context, 'review-task', '\nNew active version')
    restarted, agents, _, _ = harness(context, [review()])
    restarted.prompts = prompts.catalog
    resumed = restarted.resume(context, load_history(persisted))
    assert resumed.status == 'acceptance_ready'
    assert resumed.attempts[:1] == stopped.attempts
    assert json.loads(agents.requests[0].prompt_snapshot_json)['parts'][0]['version']['id'] == first['id']
    assert dump_history(stopped) == persisted


def test_revision_uses_external_template_and_routing_no_extra_calls(context):
    engine, agents, _, _ = harness(context, [edit('one'), review('REVISE'), edit('two'), review()])
    result = start(engine, context)
    assert result.status == 'acceptance_ready'
    snapshots = [json.loads(r.prompt_snapshot_json) for r in agents.requests]
    assert [s['parts'][0]['version']['name'] for s in snapshots] == ['execute-task', 'review-task', 'revise-task', 'review-task']
    assert snapshots[1]['parts'][1]['version']['name'] == 'executor-routing'
    assert snapshots[2]['parts'][0]['variables']['REVIEW_JSON'] == result.cycles[0].review_json
    assert len(agents.requests) == 4


def test_api_editor_guard_conflict_diff_rollback_and_restart(migrated_database, tmp_path):
    root = tmp_path / 'checkout'; root.mkdir()
    context = make_context(root)
    setup = config(context, supervisor=False)
    path = '/api/managed/projects/synthetic/prompts/execute-task'
    with client(migrated_database[0], tmp_path, setup) as http:
        shown = http.get('/api/managed/projects/synthetic/prompts').json()
        assert {item['name'] for item in shown} == set(VARIABLES)
        assert len(shown) == len(VARIABLES)
        original = http.get(path).json()
        text = original['effective']['template'] + '\nSynthetic API draft'
        assert http.post(path + '/validate', json={'template': '{{INVALID}}'}).status_code == 422
        assert http.post(path + '/validate', json={'template': text}).status_code == 200
        assert http.post(path + '/versions', json={'expected_version': 0, 'template': text},
                         headers={'X-My-Harness': '0'}).status_code == 403
        assert http.post(path + '/versions', json={'expected_version': 0, 'template': text},
                         headers={'Origin': 'https://foreign.invalid'}).status_code == 403
        assert http.get(path, headers={'Host': 'foreign.invalid'}).status_code == 403
        created = http.post(path + '/versions', json={'expected_version': 0, 'template': text})
        assert created.status_code == 201, created.text
        version = created.json()
        assert http.get(path).json()['effective'] == original['effective']
        body = {'expected_version': 1, 'version_id': version['id'], 'reason': 'Synthetic activation', 'confirmed': True}
        assert http.post(path + '/activate', json={**body, 'confirmed': False}).status_code == 422
        activated = http.post(path + '/activate', json=body)
        assert activated.status_code == 200, activated.text
        assert http.post(path + '/activate', json=body).status_code == 409
        assert http.post(path + '/versions', json={'expected_version': 0, 'template': text}).status_code == 409
        assert http.get(path + '/diff', params={'before': original['effective']['id'], 'after': version['id']}).json()['diff']
        copied = http.post(path + '/versions', json={'expected_version': 2, 'from_version': original['effective']['id']})
        assert copied.status_code == 201
        rollback = copied.json()
        assert rollback['id'] != original['effective']['id']
        assert http.post(path + '/activate', json={**body, 'expected_version': 3, 'version_id': rollback['id']}).status_code == 200
        assert http.get(path + '/diff', params={'before': 'unknown', 'after': version['id']}).status_code == 404
        assert http.get('/api/managed/projects/unknown/prompts').status_code == 404
    with client(migrated_database[0], tmp_path, setup) as http:
        result = http.get(path).json()
        assert result['effective']['id'] == rollback['id']
        assert result['effective']['template'] == original['effective']['template']
        assert len(result['activations']) == 2


def test_cross_project_versions_and_wrong_scope_cannot_activate(prompts, context):
    v = activate(prompts, context, 'execute-task', '\nPrivate synthetic override')
    root = context.root.parent / 'other'; root.mkdir()
    other = replace(context, root=root)
    with pytest.raises(LookupError):
        prompts.draft(other, 'project', 'execute-task', 0, from_version=v['id'])
    with pytest.raises(ValueError):
        prompts.activate(context, 'profile', 'execute-task', 0, v['id'], 'Wrong scope')
    assert prompts.detail(context, 'profile', 'execute-task')['generation'] == 0


def test_schema_roundtrip_preserves_existing_managed_state(prompts, migrated_database, context):
    from my_harness.storage.models import ManagedRunRow
    from my_harness.storage.managed import SQLiteManagedRepository
    from test_managed import submit
    repository = SQLiteManagedRepository(prompts.engine)
    job = submit(repository, context)
    with Session(prompts.engine) as session:
        before = session.get(ManagedRunRow, job.run_id).history_json
    command.downgrade(migrated_database[1], '0007_managed_activation')
    command.upgrade(migrated_database[1], 'head')
    command.check(migrated_database[1])
    with Session(prompts.engine) as session:
        assert session.get(ManagedRunRow, job.run_id).history_json == before
        assert session.scalar(select(func.count()).select_from(PromptVersionRow)) == 0


def test_snapshot_is_persisted_before_agent_and_old_rows_survive_activation(prompts, context):
    from my_harness.storage.managed import SQLiteManagedRepository
    from my_harness.storage.models import ManagedAttemptRow
    from my_harness.storage.managed_views import SQLiteManagedViews
    from test_managed import submit, worker
    repository = SQLiteManagedRepository(prompts.engine)
    old = activate(prompts, context, 'execute-task', '\nInitial persisted template')
    captured = []
    def execute(ctx, request):
        with Session(prompts.engine) as session:
            row = session.get(ManagedAttemptRow, request.id)
            assert row.result_json is None
            assert json.loads(row.request_json)['prompt_snapshot_json'] == request.prompt_snapshot_json
            captured.append(row.request_json)
        activate(prompts, ctx, 'execute-task', '\nChanged during executor')
        return edit()(ctx, request)
    job = submit(repository, context)
    supervisor, agents, _, _ = worker(repository, context, [execute, review()])
    assert supervisor.run_once().status == 'DONE'
    prompts.engine.dispose()
    record = repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY'
    snapshot = json.loads(record.history.attempts[0].request.prompt_snapshot_json)
    assert snapshot['parts'][0]['version']['id'] == old['id']
    with Session(prompts.engine) as session:
        assert session.get(ManagedAttemptRow, agents.requests[0].id).request_json == captured[0]
    view = SQLiteManagedViews(prompts.engine).attempts(job.run_id, 0, 30)['items'][0]
    assert view['prompt_snapshot'] == snapshot and view['prompt'] == snapshot['rendered']
