"""D119: temporary synthetic Django toolchain, real bounded process transport/Git/SQLite; no packages installed."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

from alembic import command
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.adapters.preparation import PreparationCommandRunner, verify_receipt
from my_harness.core.engine.journal import JournalError
from my_harness.recipes import django
from my_harness.services.local_config import load_local_config, LocalConfigError
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict
from my_harness.storage.models import (ProjectPreparationOperationRow as Operation, ProjectPreparationStepRow as Step,
                                         ManagedProcessRow as Process, CheckoutLockRow as Lock)
from conftest import clear_accounting
from test_definition import World, ready, DRAFTS
import test_definition
from test_project_creation import select_root, request
from test_project_registry import POLICY, v3, operator  # noqa: F401
from test_local_config import setup, web, write, launches  # noqa: F401
from test_managed_api import Ports, client, git


def recipe_data(data, folder):
    data = v3(data, [], bootstrap=True)
    data['format'] = 'local-config-5'
    for role in ('reviewer', 'executor'):
        data['agents'][role]['environment']['PYTHONDONTWRITEBYTECODE'] = '1'
    source = Path(__file__).with_name('preparation_probe.py').read_text()
    for name in ('synthetic-python', 'synthetic-uv'):
        tool = folder / name
        tool.write_text('#!' + sys.executable + '\n' + source)
        tool.chmod(0o700)
    data['recipes'] = {'django': {'python_executable':str(folder / 'synthetic-python'),
        'python_version':'3.13.1', 'installer_executable':str(folder / 'synthetic-uv'),
        'installer_version':'0.9.5', 'timeout_seconds':120, 'max_output_bytes':65536, 'allow_network':False}}
    data['compositions']['django'] = {'profile':'python-django-recipe', 'recipe':'django',
        'executables':{name:{'project_venv':name} for name in ('python','pytest','ruff','mypy')},
        'environment':{}, 'authorize_profile_commands':True}
    return data


@pytest.fixture
def preparation(operator, migrated_database, monkeypatch):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, recipe_data(data, folder)))
    engine = make_engine(migrated_database[0])
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    parent = tmp_path / 'chosen'
    parent.mkdir()
    select_root(runtime.creation, parent)
    runtime.creation.confirm(request(runtime.creation, composition='django'), 'child')
    project = runtime.project('child')
    assert not (project.context.root / '.venv').exists()
    ports = Ports()
    writer = config.commit_factory(project.context, project.versions)
    worker = LocalSupervisor(runtime.repository, lambda c,v:(ports.agents,ports.runner,ports._workspace(c)), commit_factory=lambda c,v:writer)
    world = World(project.context, runtime.repository, writer, worker, ports)
    monkeypatch.setattr(test_definition, 'VERSIONS', dict(project.versions))
    drafts = dict(DRAFTS)
    drafts['docs/NEXT_STEPS.md'] = drafts['docs/NEXT_STEPS.md'].replace('`test-runner check`', '`pytest --junitxml=reports/pytest.xml`')
    monkeypatch.setattr(test_definition, 'DRAFTS', drafts)
    cid = ready(world)
    job = world.accept(cid)
    assert worker.run_once().status == 'DONE'
    service = runtime.preparation
    original = service._files
    def files(root, plan):
        original(root, plan)
        # Toolchain fixture metadata, not product data or an actual dependency installation.
        (root / django.WORK / 'packages.json').write_text(json.dumps(django.PACKAGES))
    monkeypatch.setattr(service, '_files', files)
    yield service, config, migrated_database, folder
    runtime.stop()
    engine.dispose()
    assert not launches(tmp_path)


def shown(service, **extra):
    return service.preview('child', {'expected_version':1, 'mode':'offline', **extra})


def confirm(service, key='prepare', preview=None, **extra):
    change = {'expected_version':1, 'mode':'offline', **extra}
    preview = preview or service.preview('child', change)
    return service.confirm('child', {'change':change,'preview_sha256':preview['preview_sha256']}, key)


def root(service):
    return service.runtime.project('child').context.root


def complete(service):
    op = confirm(service)
    assert service.run_once() == op['id']
    result = service.repository.read(op['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    return result


def test_deferred_composition_root_definition_and_exact_plan_without_tools(preparation):
    service, config, *_ = preparation
    project = service.runtime.project('child')
    assert project.versions['project_recipe'] == django.VERSION
    assert 'project_environment_sha256' not in project.versions
    before = sorted(root(service).rglob('*'))
    preview = shown(service)
    assert preview == shown(service) and sorted(root(service).rglob('*')) == before
    assert preview['files'] and preview['templates'] and preview['steps']
    install = next(s for s in preview['steps'] if 'Instalar' in s['label'])
    assert '--offline' in install['argv'] and '--require-hashes' in install['argv'] and '--no-deps' in install['argv']
    assert preview['network']['enabled'] is False
    with pytest.raises(Conflict, match='preparation_required'):
        service.managed.submit(project.context, 'P001-T001','P001','synthetic',key='task',versions=dict(project.versions))
    with pytest.raises(RegistryError) as error:
        shown(service, mode='network')
    assert error.value.code == 'network_not_allowed'
    assert not (root(service) / django.WORK).exists()


def test_technical_commit_and_receipt_replay_restart_protection_and_process_ownership(preparation):
    service, config, database, folder = preparation
    document_head = git(root(service),'rev-parse','HEAD')
    request_preview = shown(service)
    queued = confirm(service, preview=request_preview)
    assert not (root(service) / '.venv').exists()
    assert confirm(service, preview=request_preview) == queued
    assert service.runtime.registry.repository.unfinished(str(root(service))) == []
    assert service.runtime.registry.repository.configuration_blockers(str(root(service))) == ['Unresolved preparation: ' + queued['id']]
    service.run_once()
    op = service.repository.read(queued['id'])
    assert op['status'] == 'COMPLETED', op['diagnostic']
    assert all(step['status'] == 'DONE' for step in op['steps'])
    assert op['receipt']['commit'] == git(root(service),'rev-parse','HEAD') != document_head
    assert git(root(service), 'rev-parse', 'HEAD^') == document_head
    assert git(root(service),'status','--porcelain') == ''
    assert not git(root(service),'ls-files','.django-secret','.venv','reports','db.sqlite3',django.WORK)
    assert 'class Task' not in (root(service)/'core/models.py').read_text()
    verify_receipt(root(service), op['receipt'])
    assert service.runtime.preparation.read('child')['prepared']
    assert service.runtime.project('child').versions['project_environment_sha256'] == digest(op['receipt'])
    with Session(service.runtime.engine) as session:
        processes = list(session.scalars(select(Process).where(Process.preparation_id == op['id'])))
        assert len(processes) == sum(s['spec']['kind']=='command' for s in op['steps'])
        assert all(p.job_id is None and p.attempt_id is None and p.status == 'STOPPED' for p in processes)
        assert not session.get(Lock,str(root(service)))
    engine = make_engine(database[0])
    restarted = ManagedRuntime(engine, config)
    restarted.start()
    try:
        assert restarted.preparation.read('child')['prepared']
        assert restarted.project('child').versions['project_environment_sha256'] == digest(op['receipt'])
        assert restarted.preparation.run_once() is None
    finally:
        restarted.stop(); engine.dispose()
    (root(service)/'config/settings.py').write_text('foreign')
    with pytest.raises(JournalError, match='preparation_required'):
        verify_receipt(root(service), op['receipt'])
    assert not service.read('child')['prepared']


@pytest.mark.parametrize('path', ['.venv', '.harness-preparation', '.django-secret', 'manage.py', 'pyproject.toml'])
def test_existing_paths_or_symlinks_never_adopted(preparation, path):
    service, *_ = preparation
    target = root(service)/path
    target.symlink_to(root(service)/'missing')
    with pytest.raises((RegistryError, ValueError)):
        shown(service)
    assert target.is_symlink()


def test_preview_cas_drift_and_idempotency(preparation):
    service, *_ = preparation
    preview=shown(service)
    (root(service)/'foreign.txt').write_text('foreign')
    with pytest.raises(RegistryError):
        confirm(service, preview=preview)
    (root(service)/'foreign.txt').unlink()
    first=confirm(service, preview=preview)
    with pytest.raises(RegistryError) as error:
        service.confirm('child',{'change':{'expected_version':1,'mode':'offline'},'preview_sha256':'0'*64},'prepare')
    assert error.value.code=='idempotency_conflict'
    with pytest.raises(RegistryError):
        confirm(service,key='another',preview=preview)
    assert service.repository.read(first['id'])['status']=='QUEUED'


def test_failure_never_retries_install_and_successor_requires_explicit_step(preparation, monkeypatch):
    service, *_ = preparation
    original=service._command
    fail = True
    def command(root, plan, step, journal):
        nonlocal fail
        if step['number']==4 and fail:
            fail=False
            raise ValueError('Synthetic installation failure, no network')
        return original(root,plan,step,journal)
    monkeypatch.setattr(service,'_command',command)
    op=confirm(service)
    service.run_once()
    failed=service.repository.read(op['id'])
    assert failed['status']=='FAILED' and failed['steps'][4]['status']=='STARTED'
    assert service.run_once() is None
    with pytest.raises(RegistryError):
        shown(service, previous_id=op['id'], retry_step=5)
    successor=confirm(service,key='explicit-retry',previous_id=op['id'],retry_step=4)
    assert successor['previous_id']==op['id']
    service.run_once()
    result=service.repository.read(successor['id'])
    assert result['status']=='COMPLETED',result['diagnostic']
    assert service.repository.read(op['id'])['steps'][4]['status']=='STARTED'
    # No second environment creation; completed prefix copied with its evidence.
    calls=[json.loads(line) for line in (root(service)/django.WORK/'probe.jsonl').read_text().splitlines()]
    assert sum('-m' in argv and 'venv' in argv for _,argv in calls)==1


def test_cancel_queued_and_lease_expiry_do_not_start_tools(preparation):
    service,*_=preparation
    op=confirm(service)
    service.control(op['id'],{'expected_version':op['version'],'plan_sha256':op['plan_sha256']},'cancel')
    assert service.run_once() is None
    assert not (root(service)/'.venv').exists()


def test_lost_owner_quarantines_and_requires_dead_process_before_unlock(preparation):
    service,*_=preparation
    op=confirm(service)
    claim=service.repository.claim(30)
    with service.managed._write() as session:
        row=session.get(Operation,op['id'])
        row.lease_until=(service.managed.clock()-timedelta(seconds=1)).isoformat()
    assert service.repository.claim(30) is None
    row=service.repository.read(op['id'])
    assert row['status']=='RECOVERY_REQUIRED'
    with pytest.raises(Conflict,match='owner'):
        service.control(op['id'],{'expected_version':row['version'],'plan_sha256':row['plan_sha256']},'confirm-stopped')
    assert not (root(service)/'.venv').exists()


def test_commit_adoption_crash_reconciles_same_commit_without_replaying_commands(preparation, monkeypatch):
    service,*_=preparation
    original=service._commit
    def crash(*args):
        original(*args)
        raise ValueError('Synthetic lost SQLite adoption after commit')
    monkeypatch.setattr(service,'_commit',crash)
    op=confirm(service)
    service.run_once()
    failed=service.repository.read(op['id'])
    assert failed['status']=='FAILED'
    head=git(root(service),'rev-parse','HEAD')
    count=(root(service)/django.WORK/'probe.jsonl').read_text()
    next_step=next(s['number'] for s in failed['steps'] if s['status']!='DONE')
    monkeypatch.setattr(service,'_commit',original)
    successor=confirm(service,key='commit-reconcile',previous_id=op['id'],retry_step=next_step)
    service.run_once()
    result=service.repository.read(successor['id'])
    assert result['status']=='COMPLETED',result['diagnostic']
    assert git(root(service),'rev-parse','HEAD')==head
    assert (root(service)/django.WORK/'probe.jsonl').read_text()==count


def test_preparation_api_security_strict_payload_and_idempotent_confirmation(preparation):
    service,config,database,*_=preparation
    with client(database[0], service.runtime.database.parent, config) as http:
        base='/api/managed/projects/child/preparation'
        body={'expected_version':1,'mode':'offline'}
        assert http.post(base+'/preview',json={**body,'argv':['arbitrary']}).status_code==422
        assert http.post(base+'/preview',json=body,headers={'Origin':'https://foreign.invalid'}).status_code==403
        preview=http.post(base+'/preview',json=body)
        assert preview.status_code==200,preview.text
        request={'change':body,'preview_sha256':preview.json()['preview_sha256']}
        assert http.post(base+'/confirm',json=request).status_code==422
        first=http.post(base+'/confirm',json=request,headers={'Idempotency-Key':'api-confirm'})
        assert first.status_code==200,first.text
        assert http.post(base+'/confirm',json=request,headers={'Idempotency-Key':'api-confirm'}).json()==first.json()
        assert http.get('/api/managed/preparations/'+first.json()['id']).status_code==200


def test_live_cancellation_stops_own_process_group_before_releasing_lock(preparation, monkeypatch):
    import time
    service, *_ = preparation
    original = service._files
    def files(root, plan):
        original(root, plan)
        (root / django.WORK / 'pause').write_text('synthetic pause')
    monkeypatch.setattr(service, '_files', files)
    op = confirm(service)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(service.run_once)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = service.repository.read(op['id'])
            if any(s['number'] == 4 and s['status'] == 'STARTED' for s in current['steps']):
                with Session(service.runtime.engine) as session:
                    process = session.get(Process, current['steps'][4]['id'])
                    if process and process.identity:
                        break
            time.sleep(.02)
        else:
            pytest.fail('Synthetic process never started')
        current = service.repository.read(op['id'])  # include the spawn event observed in the separate process query
        service.control(op['id'], {'expected_version':current['version'], 'plan_sha256':current['plan_sha256']}, 'cancel')
        assert future.result(timeout=10) == op['id']
    result = service.repository.read(op['id'])
    assert result['status'] == 'CANCELLED' and result['owner_closed']
    with Session(service.runtime.engine) as session:
        process = session.get(Process, result['steps'][4]['id'])
        assert process.capture['group_state'] == 'dead'
        assert not session.get(Lock, str(root(service)))
    assert service.run_once() is None


def test_tool_drift_after_confirmation_blocks_before_any_recipe_write(preparation):
    service, config, _, folder = preparation
    op = confirm(service)
    tool = folder / 'synthetic-uv'
    tool.write_text(tool.read_text()+'\n# changed bytes\n')
    service.run_once()
    assert service.repository.read(op['id'])['status'] == 'FAILED'
    assert not (root(service)/django.WORK).exists()


def test_foreign_source_and_environment_drift_cannot_become_recovery_authority(preparation, monkeypatch):
    service, *_ = preparation
    original = service._command
    def fail(root,plan,step,journal):
        if step['number'] == 5:
            raise ValueError('Synthetic failure after installation')
        return original(root,plan,step,journal)
    monkeypatch.setattr(service,'_command',fail)
    op=confirm(service)
    service.run_once()
    assert service.repository.read(op['id'])['status']=='FAILED'
    (root(service)/'django.py').write_text('foreign code')
    with pytest.raises(ValueError,match='Foreign'):
        shown(service,previous_id=op['id'],retry_step=5)
    (root(service)/'django.py').unlink()
    (root(service)/'.venv/bin/ruff').write_text('foreign environment bytes')
    with pytest.raises(RegistryError,match='environment'):
        shown(service,previous_id=op['id'],retry_step=5)


def test_migration_preserves_prior_job_process_and_exclusive_owner_constraints(preparation):
    from sqlalchemy.exc import IntegrityError
    service, config, database, folder = preparation
    with service.managed._write() as session:
        attempt=session.execute(text('SELECT id,run_id FROM managed_attempts LIMIT 1')).one()
        job=session.execute(text('SELECT id FROM managed_jobs WHERE run_id=:run'),{'run':attempt.run_id}).scalar()
        session.add(Process(attempt_id=attempt.id,job_id=job,spec={'synthetic':True},status='STOPPED'))
        session.add(Lock(root='/synthetic-prior-lock',job_id=job))
        # 0025 refuses to drop a confirmed work language (D167); this test is about the 0021 constraints.
        session.execute(text('DELETE FROM project_work_languages'))
    clear_accounting(database[0])  # 0028 likewise refuses to drop accounting records
    command.downgrade(database[1],'0021_project_creation')
    command.upgrade(database[1],'head')
    with Session(service.runtime.engine) as session:
        process=session.get(Process,attempt.id)
        assert process.attempt_id==attempt.id and process.job_id==job and process.preparation_id is None
        assert session.get(Lock,'/synthetic-prior-lock').job_id==job
        assert session.scalar(text('PRAGMA foreign_key_check')) is None
    for values in ({'root':'/invalid-owner'}, {'root':'/invalid-owner','job_id':job,'preparation_id':'missing'}):
        with pytest.raises(IntegrityError), service.managed._write() as session:
            session.add(Lock(**values))
            session.flush()
    command.check(database[1])


@pytest.mark.parametrize('change', ['wrong-tool','absolute-link','v4','unknown-recipe','no-recipe','shell','unfixed-python'])
def test_recipe_configuration_rejects_untyped_or_unavailable_authority(operator, change):
    _, data, folder, _ = operator
    raw=recipe_data(data,folder)
    if change=='wrong-tool': raw['compositions']['django']['executables']['python']={'project_venv':'ruff'}
    elif change=='absolute-link': raw['compositions']['django']['executables']['python']={'project_venv':'/tmp/python'}
    elif change=='v4': raw['format']='local-config-4'
    elif change=='unknown-recipe': raw['compositions']['django']['recipe']='arbitrary'
    elif change=='no-recipe': del raw['compositions']['django']['recipe']
    elif change=='shell': raw['recipes']['django']['arbitrary_shell']='anything'
    else: raw['recipes']['django']['python_version']='3.13'
    with pytest.raises(LocalConfigError):
        load_local_config(write(folder,raw))


def test_cancel_replay_and_new_intention_before_effects(preparation):
    service,*_=preparation
    op=confirm(service)
    control={'expected_version':op['version'],'plan_sha256':op['plan_sha256']}
    cancelled=service.control(op['id'],control,'cancel','cancel-key')
    assert service.control(op['id'],control,'cancel','cancel-key')==cancelled
    with pytest.raises(RegistryError,match='key'):
        service.control(op['id'],{**control,'reason':'different'},'cancel','cancel-key')
    new=confirm(service,key='new-after-cancel',previous_id=op['id'],retry_step=0)
    service.run_once()
    result=service.repository.read(new['id'])
    assert result['status']=='COMPLETED',result['diagnostic']


def test_completed_steps_without_adoption_reconcile_only_the_technical_commit(preparation, monkeypatch):
    service,*_=preparation
    op=complete(service)
    # Model a crash after the commit step checkpoint but before adopting the receipt.
    with service.managed._write() as session:
        row=session.get(Operation,op['id'])
        row.status,row.reserved,row.receipt='RECOVERY_REQUIRED',True,None
    service.runtime.registry.registrar._receipts.clear()
    service.runtime.registry.load()
    before=(root(service)/django.WORK/'probe.jsonl').read_text()
    new=confirm(service,key='lost-adoption',previous_id=op['id'],retry_step=len(op['steps'])-1)
    service.run_once()
    result=service.repository.read(new['id'])
    assert result['status']=='COMPLETED',result['diagnostic']
    assert result['receipt']['commit']==op['receipt']['commit']
    assert (root(service)/django.WORK/'probe.jsonl').read_text()==before


def test_preparation_backup_restores_journal_in_query_mode_without_new_authority(preparation, tmp_path):
    from my_harness.storage.backup import create_backup, restore_backup, is_read_only_archive
    service, config, database, folder = preparation
    op=complete(service)
    bundle=tmp_path/'backup'
    create_backup(service.runtime.database,bundle,writers_stopped=True)
    restore_backup(bundle,tmp_path/'restored')
    engine=make_engine('sqlite:///'+str(tmp_path/'restored/state.sqlite3'))
    restored=ManagedRuntime(engine,config)
    restored.start()
    try:
        assert is_read_only_archive(engine)
        assert restored.projects=={}
        assert restored.preparation.repository.read(op['id'])==service.repository.read(op['id'])
    finally:
        restored.stop(); engine.dispose()


def test_changed_generated_bytes_stop_without_a_technical_commit(preparation, monkeypatch):
    service,*_=preparation
    original=service._command
    initial=git(root(service),'rev-parse','HEAD')
    def drift(root,plan,step,journal):
        result=original(root,plan,step,journal)
        if step['number']==8:
            (root/django.WORK/'output/core/views.py').write_text('foreign generated bytes')
        return result
    monkeypatch.setattr(service,'_command',drift)
    op=confirm(service)
    service.run_once()
    assert service.repository.read(op['id'])['status']=='FAILED'
    assert not (root(service)/'manage.py').exists()
    assert git(root(service),'rev-parse','HEAD')==initial


def test_successful_environment_receipt_is_required_before_native_commands(preparation):
    service,config,*_=preparation
    project=service.runtime.project('child')
    runner=config.ports_factory(project.context,project.versions)[1]
    with pytest.raises(JournalError,match='preparation_required'):
        runner.run_managed(project.context,project.context.profile.validations[0],'no-command')
    op=complete(service)
    (root(service)/'.venv/bin/ruff').write_text('changed binary')
    with pytest.raises(JournalError,match='preparation_required'):
        verify_receipt(root(service),op['receipt'])
    project=service.runtime.project('child')
    with pytest.raises(JournalError,match='preparation_required'):
        service.managed.submit(project.context,'P001-T001','P001','synthetic',key='after-drift',versions=dict(project.versions))


def test_receipt_survives_a_remount_that_renumbers_the_device_but_not_another_directory(preparation, monkeypatch):
    """P009-T018 (D130): after a reboot macOS gave the pilot's volume another st_dev with the same inodes and bytes."""
    service,*_=preparation
    op=complete(service)
    import my_harness.adapters.preparation as adapter
    original=adapter.identity
    monkeypatch.setattr(adapter,'identity',lambda info: {**original(info),'device':info.st_dev+3})
    verify_receipt(root(service),op['receipt'])
    assert service.runtime.preparation.read('child')['prepared']
    project=service.runtime.project('child')
    assert service.managed.submit(project.context,'P001-T001','P001','synthetic',key='after-remount',
                                  versions=dict(project.versions)).status=='QUEUED'
    for field in ('identity','environment'):
        moved=json.loads(json.dumps(op['receipt']))
        target=moved[field] if field=='identity' else moved[field]['identity']
        target['inode']+=1  # Another directory at the same path, with identical bytes.
        with pytest.raises(JournalError,match='preparation_required'):
            verify_receipt(root(service),moved)
    (root(service)/'.venv/bin/ruff').write_text('changed binary')
    with pytest.raises(JournalError,match='preparation_required'):
        verify_receipt(root(service),op['receipt'])


