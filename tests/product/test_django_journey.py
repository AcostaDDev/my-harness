"""T005: one child, four fake CLI pairs, real API/Git/SQLite and optional real Django.

The default toolchain is synthetic and offline. Real tools require an explicit
HARNESS_TEST_DJANGO_WHEELHOUSE and HARNESS_TEST_DJANGO_PYTHON, prepared separately;
this test never downloads packages or invokes a real model provider.
"""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.recipes import django
from my_harness.services.local_config import load_local_config
from my_harness.services.managed import LocalSupervisor
from my_harness.services.project_registry import digest
from my_harness.storage.models import ManagedProcessRow
from test_definition import DRAFTS, answer
from test_local_config import launches, setup, web, write  # noqa: F401
from test_managed_api import client, git
from test_project_agents import selection, v5
from test_project_preparation import recipe_data
from test_project_registry import POLICY, operator  # noqa: F401

BASE = '/api/managed/projects/child'
ROOT = '/api/managed/project-creation-root'
CREATE = '/api/managed/project-creations'
PAIRS = [('codex', 'codex'), ('codex', 'claude'), ('claude', 'claude'), ('claude', 'codex')]
CRITERION = 'El flujo sintético está aceptado.'
FORMATTED = 'core/synthetic_format.py'


def post(http, path, body, key=None, status=200):
    response = http.post(path, json=body, headers={'Idempotency-Key': key} if key else {})
    assert response.status_code == status, response.text
    return response.json()


def drafts():
    result = dict(DRAFTS)
    task = result['docs/NEXT_STEPS.md'].split('## P001-T001')[1]
    task = '## P001-T001' + task.replace('`app/**`', '`templates/`').replace(
        '`test-runner check`', '`pytest --junitxml=reports/pytest.xml`')
    result['docs/NEXT_STEPS.md'] = result['docs/NEXT_STEPS.md'].split('## P001-T001')[0] + '\n'.join(
        task.replace('P001-T001', f'P001-T00{i}') for i in range(1, 5))
    return result


@pytest.fixture(params=['synthetic', 'real'])
def journey(request, operator, migrated_database, monkeypatch):
    _, raw, folder, tmp_path = operator
    value = recipe_data(raw, folder)
    presets = v5(raw, [])['agent_presets']
    script = folder / 'responses.json'
    for agent in [*value['agents'].values(), *presets.values()]:
        agent['executable'][-1] = 'recipe'
        agent['environment'].update(PROBE_SCRIPT=str(script), PYTHONDONTWRITEBYTECODE='1')
    value['agent_presets'] = presets
    real = request.param == 'real'
    if real:
        wheelhouse = os.environ.get('HARNESS_TEST_DJANGO_WHEELHOUSE')
        python = os.environ.get('HARNESS_TEST_DJANGO_PYTHON')
        if not wheelhouse and not python:
            pytest.skip('Real Django requires explicitly prepared wheels and Python; no implicit downloads')
        assert wheelhouse and python, 'Both explicit wheelhouse and Python are required'
        python = str(Path(python).resolve(strict=True))
        assert Path(wheelhouse).is_dir()
        version = subprocess.run([python, '--version'], check=True, capture_output=True, text=True).stdout.split()[1]
        installer = str(Path(shutil.which('uv')).resolve(strict=True))
        uv_version = subprocess.run([installer, '--version'], check=True, capture_output=True, text=True).stdout.split()[1]
        value['recipes']['django'].update(python_executable=python, python_version=version,
            installer_executable=installer, installer_version=uv_version, wheelhouse=str(Path(wheelhouse).resolve()))
    config = load_local_config(write(folder, value))
    captured = []
    app = importlib.import_module('my_harness.api.app')
    runtime_class = app.ManagedRuntime
    def runtime(*args, **kwargs):
        instance = runtime_class(*args, **kwargs)
        captured.append(instance)
        return instance
    monkeypatch.setattr(app, 'ManagedRuntime', runtime)
    if not real:
        from my_harness.services.project_preparation import ProjectPreparation
        original = ProjectPreparation._files
        def files(self, root, plan):
            original(self, root, plan)
            (root / django.WORK / 'packages.json').write_text(json.dumps(django.PACKAGES))
        monkeypatch.setattr(ProjectPreparation, '_files', files)
    yield config, captured, script, tmp_path, real


