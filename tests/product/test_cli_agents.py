"""H2.3 offline process characterization; installed agents are never invoked."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter, argv_for
from my_harness.adapters.engine_fake import ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.processes import identity, liveness
from my_harness.adapters.streams import AgentStream
from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot
from my_harness.core.engine.journal import JournalError
from my_harness.services.managed import LocalSupervisor, _Journal
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.models import ManagedAttemptRow
from test_managed import PLAN, VERSIONS, context, repository


PROBE = str(Path(__file__).with_name('cli_process_probe.py'))


def adapter(tmp_path, mode='success', timeout=2):
    env = (('PROBE_EXPLICIT','selected'), ('PROBE_RECORD',str(tmp_path/'launches.jsonl')),
           ('PROBE_CHILD',str(tmp_path/'child.pid')))
    configs = [CLIConfig(provider, (sys.executable,PROBE,provider,mode),version,env,timeout)
               for provider,version in (('codex','0.163.0'),('claude','2.1.304'))]
    return CLIProcessAdapter(configs, tmp_path/'captures')


def setup_invocation(repository, context, adapter, role='executor'):
    from threading import Event
    versions = {**VERSIONS, **adapter.frozen_versions()}
    job = repository.submit(context,'P001-T001','P001',PLAN,versions,key=str(uuid4()))
    claim = repository.claim()
    repository.register_owner(claim,identity())
    request = AgentRequest(str(uuid4()),role,Selection('synthetic-executor','medium','test'),
                           'Return a synthetic JSON object',None,context_snapshot(context))
    request = repository.agent_started(claim,repository.get_run(job.run_id).history,request)
    journal = _Journal(repository,claim,Event())
    adapter.bind_process_journal(journal)
    return job,claim,request


@pytest.mark.parametrize('provider,role',[('codex','planner'),('codex','reviewer'),('claude','executor')])
def test_explicit_fresh_argv_preflight_and_configuration(tmp_path,context,repository,provider,role):
    port=adapter(tmp_path)
    assert all(report['available'] for report in port.preflight().values())
    job,claim,request=setup_invocation(repository,context,port,role)
    result=port.invoke(context,request)
    assert result.status=='complete' and result.error is None and result.exit_code==0
    assert json.loads(result.payload_json)=={'result':'ñ'}
    metadata=json.loads(result.metadata_json)
    assert metadata['group_state']=='dead'
    launches=[json.loads(line) for line in (tmp_path/'launches.jsonl').read_text().splitlines()]
    assert len(launches)==1 and launches[0]['cwd']==str(context.root)
    args=launches[0]['argv']
    assert '--model' in args and 'synthetic-executor' in args
    assert '--resume' not in args and '--fallback-model' not in args and '--continue' not in args
    assert ('--ephemeral' if provider=='codex' else '--no-session-persistence') in args
    if provider=='codex':
        assert 'model_reasoning_effort="medium"' in args
        assert 'model_provider="openai"' in args
        assert not any(value.startswith('model_providers.') for value in args)
        assert port.capabilities()['cli_internal_retries']['codex']=='built-in-defaults/unknown'
    else:
        assert args[args.index('--session-id')+1]==request.id
        assert args[args.index('--permission-mode')+1]=='dontAsk'
        assert args[args.index('--permission-prompts')+1]=='none'
        assert args[args.index('--tools')+1]==args[args.index('--allowedTools')+1]==''
        assert '--strict-mcp-config' in args
        assert json.loads(args[args.index('--mcp-config')+1])=={'mcpServers':{}}
        assert args[args.index('--setting-sources')+1]==''
        assert json.loads(args[args.index('--settings')+1])=={'disableAllHooks':True,'autoMemoryEnabled':False}
        assert '--disable-slash-commands' in args and '--no-chrome' in args
        assert metadata['observed']['usage'] is None and metadata['observed']['duration_ms']==0
    assert launches[0]['explicit']=='selected'
    assert 'effort' not in metadata['observed']
    for info in metadata['artifacts'].values():
        raw=Path(info['path']).read_bytes()
        assert info['size']==len(raw) and info['sha256']==hashlib.sha256(raw).hexdigest()
    assert Path(metadata['artifacts']['stderr']['path']).read_bytes().endswith(b'\xff\n')
    assert repository.processes(job.id)[0]['status']=='STOPPED'
    spec=repository.processes(job.id)[0]['spec']
    assert spec['cli_internal_retries']==port.capabilities()['cli_internal_retries'][provider]
    assert spec['adapter_version']=='cli-14' and spec['agent']==('executor' if role=='executor' else 'reviewer')
    prompt=Path(spec['prompt_path']).read_bytes()
    assert prompt.decode()==launches[0]['prompt']
    assert spec['prompt_sha256']==hashlib.sha256(prompt).hexdigest()
    assert spec['environment_keys']==sorted(dict(port.agents[spec['agent']].environment))
    repository.close_owner(claim)


@pytest.mark.parametrize('version',['0.163.0','0.164.0'])
@pytest.mark.parametrize('retry_key',['request_max_retries','stream_max_retries'])
def test_reserved_provider_overrides_fail_once_with_preserved_evidence(
        tmp_path,context,repository,monkeypatch,version,retry_key):
    # Reintroduce the previously generated invalid configuration. The independent
    # executable must reject it instead of falsely certifying a successful stream.
    from my_harness.adapters import cli_agents
    ctx=replace(context,policy=replace(context.policy,planning_mode='agent'))
    port=adapter(tmp_path,'version_new' if version=='0.164.0' else 'success')
    port=CLIProcessAdapter((replace(port.agents['reviewer'],cli_version=version),
                            port.agents['executor']),port.artifact_root)
    original=cli_agents.argv_for
    monkeypatch.setattr(cli_agents,'argv_for',lambda config,ctx,request:
                        original(config,ctx,request)+('-c',f'model_providers.openai.{retry_key}=0'))
    assert port.preflight()['reviewer']['available'] is True
    job=repository.submit(ctx,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='reserved')
    def factory(ctx,versions):
        return port,ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    supervisor=LocalSupervisor(repository,factory)
    assert supervisor.run_once().status=='DONE'
    history=repository.get_run(job.run_id).history
    assert history.status=='stopped' and len(history.attempts)==1
    attempt=history.attempts[0]
    assert attempt.request.role=='planner' and attempt.result.status=='failed'
    assert attempt.result.exit_code==1 and not attempt.result.terminal_observed
    assert attempt.result.payload_json is None
    metadata=json.loads(attempt.result.metadata_json)
    assert metadata['observed']=={} and metadata['group_state']=='dead'
    assert Path(metadata['artifacts']['stdout']['path']).read_bytes()==b''
    stderr=Path(metadata['artifacts']['stderr']['path']).read_bytes()
    assert b'reserved built-in provider IDs: openai' in stderr
    assert metadata['artifacts']['stderr']['sha256']==hashlib.sha256(stderr).hexdigest()
    assert repository.processes(job.id)[0]['capture']['status']=='failed'
    assert len((tmp_path/'launches.jsonl').read_text().splitlines())==1
    assert supervisor.run_once() is None
    with Session(repository.engine) as session:
        row=session.scalar(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id==job.run_id))
        assert row.status=='FAILED'
    restarted=SQLiteManagedRepository(make_engine(str(repository.engine.url)))
    assert restarted.get_run(job.run_id).history==history


@pytest.mark.parametrize('version',['cli-1','cli-2'])
def test_previous_adapter_version_cannot_execute_new_configuration(tmp_path,context,repository,version):
    from threading import Event
    port=adapter(tmp_path)
    versions={**VERSIONS,**port.frozen_versions(),'agent_adapter':version}
    job=repository.submit(context,'P001-T001','P001',PLAN,versions,key='old-adapter')
    claim=repository.claim()
    before=repository.get_run(job.run_id)
    with pytest.raises(JournalError,match='configuration differs'):
        port.bind_process_journal(_Journal(repository,claim,Event()))
    assert not (tmp_path/'launches.jsonl').exists()
    assert repository.get_run(job.run_id)==before
    assert repository.processes(job.id)==[]


def test_empty_mcp_wrapper_fails_after_planner_without_review_or_retry(
        tmp_path,context,repository,monkeypatch):
    from my_harness.adapters import cli_agents
    ctx=replace(context,policy=replace(context.policy,planning_mode='agent'))
    port=adapter(tmp_path,'flow')
    original=cli_agents.argv_for
    def old_argv(config,ctx,request):
        args=list(original(config,ctx,request))
        if config.provider=='claude':
            args[args.index('--mcp-config')+1]='{}'
        return tuple(args)
    monkeypatch.setattr(cli_agents,'argv_for',old_argv)
    monkeypatch.setattr(cli_agents,'VERSION','cli-2')
    # Version/help pass although the invocation's JSON is semantically invalid.
    assert all(report['available'] for report in port.preflight().values())
    job=repository.submit(ctx,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='empty-mcp')
    def factory(ctx,versions):
        return port,ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    supervisor=LocalSupervisor(repository,factory)
    with pytest.raises(JournalError, match='required permissions'):
        supervisor.run_once()
    run = repository.get_run(job.run_id)
    history = run.history
    assert run.status == 'RECOVERY_REQUIRED'
    processes=repository.processes(job.id)
    assert len(processes)==2 and all(p['status']=='STOPPED' for p in processes)
    assert processes[1]['capture']['status']=='refused'
    assert processes[1]['identity'] is None and processes[1]['spec']['launch_permitted'] is False
    with Session(repository.engine) as session:
        rows=session.scalars(select(ManagedAttemptRow).where(
            ManagedAttemptRow.run_id==job.run_id).order_by(ManagedAttemptRow.number)).all()
        results_before=[row.result_json for row in rows]
    assert supervisor.run_once() is None
    assert len((tmp_path/'launches.jsonl').read_text().splitlines())==1
    # Loading historical cli-2 evidence with cli-3 never rewrites it.
    monkeypatch.setattr(cli_agents,'VERSION','cli-3')
    restarted=SQLiteManagedRepository(make_engine(str(repository.engine.url)))
    try:
        assert restarted.get_run(job.run_id).history==history
        assert restarted.processes(job.id)==processes
        with Session(restarted.engine) as session:
            rows=session.scalars(select(ManagedAttemptRow).where(
                ManagedAttemptRow.run_id==job.run_id).order_by(ManagedAttemptRow.number)).all()
            assert [row.result_json for row in rows]==results_before
    finally:
        restarted.engine.dispose()


@pytest.mark.parametrize('mode,status', [('invalid','invalid'),('utf8','partial'),('partial','partial'),
    ('no_terminal','partial'),('error','failed'),('exit_error','failed'),('bad_payload','invalid'),
    ('double_terminal','invalid'),('hang','timeout')])
def test_partial_error_invalid_timeout_preserve_raw_once(tmp_path,context,repository,mode,status):
    port=adapter(tmp_path,mode,timeout=.2 if status=='timeout' else 10)
    job,claim,request=setup_invocation(repository,context,port)
    result=port.invoke(context,request)
    assert result.status==status and result.error and result.payload_json is None
    assert len((tmp_path/'launches.jsonl').read_text().splitlines())==1
    meta=json.loads(result.metadata_json)
    assert Path(meta['artifacts']['stdout']['path']).stat().st_size>0
    assert repository.processes(job.id)[0]['capture']['status']==status
    repository.close_owner(claim)


def wait_until(predicate, timeout=5):
    deadline=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>deadline:
            raise AssertionError('Timed out waiting for synthetic process')
        time.sleep(.01)


def test_incremental_bytes_available_before_exit_and_group_cancel(tmp_path,context,repository):
    port=adapter(tmp_path,'child',timeout=5)
    job,claim,request=setup_invocation(repository,context,port)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(port.invoke,context,request)
        wait_until(lambda:(tmp_path/'child.pid').exists())
        wait_until(lambda:any(e['kind']=='stream_bytes' for e in repository.events(job.run_id)))
        assert not future.done()
        raw=tmp_path/'captures'/request.id/'stdout.bin'
        assert b'partial' in raw.read_bytes()
        assert port.cancel(request.id).requested
        result=future.result(timeout=5)
    assert result.status=='cancelled' and result.payload_json is None
    assert liveness(identity(int((tmp_path/'child.pid').read_text())))=='dead'
    assert port.cancel(request.id).requested is False
    repository.close_owner(claim)


def test_recovery_blocks_live_owner_and_group_after_lease(tmp_path,context,repository):
    port=adapter(tmp_path,'hang',timeout=5)
    job,claim,request=setup_invocation(repository,context,port)
    second=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='second')
    with ThreadPoolExecutor() as pool:
        future=pool.submit(port.invoke,context,request)
        wait_until(lambda:any(e['kind']=='stream_bytes' for e in repository.events(job.run_id)))
        repository.quarantine(claim,'Synthetic service interruption')
        assert repository.claim() is None
        record=repository.get_run(job.run_id)
        with pytest.raises(Conflict,match='owner'):
            repository.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Requested')
        # Even closing the owner scope cannot release a live group.
        repository.close_owner(claim)
        record=repository.get_run(job.run_id)
        with pytest.raises(Conflict,match='group'):
            repository.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Requested')
        port.cancel(request.id)
        with pytest.raises(JournalError):
            future.result(timeout=5)  # The quarantined lease forbids further capture writes.
    record=repository.get_run(job.run_id)
    repository.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Group checked dead')
    assert repository.claim().id==second.id
    assert repository.get_run(job.run_id).history.attempts[0].result.error.startswith('Interrupted')


@pytest.mark.parametrize("mode,status", [("error","failed"),("invalid","invalid"),
                                         ("no_terminal","partial"),("hang","timeout")])
def test_managed_flow_stops_on_cli_error_without_reviewer_or_retry(tmp_path,context,repository,mode,status):
    port=adapter(tmp_path,mode,timeout=.2 if status=='timeout' else 10)
    job=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='run')
    def factory(ctx,versions):
        return port,ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    supervisor=LocalSupervisor(repository,factory)
    assert supervisor.run_once().status=='DONE'
    history=repository.get_run(job.run_id).history
    assert history.status=='stopped' and len(history.attempts)==1
    assert history.attempts[0].result.status==status
    with Session(repository.engine) as session:
        row=session.scalar(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id==job.run_id))
        assert row.status==status.upper()
    assert supervisor.run_once() is None
    assert len((tmp_path/'launches.jsonl').read_text().splitlines())==1
    restarted=SQLiteManagedRepository(make_engine(str(repository.engine.url)))
    assert restarted.get_run(job.run_id).history==history


def test_spawn_record_failure_never_executes_gate(tmp_path,context,repository,monkeypatch):
    port=adapter(tmp_path)
    job,claim,request=setup_invocation(repository,context,port)
    original=repository.process_update
    def failing(claim,attempt,kind,data):
        if kind=='process_spawned':
            raise OSError('Synthetic SQLite outage')
        return original(claim,attempt,kind,data)
    monkeypatch.setattr(repository,'process_update',failing)
    with pytest.raises(JournalError):
        port.invoke(context,request)
    assert not (tmp_path/'launches.jsonl').exists()
    assert repository.processes(job.id)[0]['identity'] is None
    repository.quarantine(claim,'Spawn persistence failed')
    repository.close_owner(claim)
    record=repository.get_run(job.run_id)
    repository.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Gate EOF without GO')


def test_capture_write_failure_kills_group_without_more_effects(tmp_path,context,repository,monkeypatch):
    port=adapter(tmp_path,'hang')
    job,claim,request=setup_invocation(repository,context,port)
    original=repository.process_updates
    def failing(claim,attempt,items):
        if any(kind=='stream_bytes' for kind, _ in items):
            raise OSError('Synthetic disk persistence outage')
        return original(claim,attempt,items)
    monkeypatch.setattr(repository,'process_updates',failing)
    with pytest.raises(JournalError):
        port.invoke(context,request)
    row=repository.processes(job.id)[0]
    assert liveness(row['identity'],group=True)=='dead'
    assert row['status']=='RUNNING'  # uncertain durable result, never silently retried
    assert (tmp_path/'captures'/request.id/'stdout.bin').read_bytes()
    repository.close_owner(claim)
    row=repository.processes(job.id)[0]
    assert row['status']=='STOPPED' and row['capture']['status']=='interrupted'
    assert row['capture']['settled_by']=='closing_owner'


def test_config_snapshot_mismatch_stops_before_spawn(tmp_path,context,repository):
    port=adapter(tmp_path)
    repository.submit(context,'P001-T001','P001',PLAN,VERSIONS,key='mismatch')
    def factory(ctx,versions):
        return port,ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    with pytest.raises(JournalError,match='configuration'):
        LocalSupervisor(repository,factory).run_once()
    assert not (tmp_path/'launches.jsonl').exists()


def test_unknown_liveness_never_unlocks(tmp_path,context,repository):
    port=adapter(tmp_path)
    job,claim,request=setup_invocation(repository,context,port)
    repository.process_intent(claim,request.id,{'synthetic':True})
    repository.process_update(claim,request.id,'process_spawned',{'host':'another-host','pid':42,'pgid':42})
    repository.quarantine(claim,'Unknown host')
    repository.close_owner(claim)
    record=repository.get_run(job.run_id)
    with pytest.raises(Conflict,match='group'):
        repository.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Cannot observe host')


def test_new_migration_round_trip_preserves_existing_managed_history(repository,context,migrated_database):
    port=adapter(context.root.parent)
    job=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='migration')
    before=repository.get_run(job.run_id)
    command.check(migrated_database[1])
    command.downgrade(migrated_database[1],'0004_managed_queue')
    assert 'managed_processes' not in inspect(repository.engine).get_table_names()
    command.upgrade(migrated_database[1],'head')
    assert repository.get_run(job.run_id)==before
    command.check(migrated_database[1])


def test_actual_owner_crash_restart_retains_group_lock_and_bytes(tmp_path,context,repository):
    from dataclasses import asdict
    import signal
    port=adapter(tmp_path,'hang',timeout=60)
    job=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='crash')
    second=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='after-crash')
    specification=tmp_path/'owner.json'
    specification.write_text(json.dumps({'configs':[asdict(config) for config in port.agents.values()],
                                         'context':context_snapshot(context),'artifacts':str(port.artifact_root)}))
    worker=subprocess.Popen((sys.executable,str(Path(__file__).with_name('cli_owner_probe.py')),
                             str(repository.engine.url),str(specification)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    process_identity=None
    try:
        wait_until(lambda:any(e['kind']=='stream_bytes' for e in repository.events(job.run_id)))
        process_identity=repository.processes(job.id)[0]['identity']
        worker.kill()
        worker.wait(timeout=5)
        time.sleep(.7)
        restarted=SQLiteManagedRepository(make_engine(str(repository.engine.url)))
        assert restarted.recover_expired()==[job.id]
        claim=restarted.get_job(job.id)
        record=restarted.get_run(job.run_id)
        assert liveness(process_identity,group=True)=='alive'
        with pytest.raises(Conflict,match='group'):
            restarted.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Owner dead only')
        assert restarted.claim() is None
        row=restarted.processes(job.id)[0]
        assert row['capture'] is None and row['status']=='RUNNING'
        assert b'partial' in (Path(row['spec']['artifacts'])/'stdout.bin').read_bytes()
        # Test owns this exact synthetic group; production recovery never signals stored PIDs.
        os.killpg(process_identity['pgid'],signal.SIGTERM)
        wait_until(lambda:liveness(process_identity,group=True)=='dead')
        restarted.confirm_stopped(job.id,owner_token=claim.owner_token,expected_version=record.version,reason='Synthetic group observed dead')
        assert restarted.claim().id==second.id
        assert restarted.get_run(job.run_id).history.attempts[0].result.error.startswith('Interrupted')
        assert len((tmp_path/'launches.jsonl').read_text().splitlines())==1
        restarted.engine.dispose()
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        if process_identity and liveness(process_identity,group=True)!='dead':
            os.killpg(process_identity['pgid'],signal.SIGKILL)
        worker.stdout.close()
        worker.stderr.close()


@pytest.mark.parametrize('raw,status',[
    (b'[1]','invalid'),(b'{"type":"result","is_error":false,"subtype":"success","result":"{}"}','complete'),
    (b'{"type":"result","is_error":false,"subtype":"future"}\n','invalid'),
    (b'{"type":"result","is_error":false,"subtype":"success","result":"{}","cost":NaN}\n','invalid'),
    (b'{"type":"future.event","text":"\xff"}\n','invalid'),
    (b'{"type":"result","is_error":null,"subtype":"success"}\n','invalid'),
])
def test_parser_eof_invalid_envelopes_and_nonfinite(raw,status):
    events=[]
    parser=AgentStream('claude',lambda kind,data:events.append((kind,data)))
    for byte in raw:
        parser.feed(bytes([byte]))
    assert parser.finish(0)[0]==status
    assert events


def test_partial_durable_events_keep_unknown_fields_and_exact_byte_ranges(tmp_path,context,repository):
    port=adapter(tmp_path,'slow')
    job,claim,request=setup_invocation(repository,context,port)
    result=port.invoke(context,request)
    events=repository.events(job.run_id,limit=1000)
    original=[e['payload']['original'] for e in events if e['kind']=='agent_event']
    assert {'type':'future.event','opaque':{'a':None}} in original
    raw=(tmp_path/'captures'/request.id/'stdout.bin').read_bytes()
    offset=0
    for event in events:
        if event['kind']=='stream_bytes' and event['payload']['stream']=='stdout':
            payload=event['payload']
            assert payload['offset']==offset
            chunk=raw[offset:offset+payload['size']]
            assert hashlib.sha256(chunk).hexdigest()==payload['sha256']
            offset+=payload['size']
    assert offset==len(raw) and result.status=='complete'
    repository.close_owner(claim)


def test_no_process_launch_without_managed_journal(tmp_path,context):
    port=adapter(tmp_path)
    request=AgentRequest(str(uuid4()),'executor',Selection('model','medium','test'),'prompt',None,context_snapshot(context))
    with pytest.raises(JournalError,match='managed'):
        port.invoke(context,request)
    assert not (tmp_path/'launches.jsonl').exists()


@pytest.mark.parametrize('change',[{'cli_version':'future'}, {'timeout_seconds':float('inf')},
                                   {'executable':('relative',)}, {'environment':(('A','x'),('A','y'))}])
def test_bad_config_rejected_without_execution(tmp_path,change):
    port=adapter(tmp_path)
    with pytest.raises(ValueError):
        replace(port.agents['executor'],**change)


def test_smoke_requires_explicit_consumption_before_side_effects(tmp_path):
    script=Path(__file__).resolve().parents[2]/'scripts/smoke_cli.py'
    result=subprocess.run((sys.executable,str(script),'--codex-model','synthetic','--codex-effort','medium',
                           '--claude-model','synthetic','--claude-effort','medium','--output-parent',str(tmp_path/'smoke')),
                          capture_output=True)
    assert result.returncode==2 and b'not authorized' in result.stderr
    assert not (tmp_path/'smoke').exists()


@pytest.mark.parametrize('planning_mode',['deterministic','agent'])
def test_complete_managed_cli_pipeline_uses_fresh_attempts_and_persisted_results(tmp_path,context,repository,planning_mode):
    ctx=replace(context,policy=replace(context.policy,planning_mode=planning_mode))
    port=adapter(tmp_path,'flow')
    job=repository.submit(ctx,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='complete')
    def factory(ctx,versions):
        return port,ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    assert LocalSupervisor(repository,factory).run_once().status=='DONE'
    record=repository.get_run(job.run_id)
    assert record.status=='ACCEPTANCE_READY'
    roles=[attempt.request.role for attempt in record.history.attempts]
    assert roles==(['planner','executor','reviewer'] if planning_mode=='agent' else ['executor','reviewer'])
    assert len(set(a.request.id for a in record.history.attempts))==len(roles)
    assert all(a.result.status=='complete' and a.request.fresh_session for a in record.history.attempts)
    assert all(p['status']=='STOPPED' for p in repository.processes(job.id))
    assert len((tmp_path/'launches.jsonl').read_text().splitlines())==len(roles)


def test_owner_closed_cannot_launch_a_pending_gate(tmp_path,context,repository):
    port=adapter(tmp_path)
    job,claim,request=setup_invocation(repository,context,port)
    repository.process_intent(claim,request.id,{'synthetic':True})
    repository.close_owner(claim)
    with pytest.raises(Conflict):
        repository.process_update(claim,request.id,'process_spawned',{**identity(),'pgid':os.getpid()})


def test_large_original_event_is_referenced_without_copying_blob_to_sqlite():
    events=[]
    raw=(json.dumps({'type':'future.event','opaque':'x'*20000})+'\n').encode()
    parser=AgentStream('claude',lambda kind,data:events.append((kind,data)))
    parser.feed(raw)
    assert parser.finish(0)[0]=='partial'
    payload=events[0][1]
    assert 'original' not in payload and payload['type']=='future.event'
    reference=payload['original_reference']
    assert reference=={'stream':'stdout','offset':0,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def test_managed_cancellation_is_persisted_and_does_not_launch_review(tmp_path,context,repository):
    port=adapter(tmp_path,'hang',timeout=5)
    job=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='cancel')
    def factory(ctx,versions):
        return port,ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    with ThreadPoolExecutor() as pool:
        future=pool.submit(LocalSupervisor(repository,factory).run_once)
        wait_until(lambda:any(e['kind']=='stream_bytes' for e in repository.events(job.run_id)))
        assert port.cancel(repository.processes(job.id)[0]['attempt_id']).requested
        assert future.result(timeout=5).status=='DONE'
    history=repository.get_run(job.run_id).history
    assert len(history.attempts)==1 and history.attempts[0].result.status=='cancelled'
    with Session(repository.engine) as session:
        assert session.scalar(select(ManagedAttemptRow.status).where(ManagedAttemptRow.run_id==job.run_id))=='CANCELLED'


def test_explicit_cli_retry_uses_new_session_and_preserves_persisted_budget(tmp_path,context,repository):
    port=adapter(tmp_path,'error')
    job=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='retry-start')
    def factory(ctx,versions):
        return adapter(tmp_path,'error'),ScriptedCommandRunner([]),SyntheticWorkspace(ctx,('app/main.txt',))
    supervisor=LocalSupervisor(repository,factory)
    supervisor.run_once()
    before=repository.get_run(job.run_id)
    repository.resume(job.run_id,key='retry-one',expected_version=before.version,retry_executor=True)
    supervisor.run_once()
    after=repository.get_run(job.run_id)
    assert after.revisions==1 and len(after.history.attempts)==2
    assert after.history.attempts[:1]==before.history.attempts
    assert after.history.attempts[0].request.id!=after.history.attempts[1].request.id
    repository.resume(job.run_id,key='retry-two',expected_version=after.version,retry_executor=True)
    supervisor.run_once()
    final=repository.get_run(job.run_id)
    assert final.status=='REVISION_LIMIT' and final.history.attempts==after.history.attempts
    assert len((tmp_path/'launches.jsonl').read_text().splitlines())==2


def test_same_version_without_required_help_capabilities_blocks_execution(tmp_path,context,repository):
    from threading import Event
    port=adapter(tmp_path,'incompatible_help')
    job=repository.submit(context,'P001-T001','P001',PLAN,{**VERSIONS,**port.frozen_versions()},key='bad-help')
    claim=repository.claim()
    with pytest.raises(JournalError,match='version/help'):
        port.bind_process_journal(_Journal(repository,claim,Event()))
    assert not (tmp_path/'launches.jsonl').exists()


def test_new_installed_codex_version_requires_explicit_frozen_selection(tmp_path,context,repository):
    port=adapter(tmp_path,'version_new')
    assert port.preflight()['reviewer']['available'] is False  # no automatic version substitution
    updated=replace(port.agents['reviewer'],cli_version='0.164.0')
    port=CLIProcessAdapter((updated,port.agents['executor']),port.artifact_root)
    job,claim,request=setup_invocation(repository,context,port,role='reviewer')
    result=port.invoke(context,request)
    assert result.status=='complete'
    assert repository.processes(job.id)[0]['spec']['preflight_observed']['version_output']=='codex-cli 0.164.0'
    repository.close_owner(claim)


def test_pre_h23_result_json_and_history_can_resume_without_rewriting_results(context,repository):
    from test_managed import submit, worker, review
    from my_harness.core.engine.contracts import AgentResult, freeze
    from my_harness.core.engine.serialization import load_history
    from my_harness.storage.models import ManagedRunRow
    job=submit(repository,context)
    supervisor,_,_,_=worker(repository,context,[AgentResult(None,error='Synthetic H2.2 interruption')])
    supervisor.run_once()
    with Session(repository.engine) as session,session.begin():
        row=session.scalar(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id==job.run_id))
        result=json.loads(row.result_json)
        result.pop('status')
        result.pop('metadata_json')
        legacy_result=freeze(result)
        row.result_json=legacy_result
        run=session.get(ManagedRunRow,job.run_id)
        serialized=json.loads(run.history_json)
        # Construct the historical format explicitly; current engines emit format 4.
        serialized['format'] = 1
        serialized['history'].pop('prompt_catalog_json')
        for attempt in serialized['history']['attempts']:
            attempt['request'].pop('prompt_snapshot_json')
        request = json.loads(row.request_json)
        request.pop('prompt_snapshot_json')
        row.request_json = freeze(request)
        legacy_request = row.request_json
        run.history_json = freeze(serialized)
        assert 'status' not in serialized['history']['attempts'][0]['result']
        assert load_history(run.history_json).attempts[0].result.status is None
    before=repository.get_run(job.run_id)
    repository.resume(job.run_id,key='legacy-revalidate',expected_version=before.version)
    supervisor,_,_,_=worker(repository,context,[review()])
    assert supervisor.run_once().status=='DONE'
    assert repository.get_run(job.run_id).status=='ACCEPTANCE_READY'
    with Session(repository.engine) as session:
        row=session.scalar(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id==job.run_id).order_by(ManagedAttemptRow.number))
        assert row.result_json==legacy_result
        assert row.request_json==legacy_request