def test_failure_in_success_exit_junit_never_adopts_environment(preparation, monkeypatch):
    service,*_=preparation
    original=service._files
    def files(root,plan):
        original(root,plan)
        (root/django.WORK/'bad-junit').write_text('synthetic failure marker')
    monkeypatch.setattr(service,'_files',files)
    initial=git(root(service),'rev-parse','HEAD')
    op=confirm(service)
    service.run_once()
    failed=service.repository.read(op['id'])
    assert failed['status']=='FAILED' and 'JUnit' in failed['diagnostic']
    assert failed['receipt'] is None
    assert git(root(service),'rev-parse','HEAD')==initial


def test_registry_projects_and_preview_preserve_integer_jobs_during_preparation(preparation):
    service,config,database,*_=preparation
    op=confirm(service)
    with client(database[0],service.runtime.database.parent,config) as http:
        record=http.get('/api/managed/registry/projects/child')
        assert record.status_code==200,record.text
        assert record.json()['unfinished_jobs']==[]
        assert record.json()['configuration_blockers']==['Unresolved preparation: '+op['id']]
        body={'action':'update','project_id':'child','expected_version':1,'composition':'django',
              'policy':POLICY,'bootstrap_enabled':True}
        preview=http.post('/api/managed/registry/preview',json=body)
        assert preview.status_code==200,preview.text
        assert preview.json()['configuration_blockers']==['Unresolved preparation: '+op['id']]
        response=http.post('/api/managed/registry/apply',json={'change':body,'preview_sha256':preview.json()['preview_sha256']})
        assert response.status_code==409,response.text


