"""Retired surfaces and old-installation data, using synthetic SQLite/Git only."""
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.api.app import create_app
from my_harness.cli import main
from my_harness.core.engine.contracts import ContractError, freeze
from my_harness.core.engine.prompts import Template, builtin_catalog, digest, dump_catalog, load_catalog, render, validate
from my_harness.storage.backup import create_backup, restore_backup, verify_bundle
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict
from my_harness.storage.managed_mode import ModeGuard
from my_harness.storage.models import (
    LegacySourceRow, ManagedActivationRow, ManagedJobRow, ManagedRunRow, PlanningConversationRow,
    ProjectImportRow, PromptHeadRow, PromptVersionRow,
)
from my_harness.storage.prompts import PromptRepository
from test_managed_api import client, config, VERSIONS
from test_onboarding_conversation import world  # noqa: F401
from test_onboarding_commit import ready, preview, confirm

NOW = '2000-01-01T00:00:00+00:00'
REMOVED_PATHS = [
    ('GET', '/api/legacy/projects'), ('GET', '/api/legacy/updates'), ('GET', '/api/legacy/events'),
    ('PUT', '/api/legacy/projects/p/observation'), ('GET', '/api/legacy/projects/p/artifacts/a/content'),
    ('GET', '/api/managed/projects/synthetic/import'),
    ('GET', '/api/managed/projects/synthetic/migration/preview'),
    ('POST', '/api/managed/projects/synthetic/migration/activations'),
    ('GET', '/api/managed/activations/a'), ('POST', '/api/managed/activations/a/resume'),
    ('POST', '/api/managed/activations/a/abandon'), ('POST', '/api/managed/activations/a/revert'),
    ('POST', '/api/managed/activations/a/resume-revert'),
    ('GET', '/api/managed/projects/synthetic/planning/c/import'),
    ('POST', '/api/managed/projects/synthetic/planning/c/import/preview'),
    ('POST', '/api/managed/projects/synthetic/planning/c/import/confirm'),
]


def old_activation(engine, root, *, status='ACTIVE'):
    """Persist an old installation's sealed facts without any activation/import service."""
    root = Path(root)
    scope = root / '.harness/runs/synthetic'
    scope.mkdir(parents=True)
    raw = b'{"synthetic":true}\n'
    file = scope / 'task.json'
    file.write_bytes(raw)
    identifier = str(uuid4())
    snapshot = root.parent / ('sealed-' + identifier)
    target = snapshot / '.harness/runs/synthetic/task.json'
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    marker = freeze({'format': 'harness-local/managed-mode/1', 'activation_id': identifier,
                     'root': str(root), 'prepared_at': NOW}) + '\n'
    (root / '.harness/managed-mode.json').write_text(marker)
    manifest = freeze({'format': 'harness-local/migration-manifest/1', 'activation_id': identifier,
        'origin_root': str(root), 'snapshot_root': str(snapshot), 'runs': [{'path': '.harness/runs/synthetic'}],
        'artifacts': [{'path': '.harness/runs/synthetic/task.json', 'copied': True, 'sha256': digest(raw.decode()),
                       'size_bytes': len(raw), 'origin_mtime_ns': file.stat().st_mtime_ns}]})
    with Session(engine) as session, session.begin():
        session.add(ManagedActivationRow(id=identifier, root=str(root), repository_key=None, status=status,
            preview_sha256='0' * 64, legacy_stopped='Synthetic historical declaration', rules_json='{}',
            marker=marker, marker_sha256=digest(marker), snapshot_root=str(snapshot), manifest_json=manifest,
            manifest_sha256=digest(manifest), version=1, created_at=NOW))
        session.add(LegacySourceRow(root=str(root), observed_at=NOW, watch_enabled=True, diagnostic='unchanged'))
    return identifier, snapshot


def test_removed_api_and_conversation_kind_cannot_execute(world, tmp_path):
    with client(str(world.engine.url), tmp_path, config(world.context, supervisor=False)) as http:
        for method, path in REMOVED_PATHS:
            response = http.request(method, path, json={} if method != 'GET' else None)
            assert response.status_code == 404, (path, response.text)
        response = http.post('/api/managed/projects/synthetic/planning',
            json={'kind': 'project_import', 'title': 'Retired'}, headers={'Idempotency-Key': 'retired'})
        assert response.status_code == 422
        schema = http.app.openapi()
        assert not any('/legacy' in path or '/migration' in path or path.endswith('/import')
                       or '/import/' in path or '/activations' in path for path in schema['paths']
                       if not path.startswith('/api/managed/configuration/'))
        assert '/api/managed/configuration/import/preview' in schema['paths']
        assert not any(name.startswith(('Legacy', 'Activation', 'Migration', 'Observation'))
                       for name in schema['components']['schemas'])
    assert builtin_catalog().keys().isdisjoint({'import-project'})
    with pytest.raises(ValueError):
        world.planning.create(world.context, kind='project_import', title='Retired', writer=world.writer)
    with pytest.raises(LookupError):
        PromptRepository(world.engine).key(world.context, 'project', 'import-project')