def test_new_child_definition_recipe_four_pairs_restart_and_phase_closure(journey, migrated_database, monkeypatch):
    config, runtimes, script, temporary, real = journey
    script.write_text(json.dumps({'definition': answer(drafts())}))
    parent = temporary / 'chosen'
    parent.mkdir()
    root = parent / 'child'
    creation_body = definition_body = preparation_body = None
    records = []
    # A fresh lifespan after preparation and after each task reloads the same registry/receipts/history.
    for stage in range(5):
        with client(migrated_database[0], temporary, config) as http:
            runtime = runtimes[-1]
            worker = LocalSupervisor(runtime.repository, config.ports_factory, commit_factory=config.commit_factory)
            def run(job):
                assert worker.run_once().status == 'DONE'
                record = runtime.repository.get_run(job['run_id'])
                assert record.status in ('COMMITTED', 'ACCEPTANCE_READY', 'READY', 'COMPLETED'), record.history.stop
                return record
            if stage == 0:
                selected = {'action': 'select', 'expected_version': 0, 'path': str(parent)}
                preview = post(http, ROOT + '/preview', selected)
                root_body = {'change': selected, 'preview_sha256': preview['preview_sha256'], 'confirm_path': str(parent)}
                post(http, ROOT + '/apply', root_body, 'root')
                change = {'project_id': 'child', 'directory_name': 'child', 'root_version': 1,
                          'composition': 'django', 'policy': POLICY, 'agent_selection': selection(*PAIRS[0]),
                          'work_language': 'en'}
                preview = post(http, CREATE + '/preview', change)
                creation_body = {'change': change, 'preview_sha256': preview['preview_sha256'], 'trust_root': str(root)}
                created = post(http, CREATE + '/confirm', creation_body, 'child')
                assert list(root.iterdir()) == []
                assert post(http, CREATE + '/confirm', creation_body, 'child') == created
                conversation = post(http, BASE + '/planning', {'kind': 'definition', 'title': 'Sintético',
                    'brief': '# Ensayo sintético\n\nSin proveedores reales.\n'}, 'definition', 201)['id']
                turn = post(http, BASE + f'/planning/{conversation}/messages',
                            {'expected_version': 0, 'text': 'Propón los documentos'}, 'turn', 202)
                assert worker.run_once().status == 'DONE'
                planning = BASE + f'/planning/{conversation}'
                detail = http.get(planning).json()
                assert detail['turns'][-1]['status'] == 'ANSWERED', detail
                for proposal in detail['proposals']:
                    post(http, planning + f"/proposals/{proposal['id']}/apply", {
                        'expected_version': http.get(planning).json()['version'],
                        'proposal_sha256': proposal['proposal_sha256'], 'confirmed': True})
                preview = post(http, planning + '/accept/preview', {})
                assert preview['ready'], preview['blockers']
                definition_body = {'preview_sha256': preview['preview_sha256'], 'confirmed': True,
                    'reason': 'Synthetic exact definition', 'resume_operation_id': None, 'expected_version': None}
                definition = post(http, planning + '/accept', definition_body, 'accept', 202)
                run(definition)
                assert git(root, 'rev-list', '--count', 'HEAD') == '1'
                phase_id = http.get(BASE + '/bootstrap').json()['definition_operation']['phase_id']
                preparation_change = {'expected_version': 1, 'mode': 'offline'}
                preview = post(http, BASE + '/preparation/preview', preparation_change)
                assert not preview['network']['enabled']
                preparation_body = {'change': preparation_change, 'preview_sha256': preview['preview_sha256']}
                prepared = post(http, BASE + '/preparation/confirm', preparation_body, 'prepare')
                assert post(http, BASE + '/preparation/confirm', preparation_body, 'prepare') == prepared
                original = runtime.preparation._commit
                def lost_adoption(*args):
                    original(*args)
                    raise ValueError('Synthetic crash after technical commit, before receipt adoption')
                with monkeypatch.context() as fault:
                    fault.setattr(runtime.preparation, '_commit', lost_adoption)
                    assert runtime.preparation.run_once() == prepared['id']
                failed = runtime.preparation.repository.read(prepared['id'])
                assert failed['status'] == 'FAILED', failed['diagnostic']
                technical_head = git(root, 'rev-parse', 'HEAD')
                def preparation_process_count():
                    with Session(runtime.engine) as session:
                        return session.scalar(select(func.count()).select_from(ManagedProcessRow).where(
                            ManagedProcessRow.preparation_id.is_not(None)))
                commands = preparation_process_count()
                # Restart classifies evidence; only a new confirmed intention may reconcile it.
                runtime.stop()
                runtime.start()
                assert runtime.preparation.run_once() is None
                assert not runtime.preparation.read('child')['prepared']
                recovery_change = {**preparation_change, 'previous_id': prepared['id'], 'retry_step': 17}
                preview = post(http, BASE + '/preparation/preview', recovery_change)
                recovery_body = {'change': recovery_change, 'preview_sha256': preview['preview_sha256']}
                recovered = post(http, BASE + '/preparation/confirm', recovery_body, 'reconcile')
                assert runtime.preparation.run_once() == recovered['id']
                assert git(root, 'rev-parse', 'HEAD') == technical_head
                assert preparation_process_count() == commands
                predecessor = runtime.preparation.repository.read(prepared['id'])
                assert predecessor['status'] == 'FAILED'
                assert predecessor['plan'] == failed['plan'] and predecessor['steps'] == failed['steps']
                assert predecessor['events'][:len(failed['events'])] == failed['events']
                preparation_body, prepared = recovery_body, recovered
                operation = runtime.preparation.repository.read(prepared['id'])
                assert operation['status'] == 'COMPLETED', (operation['diagnostic'], [
                    (step['number'], step['status'], step.get('evidence', {}).get('result'))
                    for step in operation['steps'] if step['status'] == 'STARTED'])
                receipt = operation['receipt']
                assert git(root, 'rev-list', '--count', 'HEAD') == '2'
                assert all(step['status'] == 'DONE' for step in operation['steps'])
                junit = [step['evidence']['junit'] for step in operation['steps'] if 'junit' in (step['evidence'] or {})]
                assert len(junit) == 1 and junit[0]['status'] == 'complete'
            else:
                assert post(http, CREATE + '/confirm', creation_body, 'child') == created
                if stage == 1:
                    assert post(http, planning + '/accept', definition_body, 'accept', 202)['id'] == definition['id']
                    assert post(http, BASE + '/preparation/confirm', preparation_body, 'reconcile')['id'] == prepared['id']
                assert runtime.preparation.run_once() is None and worker.run_once() is None
                assert runtime.preparation.read('child')['prepared']
                assert runtime.preparation.repository.read(prepared['id']) == operation
            assert runtime.project('child').versions['project_environment_sha256'] == digest(receipt)
            for previous in records:
                assert runtime.repository.get_run(previous.history.id) == previous
            if stage == 4:
                break
            if stage:
                change = {'action': 'update', 'project_id': 'child', 'expected_version': stage,
                          'composition': 'django', 'policy': POLICY, 'agent_selection': selection(*PAIRS[stage])}
                preview = post(http, '/api/managed/registry/preview', change)
                body = {'change': change, 'preview_sha256': preview['preview_sha256']}
                saved = post(http, '/api/managed/registry/apply', body, f'roles-{stage}')
                assert post(http, '/api/managed/registry/apply', body, f'roles-{stage}') == {**saved, 'replayed': True}
            task_id = f'P001-T00{stage + 1}'
            content = (root / 'templates/core/index.html').read_text().replace('</main>', f'<p>{task_id}</p></main>')
            edits, allowed = {'templates/core/index.html': content}, ['templates/']
            if PAIRS[stage] == ('codex', 'claude'):
                # P009-T019 (D133): like T009, the shell-less Claude executor leaves Python that `ruff format --check`
                # rejects; the profile formatter fixes it before validation, so the first review already accepts.
                edits[FORMATTED] = "VALUE = 'SYNTHETIC'\n"
                allowed.append('core/')
            script.write_text(json.dumps({
                'planner': {'task_id': task_id, 'phase_id': 'P001', 'title': 'Synthetic increment',
                    'objective': 'Preserve the Django scaffold', 'executor_prompt': 'Apply the synthetic increment',
                    'allowed_paths': allowed, 'forbidden_paths': [],
                    'acceptance_criteria': ['Synthetic behavior is present.'], 'validation_commands': [],
                    'executor_selection': {'model': 'synthetic-executor', 'effort': 'medium',
                                           'reason': f'Synthetic reviewer choice for {task_id}'}},
                'edits': edits, 'executor': {'result': f'Applied {task_id}'},
                'reviewer': {'task_id': task_id, 'verdict': 'ACCEPT', 'findings': [],
                             'blocking_questions': [], 'scope_grants': []}}))
            body = {'task_id': task_id, 'phase_id': 'P001', 'text': (root / 'docs/NEXT_STEPS.md').read_text()}
            job = post(http, BASE + '/runs', body, task_id, 202)
            accepted = run(job)
            assert accepted.status == 'ACCEPTANCE_READY'
            assert json.loads(accepted.history.task_json)['allowed_paths'] == [f'{p}**' for p in allowed]  # D129
            formatters = [p['spec'] for p in runtime.repository.command_processes(job['id'])
                          if p['spec']['authorization'] == 'formatter-paths']
            formatting = [json.loads(c.formatting_json) if c.formatting_json else None for c in accepted.history.cycles]
            if FORMATTED in edits:
                assert [spec['command']['argv'] for spec in formatters] == [['ruff', 'format', '--', FORMATTED]]
                assert formatting[0]['paths'] == [FORMATTED] and formatting[0]['result']['exit_code'] == 0
                assert (root / FORMATTED).read_text() == 'VALUE = "SYNTHETIC"\n'
                assert all(entry.result.passed for entry in accepted.history.cycles[0].validation.entries)
                instructions = json.loads(accepted.history.attempts[1].request.prompt_snapshot_json)
                assert '`ruff format --`' in instructions['parts'][0]['variables']['PROFILE_INSTRUCTIONS']
            else:  # Only HTML changed: nothing to format, no command and the cycle keeps its previous shape.
                assert formatters == [] and formatting == [None]
            attempts = accepted.history.attempts
            assert [a.request.role for a in attempts] == ['planner', 'executor', 'reviewer']
            assert attempts[1].request.selection.reason.endswith(task_id)
            assert (attempts[1].request.selection.model, attempts[1].request.selection.effort) == ('synthetic-executor', 'medium')
            specs = [p['spec'] for p in runtime.repository.processes(job['id']) if p['spec'].get('provider')]
            assert [p['provider'] for p in specs] == [PAIRS[stage][0], PAIRS[stage][1], PAIRS[stage][0]]
            assert all(p['cwd'] == str(root) for p in specs)
            for spec, attempt in zip(specs, attempts, strict=True):
                chosen = attempt.request.selection
                assert spec['requested'] == {'model': chosen.model, 'effort': chosen.effort, 'fresh_session': True}
                argv = spec['argv']
                assert argv[argv.index('--model') + 1] == chosen.model
                if spec['provider'] == 'codex':
                    assert f'model_reasoning_effort="{chosen.effort}"' in argv
                else:
                    assert argv[argv.index('--effort') + 1] == chosen.effort
            commit = post(http, f"/api/managed/runs/{job['run_id']}/actions", {
                'action': 'commit', 'expected_version': accepted.version}, f'commit-{task_id}', 202)
            committed = run(commit)
            assert committed.status == 'COMMITTED'
            records.append(committed)
            assert post(http, BASE + '/runs', body, task_id, 202)['id'] == job['id']
            assert worker.run_once() is None
            assert git(root, 'rev-list', '--count', 'HEAD') == str(3 + stage)
            assert git(root, 'status', '--porcelain') == ''
    # All four task histories are unchanged after changing roles and restarting.
    with client(migrated_database[0], temporary, config) as http:
        runtime = runtimes[-1]
        worker = LocalSupervisor(runtime.repository, config.ports_factory, commit_factory=config.commit_factory)
        for record in records:
            assert runtime.repository.get_run(record.history.id) == record
        script.write_text(json.dumps({'phase': {'phase_id': 'P001', 'verdict': 'READY',
            'summary': 'Four synthetic increments accepted', 'exit_criteria_results': [
                {'criterion': CRITERION, 'passed': True, 'evidence': 'Four exact accepted commits and profile checks'}],
            'required_actions': [], 'blocking_questions': []}}))
        phase_path = f'/api/managed/phases/{phase_id}'
        detail = http.get(phase_path).json()
        checked = post(http, phase_path + '/actions', {'action': 'check', 'expected_version': detail['version']}, 'check', 202)
        assert worker.run_once().status == 'DONE'
        detail = http.get(phase_path).json()
        assert detail['status'] == 'READY_TO_CLOSE', detail
        original_head = git(root, 'rev-parse', 'HEAD')
        state = (root / 'docs/STATE.md').read_bytes()
        next_steps = (root / 'docs/NEXT_STEPS.md').read_bytes()
        body = {'action': 'close', 'expected_version': detail['version'],
                'binding_sha256': detail['ready']['binding_sha256'], 'reason': 'Close synthetic P001', 'confirmed': True}
        closed = post(http, phase_path + '/actions', body, 'close', 202)
        assert worker.run_once().status == 'DONE'
        assert runtime.repository.get_run(closed['run_id']).status == 'COMMITTED'
        assert http.get(phase_path).json()['status'] == 'CLOSED'
        assert git(root, 'rev-parse', 'refs/tags/p001') == original_head
        assert git(root, 'rev-list', '--count', 'HEAD') == '7'
        assert (root / 'docs/archive/phase-001/STATE.md').read_bytes() == state
        assert (root / 'docs/archive/phase-001/NEXT_STEPS.md').read_bytes() == next_steps
        assert not list((root / 'docs/phase').glob('*'))
        assert post(http, phase_path + '/actions', body, 'close', 202)['id'] == closed['id']
        assert worker.run_once() is None
        assert git(root, 'status', '--porcelain') == ''
        assert not git(root, 'ls-files', '.venv', '.django-secret', 'reports', 'db.sqlite3', django.WORK)
        assert [item.name for item in parent.iterdir()] == ['child']
        assert len(runtime.creation.repository.operations()) == 1
        assert len(runtime.registry.repository.rows()) == 1
        assert len(runtime.registry.repository.history('child')) == 4
        assert all(json.loads(line)['cwd'] == str(root) for line in launches(temporary))
        assert len(launches(temporary)) == 14  # definition + 4 * (planner/executor/reviewer) + phase