def test_file_effects_check_the_authorized_root_inode_on_the_open_fd(tmp_path):
    from my_harness.adapters.preparation import write_new
    with pytest.raises(ValueError, match='identity'):
        write_new(tmp_path,'nested/target.txt',b'synthetic',expected_identity={'device':-1,'inode':-1})
    assert list(tmp_path.iterdir())==[]


def test_uv_cache_links_are_internal_evidence_and_cannot_escape_the_cache(tmp_path):
    from my_harness.services.project_preparation import snapshot
    cache=tmp_path/django.WORK/'cache'
    (cache/'archive').mkdir(parents=True)
    (cache/'archive/wheel.txt').write_text('synthetic wheel cache')
    (cache/'wheel-link').symlink_to('archive',target_is_directory=True)
    observed=snapshot(tmp_path)
    assert observed[django.WORK+'/cache/wheel-link']['link']=='archive'
    assert observed[django.WORK+'/cache/archive/wheel.txt']['sha256']
    (tmp_path/'foreign.txt').write_text('synthetic outside cache')
    (cache/'escape').symlink_to(tmp_path/'foreign.txt')
    with pytest.raises(ValueError,match='symlink'):
        snapshot(tmp_path)


def test_internal_uv_cache_links_do_not_prevent_preparation_or_environment_receipt(preparation, monkeypatch):
    service,*_=preparation
    original=service._command
    def install(root,plan,step,journal):
        result=original(root,plan,step,journal)
        if step['number']==4:
            cache=root/django.WORK/'cache'
            (cache/'archive').mkdir()
            (cache/'archive/wheel.txt').write_text('synthetic unpacked wheel')
            (cache/'wheel-link').symlink_to('archive',target_is_directory=True)
        return result
    monkeypatch.setattr(service,'_command',install)
    op=complete(service)
    assert op['receipt']