@pytest.mark.parametrize('command', ['legacy-import', 'legacy-summary'])
def test_removed_cli_rejects_before_opening_any_database(command, tmp_path, monkeypatch):
    target = tmp_path / 'must-not-exist.sqlite3'
    monkeypatch.setenv('HARNESS_DATABASE_URL', f'sqlite:///{target}')
    with pytest.raises(SystemExit) as error:
        main([command, str(tmp_path)])
    assert error.value.code == 2 and not target.exists()


@pytest.mark.parametrize('status', ['PREPARING', 'REVERTING'])
def test_unfinished_activation_blocks_without_completing_or_reverting(world, status):
    identifier, _ = old_activation(world.engine, world.context.root, status=status)
    assert status in ModeGuard(world.engine).assess(world.context.root).refusal
    with pytest.raises(Conflict):
        world.repo.submit(world.context, 'P001-T001', 'P001', 'Synthetic task', VERSIONS, key='blocked')
    with Session(world.engine) as session:
        row = session.get(ManagedActivationRow, identifier)
        assert row.status == status and row.version == 1


@pytest.mark.parametrize('tamper', ['none', 'marker', 'snapshot', 'manifest', 'drift', 'new-run'])
def test_existing_activation_only_authorizes_intact_managed_work(world, tamper):
    root = world.context.root
    identifier, snapshot = old_activation(world.engine, root)
    if tamper == 'marker':
        (root / '.harness/managed-mode.json').write_text('{}')
    elif tamper == 'snapshot':
        (snapshot / '.harness/runs/synthetic/task.json').write_text('changed')
    elif tamper == 'manifest':
        with Session(world.engine) as session, session.begin():
            session.get(ManagedActivationRow, identifier).manifest_sha256 = '0' * 64
    elif tamper == 'drift':
        (root / '.harness/runs/synthetic/task.json').write_text('changed')
    elif tamper == 'new-run':
        (root / '.harness/runs/new').mkdir()
    assessment = ModeGuard(world.engine).assess(root)
    assert (assessment.refusal is None) == (tamper == 'none')
    with Session(world.engine) as session:
        assert session.get(LegacySourceRow, str(root)).watch_enabled


@pytest.mark.parametrize('variant', ['A', 'missing-source', 'wrong-flow', 'wrong-kind', 'invalid-inventory', 'wrong-action'])
def test_pending_retired_or_ambiguous_commit_is_quarantined_before_factories(world, monkeypatch, variant):
    cid = ready(world)
    shown = preview(world, cid)
    job = confirm(world, cid, shown)
    with Session(world.engine) as session, session.begin():
        row = session.get(PlanningConversationRow, cid)
        operation = session.scalar(select(ProjectImportRow))
        if variant == 'A':
            row.kind = 'project_import'
        elif variant == 'missing-source':
            row.source = None
        elif variant == 'wrong-kind':
            row.kind = 'definition'
        elif variant == 'invalid-inventory':
            row.source = {'inventory': []}
        elif variant == 'wrong-action':
            session.get(ManagedJobRow, job.id).request_json = freeze({'action': 'planning_turn'})
        else:
            operation.preview = {**operation.preview, 'flow': None}
        original = operation.intent, operation.preview, operation.status, row.source, row.kind
    def forbidden(*args):
        pytest.fail('Retired/ambiguous jobs must not construct ports, writers or agents')
    world.worker.ports_factory = forbidden
    world.worker.commit_factory = forbidden
    assert world.worker.run_once().status == 'RECOVERY_REQUIRED'
    state = world.repo.get_run(job.run_id)
    with pytest.raises(Conflict):
        world.repo.confirm_stopped(job.id, owner_token='wrong', expected_version=state.version, reason='Synthetic')
    world.repo.confirm_stopped(job.id, owner_token=world.repo.get_job(job.id).owner_token,
        expected_version=state.version, reason='Synthetic stopped owner')
    with pytest.raises(Conflict):
        world.repo.resume(job.run_id, key='cannot-resume', expected_version=world.repo.get_run(job.run_id).version)
    with Session(world.engine) as session:
        operation = session.scalar(select(ProjectImportRow))
        row = session.get(PlanningConversationRow, cid)
        assert (operation.intent, operation.preview, operation.status, row.source, row.kind) == original
    assert any(e['kind'] == 'retired_work_resolved' for e in world.repo.events(job.run_id))