def test_recipe_requires_explicit_agent_bytecode_policy_without_rewriting_presets(operator):
    _,data,folder,tmp=operator
    raw=recipe_data(data,folder)
    del raw['agents']['executor']['environment']['PYTHONDONTWRITEBYTECODE']
    config=load_local_config(write(folder,raw))
    root=tmp/'new'
    root.mkdir()
    row={'id':'new','root':str(root),'repository_trusted':True,'composition':'django','policy':POLICY}
    with pytest.raises(LocalConfigError,match='PYTHONDONTWRITEBYTECODE'):
        config.registrar.compose(row,'synthetic')
    assert 'PYTHONDONTWRITEBYTECODE' not in dict(config.registrar.agents['executor'].environment)
    assert list(root.iterdir())==[]


def test_preparation_lease_uses_utc_even_with_an_aware_non_utc_clock(preparation):
    from datetime import datetime, timezone
    service,*_=preparation
    instant=datetime.now(timezone(timedelta(hours=2)))
    service.managed.clock=lambda:instant
    op=confirm(service)
    service.repository.claim(30)
    with Session(service.runtime.engine) as session:
        lease=datetime.fromisoformat(session.get(Operation,op['id']).lease_until)
        assert lease.utcoffset()==timedelta(0)
    service.managed.clock=lambda:instant+timedelta(seconds=31)
    service.repository.recover_expired()
    assert service.repository.read(op['id'])['status']=='RECOVERY_REQUIRED'
    assert not (root(service)/'.venv').exists()


def test_persisted_step_argv_cannot_override_the_confirmed_plan(preparation):
    service,*_=preparation
    op=confirm(service)
    with service.managed._write() as session:
        step=session.scalar(select(Step).where(Step.operation_id==op['id'],Step.number==4))
        step.spec={**step.spec,'argv':['/synthetic/unconfirmed-tool','foreign']}
    service.run_once()
    result=service.repository.read(op['id'])
    assert result['status']=='FAILED' and 'argv' in result['diagnostic']
    assert not (root(service)/django.WORK).exists()
    with Session(service.runtime.engine) as session:
        assert session.scalar(select(Process.id).where(Process.preparation_id==op['id'])) is None


@pytest.mark.parametrize('fmt',['local-config-4','local-config-5'])
def test_previous_declared_profile_name_remains_valid_without_recipe_opt_in(operator,fmt):
    context,data,folder,_=operator
    raw=v3(data,[])
    raw['format']=fmt
    raw['profiles']={'python-django-recipe':{
        'preparation':[], 'validations':[{'argv':['node','--version'],'timeout_seconds':20}],
        'allowed_command_prefixes':[['node','--version']], 'protected_paths':['package.json'],
        'sensitive_paths':['.env'], 'data_model_paths':[], 'executor_instructions':'Synthetic legacy profile'}}
    raw['compositions']['web']['profile']='python-django-recipe'
    config=load_local_config(write(folder,raw))
    project,_=config.registrar.compose({'id':'legacy','root':str(context.root),'repository_trusted':True,
                                       'composition':'web','policy':POLICY},'synthetic legacy')
    assert project.context.profile.executor_instructions=='Synthetic legacy profile'
    assert 'project_recipe' not in project.versions