def test_old_watch_setting_and_artifacts_survive_startup_backup_restore_without_observers(world, tmp_path, monkeypatch):
    root = world.context.root
    identifier, snapshot = old_activation(world.engine, root)
    # Startup must never walk an external watched root, including a root that has disappeared.
    shutil.rmtree(root)
    with client(str(world.engine.url), tmp_path, config(world.context, supervisor=False)) as http:
        assert http.get('/api/legacy/projects').status_code == 404
        assert http.get('/api/managed/supervisor').status_code == 200
    with Session(world.engine) as session:
        assert session.get(LegacySourceRow, str(root)).watch_enabled
        assert session.get(LegacySourceRow, str(root)).diagnostic == 'unchanged'
    bundle, restored = tmp_path / 'backup', tmp_path / 'restored'
    create_backup(world.engine.url.database, bundle, artifact_roots=[snapshot], writers_stopped=True)
    manifest = verify_bundle(bundle)
    assert any(item['sha256'] for item in manifest['files'])
    restore_backup(bundle, restored)
    shutil.rmtree(snapshot)
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'must_never_load:factory')
    with client(f'sqlite:///{restored / "state.sqlite3"}', tmp_path, None) as http:
        assert http.get('/api/managed/supervisor').json()['enabled'] is False
        assert http.get('/api/legacy/events').status_code == 404
    engine = make_engine(f'sqlite:///{restored / "state.sqlite3"}')
    try:
        with Session(engine) as session:
            assert session.get(LegacySourceRow, str(root)).watch_enabled
            assert session.get(ManagedActivationRow, identifier).status == 'ACTIVE'
    finally:
        engine.dispose()
    verify_bundle(restored)


def test_frozen_catalog_reads_retired_template_but_never_renders_it():
    catalog = builtin_catalog()
    text = 'Historical {{CONTEXT_JSON}} {{MESSAGE}}'
    template = Template('import-project', 'historical', 'core', 'core', text, digest(text), 'historical')
    catalog[template.name] = template
    encoded = dump_catalog(catalog)
    assert dump_catalog(load_catalog(encoded)) == encoded
    with pytest.raises(ContractError, match='removed'):
        render(template, {'CONTEXT_JSON': '{}', 'MESSAGE': 'Do not invoke'})


def test_expired_retired_turn_needs_explicit_recovery_without_reinvocation(world):
    cid = world.create()
    job = world.message(cid)
    claim = world.repo.claim()
    with Session(world.engine) as session, session.begin():
        session.get(PlanningConversationRow, cid).kind = 'project_import'
        session.get(ManagedRunRow, job.run_id).purpose = 'project_import'
        session.get(ManagedJobRow, job.id).lease_until = NOW
    assert world.worker.run_once() is None
    assert world.repo.get_job(job.id).status == 'RECOVERY_REQUIRED'
    version = world.repo.get_run(job.run_id).version
    world.repo.confirm_stopped(job.id, owner_token=claim.owner_token, expected_version=version,
                              reason='Synthetic stopped writer')
    assert world.repo.get_job(job.id).status == 'INTERRUPTED'
    assert not world.ports.agents.requests
    with pytest.raises(Conflict, match='removed'):
        world.planning.submit_message(world.context, cid, 1, key='retired-turn', versions=VERSIONS,
                                      text='Never invoke', writer=world.writer)
    with Session(world.engine) as session:
        assert session.get(PlanningConversationRow, cid).kind == 'project_import'


def test_old_active_prompt_head_is_inert(world):
    text = 'Historical {{CONTEXT_JSON}} {{MESSAGE}}'
    with Session(world.engine) as session, session.begin():
        session.add(PromptHeadRow(scope='core', owner='core', name='import-project', generation=1,
                                  active_id='old-import-template'))
        session.add(PromptVersionRow(id='old-import-template', scope='core', owner='core', name='import-project',
                                     template=text, sha256=digest(text), source='historical', created_at=NOW))
    assert 'import-project' not in PromptRepository(world.engine).catalog(world.context)
    with pytest.raises(ContractError, match='removed'):
        validate('import-project', text)
    with Session(world.engine) as session:
        assert session.get(PromptHeadRow, ('core', 'core', 'import-project')).active_id == 'old-import-template'


def test_retained_artifact_directory_remains_canonical_and_protected(world, tmp_path, monkeypatch):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
    from session_client import TestClient
    monkeypatch.chdir(world.context.root)
    managed = ManagedConfig((ManagedProject('synthetic', world.context, VERSIONS),),
                            migrations_dir=Path('old-artifacts'))
    with pytest.raises(ValueError, match='outside the checkout'):
        with TestClient(create_app(str(world.engine.url), tmp_path / 'ui', managed=managed)):
            pass
    assert not (world.context.root / 'old-artifacts').exists()