def test_later_profile_preparation_does_not_replace_legacy_recipe_authority(preparation, tmp_path):
    """A staged T011 profile receipt cannot displace a still-active packaged recipe receipt."""
    from uuid import uuid4
    service, *_ = preparation
    completed = complete(service)
    project = service.runtime.project('child')
    with service.managed._write() as session:
        original = session.get(Operation, completed['id'])
        values = {column.name: getattr(original, column.name) for column in Operation.__table__.columns}
        values.update(id=str(uuid4()), idempotency_key='later-profile-receipt', reserved=False,
            created_at='2099-01-01T00:00:00+00:00', updated_at='2099-01-01T00:00:00+00:00',
            receipt={'contract': 'project-profile-preparation-1', 'operation_id': 'synthetic-new-profile'})
        session.add(Operation(**values))
    bound = service.bind(project)
    assert bound.versions['project_environment_sha256'] == digest(completed['receipt'])
    assert service.runtime.registry.registrar._receipts[project.context.root] == completed['receipt']
    # Preparation CLI evidence is included without turning either receipt into execution authority.
    from my_harness.storage.backup import create_backup, verify_bundle
    import hashlib
    import shutil
    artifacts = tmp_path / 'synthetic-preparation-cli'
    artifacts.mkdir()
    files = {'prompt.txt': b'Synthetic prompt', 'stdout.bin': b'Synthetic output', 'stderr.bin': b''}
    for name, raw in files.items():
        (artifacts / name).write_bytes(raw)
    with service.managed._write() as session:
        session.add(Process(id='synthetic-preparation-cli', preparation_id=completed['id'], status='STOPPED',
            spec={'artifacts': str(artifacts), 'prompt_path': str(artifacts / 'prompt.txt'),
                  'prompt_sha256': hashlib.sha256(files['prompt.txt']).hexdigest()},
            capture={'artifacts': {stream: {'path': str(artifacts / (stream + '.bin')),
                'sha256': hashlib.sha256(files[stream + '.bin']).hexdigest(), 'size': len(files[stream + '.bin'])}
                for stream in ('stdout', 'stderr')}}))
    destination = tmp_path / 'bundle-with-preparation'
    manifest = create_backup(service.runtime.database, destination, artifact_roots=[artifacts], writers_stopped=True)
    assert len(manifest['files']) == 3
    shutil.rmtree(artifacts)
    assert verify_bundle(destination) == manifest
