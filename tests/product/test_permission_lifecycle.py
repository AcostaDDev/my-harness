"""D291 synthetic-only permission lifecycle: temporary SQLite, canonical contexts, no providers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.core.engine import domain_policy, permission_targets as targets
from my_harness.core.engine.domain_catalogue import CATALOGUE
from my_harness.services.domain_operations import DomainOperations, DomainRefusal, owner_reader
from my_harness.services.permission_lifecycle import PermissionLifecycle
from my_harness.storage.models import PermissionRecordRow
from test_frozen_context import world  # noqa: F401
from test_managed import context, repository  # noqa: F401
from test_domain_operations import run

PERMANENT = {'kind': 'permanent', 'seconds': None}
ONCE = {'kind': 'operation', 'seconds': None}


@pytest.fixture
def permissions(world, repository):
    clock = ['2026-10-30T10:00:00.000000+00:00']
    ceilings = {l: {} for l in ('global', 'project', 'contract', 'provider')}
    lifecycle = PermissionLifecycle(repository.engine, authority=lambda s, p: ceilings, clock=lambda: clock[0])
    ops = DomainOperations(repository.engine, permissions=lifecycle)
    return SimpleNamespace(w=world, repo=repository, service=lifecycle, ops=ops, clock=clock, ceilings=ceilings)


def request(p, *, dimension='tools', values=None, duration=PERMANENT, parent=None, operation='operation-1', purpose='validation'):
    e = CATALOGUE.current('knowledge.head')
    values = values or [{'domain': e.id, 'version': e.version, 'schema_sha256': e.schema_sha256}]
    data = {'grantee': 'executor', 'dimension': dimension, 'targets': values, 'purpose': purpose,
            'snapshot_id': p.w['snapshot'], 'duration': duration, 'operation_key': operation, 'parent': parent, 'replaces': None}
    result = run(p.ops, p.w['owner'], 'permissions.request', {'request': data}, 'request-'+str(__import__('uuid').uuid4()))
    return result.result['request_id']


def inspect(p):
    return run(p.ops, owner_reader(p.w['project']), 'permissions.inspect', {}).result


def response(p, identity, action='grant', duration=PERMANENT):
    data = {'record_id': identity, 'reason': 'Synthetic owner revocation.'} if action in ('revoke','end') else {
        'request_id': identity, 'duration': duration, 'reason': 'Synthetic owner response.'}
    args = {'action': action, 'response': data, 'expected_revision': inspect(p)['revision']}
    preview = run(p.ops, p.w['owner'], 'permissions.preview', args).result
    return run(p.ops, p.w['owner'], 'permissions.respond', {**args, 'preview_sha256': preview['preview_sha256'], 'confirmed': True},
               'response-'+str(__import__('uuid').uuid4())).result['record_id']


def test_manual_permanent_denial_equivalence_and_stale_response(permissions):
    p = permissions
    req = request(p)
    assert request(p, values=[{'domain': 'knowledge.get', 'version': 1, 'schema_sha256': CATALOGUE.get('knowledge.get',1).schema_sha256}]) == req
    assert response(p, req, 'deny')
    assert request(p) == req
    assert inspect(p)['items'][-1]['kind'] == 'deny'
    with pytest.raises(DomainRefusal):
        response(p, req)
    assert not any(r['kind'] == 'grant' for r in inspect(p)['items'])


def test_permanence_expiry_cascade_and_independent_origin(permissions, context):
    p = permissions
    target = targets.normalize('tools', {'domain':'knowledge.head','version':1,
        'schema_sha256':CATALOGUE.get('knowledge.head',1).schema_sha256}, str(context.root))
    parent = p.service.authorize(p.w['project'], grantee='executor', targets_list=[target], purpose='validation')
    grant = response(p, request(p, parent=parent))
    independent = response(p, request(p, operation='independent'))
    response(p, parent, 'end')
    items = {r['id']:r for r in inspect(p)['items']}
    assert not items[grant]['active'] and items[independent]['active']
    p.clock[0] = '2036-10-30T10:00:00.000000+00:00'
    assert {r['id']:r for r in inspect(p)['items']}[independent]['active']
    req = request(p, operation='temporary', duration={'kind':'time_limited','seconds':1})
    temporary = response(p, req, duration={'kind':'time_limited','seconds':1})
    p.clock[0] = '2036-10-30T10:00:01.000000+00:00'
    assert not {r['id']:r for r in inspect(p)['items']}[temporary]['active']


@pytest.mark.parametrize('bad', ['../x','/x','src/../x','a\\b','*.py','.', 'a\x00b'])
def test_adversarial_paths(context, bad):
    with pytest.raises(ValueError):
        targets.normalize('files', {'path':bad,'operation':'write'}, str(context.root))


def test_path_aliases_symlinks_and_dimensions(context):
    root = context.root
    a = targets.normalize('files', {'path':'app//./main.txt','operation':'write'}, str(root))
    assert a == targets.normalize('files', {'path':'app/main.txt','operation':'write'}, str(root))
    read = targets.normalize('files', {'path':'app/main.txt','operation':'read'}, str(root))
    assert targets.token(a) != targets.token(read)
    (root/'alias').symlink_to(root/'app')
    for value in ('alias/main.txt','APP/main.txt'):
        with pytest.raises(ValueError):
            targets.normalize('files', {'path':value,'operation':'write'}, str(root))


@pytest.mark.parametrize('bad', ['http://127.1','http://0x7f.0.0.1','https://user@a.test','https://a.test/path','https://*.test','https://a.test.','https://a.test:0','https://a.test%2f','https://é.test'])
def test_adversarial_network(context, bad):
    with pytest.raises(ValueError):
        targets.normalize('network', {'destination':bad}, str(context.root))


def test_network_canonical(context):
    normalize=lambda s: targets.normalize('network', {'destination':s}, str(context.root))
    assert normalize('https://EXAMPLE.test') == normalize('https://example.test:443')
    assert normalize('https://example.test') != normalize('http://example.test')


def test_concurrent_owner_consumption(permissions):
    p = permissions
    req = request(p)
    args = {'action':'grant','response':{'request_id':req,'reason':'Synthetic response','duration':PERMANENT},'expected_revision':inspect(p)['revision']}
    preview = run(p.ops,p.w['owner'],'permissions.preview',args).result
    args.update(preview_sha256=preview['preview_sha256'],confirmed=True)
    def consume(i):
        try:
            return run(p.ops,p.w['owner'],'permissions.respond',args,'same-response').result
        except DomainRefusal as error:
            return error.code
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(consume,range(2)))
    assert results[0] == results[1]
    assert sum(r['kind']=='grant' for r in inspect(p)['items']) == 1


def start_boundary(p, context, *, marker=None, key='operation-1', role='executor', adapter=None):
    import json
    from uuid import uuid4
    from my_harness.adapters.processes import identity
    from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot
    from my_harness.core.engine.prompts import builtin_catalog
    from my_harness.storage.operation_journal import InvocationOperation
    from my_harness.storage.models import GraphThreadRow
    from test_operation_journal import thread
    from test_managed import PLAN, VERSIONS
    with Session(p.repo.engine) as s:
        exists=s.get(GraphThreadRow,'thread-1')
    if not exists:
        thread(p.repo.engine)
    versions={**VERSIONS, **(adapter.frozen_versions() if adapter else {}), 'permission_authority':json.dumps(p.ceilings)}
    job=p.repo.submit(context,'P001-T001','P001',PLAN,versions,key=str(uuid4()))
    claim=p.repo.claim(lease_seconds=120)
    p.repo.register_owner(claim,identity())
    prompt,frozen=p.w['contexts'].render(p.w['project'],p.w['snapshot'],builtin_catalog(),'review-task',{'INPUT_JSON':'{}'},context)
    frozen=json.loads(frozen)
    frozen['permissions']=marker or p.service.prepare(p.w['project'],role=role,purpose='validation',operation_key=key,authority=copy.deepcopy(p.ceilings))
    req=AgentRequest(str(uuid4()),role,Selection('synthetic-model','medium','test'),prompt,None,context_snapshot(context),prompt_snapshot_json=json.dumps(frozen))
    p.repo.permission_lifecycle=p.service
    req=p.repo.agent_started(claim,p.repo.get_run(job.run_id).history,req,InvocationOperation('thread-1',key))
    from my_harness.storage.models import PermissionBoundaryRow
    with Session(p.repo.engine) as s:
        boundary=s.scalar(select(PermissionBoundaryRow).where(PermissionBoundaryRow.attempt_id==req.id))
        invocation=boundary.invocation_id
    from my_harness.services.domain_operations import Caller
    caller=Caller('agent','broker',knowledge_project_id=p.w['project'],root=str(context.root),role=role,
        invocation_id=invocation,attempt_id=req.id,thread_id='thread-1',operation_key=key,
        frozen_revision_id=p.w['revision']['revision_id'],tool_policy=frozenset(e.ref for e in CATALOGUE))
    return caller,claim,req


def allow(p, *tokens):
    for l in p.ceilings:
        p.ceilings[l].setdefault('tools',[]).extend(tokens)


def test_frozen_snapshot_current_authority_and_revocation(permissions, context):
    from my_harness.services.domain_operations import DomainOperations
    from my_harness.storage.frozen_context import ReceiptSink
    from test_domain_operations import TrustingResolver
    p=permissions
    entry=CATALOGUE.current('knowledge.head')
    allow(p,entry.tool_target)
    grant=response(p,request(p))
    caller,claim,req=start_boundary(p,context)
    ops=DomainOperations(p.repo.engine,permissions=p.service,resolver=TrustingResolver(),delivery=ReceiptSink())
    assert run(ops,caller,'knowledge.head',{},'read-1').result
    # A new grant cannot modify the already frozen set.
    newer=response(p,request(p,operation='new-request', values=[{'domain':'knowledge.get','version':1,'schema_sha256':CATALOGUE.get('knowledge.get',1).schema_sha256}]))
    with Session(p.repo.engine) as s:
        before=p.service.state(s,caller)
    assert newer not in [g[0] for g in before.grants]
    response(p,grant,'revoke')
    with Session(p.repo.engine) as s:
        after=p.service.state(s,caller)
        assert p.service.cancelled(s,claim.run_id)
    assert before.snapshot_sha256==after.snapshot_sha256 and grant in after.unavailable
    with pytest.raises(DomainRefusal):
        run(ops,caller,'knowledge.head',{},'read-1')
    # Historical boundary cannot be moved into a different project.
    with Session(p.repo.engine) as s:
        with pytest.raises(DomainRefusal):
            p.service.state(s,replace(caller,knowledge_project_id='other-project'))


def test_stale_owner_answer_and_snapshot_admission(permissions, context):
    p=permissions
    allow(p,CATALOGUE.current('knowledge.head').tool_target)
    req=request(p)
    args={'action':'grant','response':{'request_id':req,'reason':'Synthetic','duration':PERMANENT},'expected_revision':inspect(p)['revision']}
    preview=run(p.ops,p.w['owner'],'permissions.preview',args).result
    request(p,operation='unrelated')
    with pytest.raises(DomainRefusal):
        run(p.ops,p.w['owner'],'permissions.respond',{**args,'preview_sha256':preview['preview_sha256'],'confirmed':True},'stale')
    grant=response(p,req)
    marker=p.service.prepare(p.w['project'],role='executor',purpose='validation',operation_key='operation-1',authority=copy.deepcopy(p.ceilings))
    response(p,grant,'revoke')
    with pytest.raises(DomainRefusal):
        start_boundary(p,context,marker=marker)
    with Session(p.repo.engine) as s:
        from my_harness.storage.models import UsageInvocationRow, PermissionBoundaryRow
        assert not list(s.scalars(select(UsageInvocationRow)))
        assert not list(s.scalars(select(PermissionBoundaryRow)))


def test_operation_consumption_and_atomic_rollback(permissions, context, monkeypatch):
    p=permissions
    allow(p,CATALOGUE.current('knowledge.head').tool_target)
    grant=response(p,request(p,duration=ONCE),duration=ONCE)
    original=p.service.append
    def broken(s,project,kind,payload,key,**kw):
        row=original(s,project,kind,payload,key,**kw)
        if kind=='consumed':
            raise RuntimeError('Synthetic crash before commit')
        return row
    monkeypatch.setattr(p.service,'append',broken)
    with pytest.raises(RuntimeError):
        start_boundary(p,context)
    assert not any(i['kind']=='consumed' for i in inspect(p)['items'])
    monkeypatch.setattr(p.service,'append',original)


def test_backup_verifies_immutable_permission_history(permissions, tmp_path):
    from my_harness.storage.permission_lifecycle import verify_archive
    import sqlite3
    p=permissions
    response(p,request(p))
    with sqlite3.connect(p.repo.engine.url.database) as db:
        db.row_factory=sqlite3.Row
        verify_archive(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE permission_records SET payload='{}'")
    from my_harness.storage.backup import create_backup, restore_backup
    create_backup(p.repo.engine.url.database,tmp_path/'permission-backup',writers_stopped=True)
    restore_backup(tmp_path/'permission-backup',tmp_path/'permission-archive')
    from my_harness.storage.database import make_engine
    archive=make_engine('sqlite:///'+str(tmp_path/'permission-archive'/'harness.sqlite3'))
    # Locate the restored database through the bundle's actual layout.
    candidates=list((tmp_path/'permission-archive').rglob('*.sqlite3'))
    assert candidates
    archive=make_engine('sqlite:///'+str(candidates[0]))
    with Session(archive) as s:
        assert s.execute(text('PRAGMA query_only')).scalar()==1
        before=PermissionLifecycle(archive).inspect(s,p.w['project'])
        assert before['items']
    archive.dispose()


@pytest.mark.parametrize('outcome',['grant','deny','escalate'])
def test_consumes_validated_simulated_judge_once(permissions,context,outcome):
    """Persisted synthetic ruling fixture; no native judge qualification or inference."""
    from my_harness.storage.models import JudgeRequestRow, JudgeRulingRow
    from my_harness.core.engine.domain_catalogue import digest
    from my_harness.core.engine.judge import FORMAT
    p=permissions
    e=CATALOGUE.current('knowledge.head')
    target=targets.normalize('tools',{'domain':e.id,'version':e.version,'schema_sha256':e.schema_sha256},str(context.root))
    allow(p,e.tool_target)
    policy={'revision':1,'policy_version':'synthetic-policy-1','reconsiderations':0,'active':True,'duties':['permission'],
        'effective_grants':[],'compound_safe':True,'delegable':{'tools':[e.tool_target]},'duration_ceiling':PERMANENT,
        'permitted_alternatives':[],'intent_ids':[]}
    parent=p.service.authorize(p.w['project'],grantee='executor',targets_list=[target],purpose='validation',delegation=policy)
    req=request(p,parent=parent)
    with Session(p.repo.engine) as s,s.begin():
        row=s.get(PermissionRecordRow,req)
        policy=s.get(PermissionRecordRow,parent).payload['delegation']
        inp={'dimension':'tools','targets':[e.tool_target],'capability':'command','purpose':'validation','blocker':'Synthetic blocker','duration':PERMANENT}
        payload={'format':FORMAT,'inputs':inp,'policy':policy,'evidence':{'fixture':'synthetic'},'revision_id':p.w['revision']['revision_id']}
        jr=JudgeRequestRow(id='synthetic-judge-request',project_id=p.w['project'],snapshot_id=p.w['snapshot'],subject=row.payload['subject'],duty='permission',
            equivalence_sha256=digest({'project':p.w['project'],'duty':'permission','subject':row.payload['subject']}),
            evidence_sha256=digest({'evidence':payload['evidence'],'context_sha256':row.payload['evidence']}),payload=payload,created_at=p.clock[0])
        s.add(jr);s.flush()
        candidate={'duty':'permission','outcome':outcome,'rationale':'Synthetic ruling fixture.','evidence_ids':['fixture']}
        if outcome=='grant': candidate['duration']=PERMANENT
        if outcome=='deny': candidate['alternative']=None
        s.add(JudgeRulingRow(id='synthetic-ruling',request_id=jr.id,status='ESCALATED' if outcome=='escalate' else 'VALIDATED',
            payload={'candidate':candidate,'proposal_only':True,'origin':{'kind':'owner_delegated','parent_id':policy['id'],'parent_revision':1,'policy_version':policy['policy_version']}},created_at=p.clock[0]))
    def consume(_):return p.service.consume_ruling(p.w['project'],req,'synthetic-ruling')
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(consume,range(2)))
    assert results[0]==results[1] and results[0]['state']==outcome
    assert sum(i['kind']==outcome for i in inspect(p)['items'])==1
    assert not any(i['kind']=='grant' for i in inspect(p)['items']) if outcome!='grant' else True


def test_compound_dimensions_current_ceilings_and_snapshot_age(permissions,context):
    p=permissions
    first=response(p,request(p))
    e=CATALOGUE.current('knowledge.get')
    second=response(p,request(p,operation='another',values=[{'domain':e.id,'version':e.version,'schema_sha256':e.schema_sha256}]))
    allow(p,CATALOGUE.current('knowledge.head').tool_target,e.tool_target)
    caller,claim,req=start_boundary(p,context)
    with Session(p.repo.engine) as s:
        state=p.service.state(s,caller)
    assert {g[0] for g in state.grants}=={first,second}
    assert domain_policy.evaluate([('tools',e.tool_target),('tools',CATALOGUE.current('knowledge.head').tool_target)],state).allowed
    assert not domain_policy.evaluate([('network',e.tool_target)],state).allowed
    assert not domain_policy.evaluate([('product','knowledge.adopt:owner_only')],state).allowed
    p.ceilings['project']['tools'].remove(e.tool_target)
    with Session(p.repo.engine) as s:
        narrowed=p.service.state(s,caller)
    assert not domain_policy.evaluate([('tools',e.tool_target)],narrowed).allowed
    assert narrowed.snapshot_sha256==state.snapshot_sha256


def test_revocation_serializes_with_effect(permissions,context):
    from threading import Event
    p=permissions
    allow(p,CATALOGUE.current('knowledge.head').tool_target)
    grant=response(p,request(p))
    caller,claim,req=start_boundary(p,context)
    locked,release=Event(),Event()
    def before_revoke():
        with Session(p.repo.engine) as s,s.begin():
            s.execute(text('DELETE FROM domain_commands WHERE 0'))
            assert domain_policy.evaluate([('tools',CATALOGUE.current('knowledge.head').tool_target)],p.service.state(s,caller)).allowed
            locked.set();assert release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        effect=pool.submit(before_revoke);assert locked.wait(5)
        revocation=pool.submit(response,p,grant,'revoke')
        release.set();effect.result();revocation.result()
    with Session(p.repo.engine) as s:
        assert not domain_policy.evaluate([('tools',CATALOGUE.current('knowledge.head').tool_target)],p.service.state(s,caller)).allowed
        assert p.service.cancelled(s,claim.run_id)


def test_cross_project_and_product_revision_targets(permissions,context):
    p=permissions
    with pytest.raises(DomainRefusal):
        request(p,dimension='product',values=[{'capability':'knowledge.propose:task','entity':'foreign','revision':p.w['revision']['revision_id'],'evidence':'synthetic'}])
    grant=response(p,request(p))
    with Session(p.repo.engine) as s:
        with pytest.raises(DomainRefusal):p.service.get(s,'foreign',grant)


def test_owner_controls_use_shared_http_pipeline(permissions,context):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from my_harness.api.knowledge import knowledge_router
    from my_harness.services.managed_runtime import ManagedRuntime, ManagedProject
    p=permissions
    request(p)
    runtime=ManagedRuntime(p.repo.engine)
    runtime.repository=p.repo
    runtime.projects={'synthetic':ManagedProject('synthetic',context,{})}
    runtime._domain_operations=p.ops
    app=FastAPI();app.include_router(knowledge_router(runtime))
    with TestClient(app,base_url='http://localhost') as client:
        response=client.get('/api/managed/projects/synthetic/permissions')
        assert response.status_code==200 and response.json()['revision']>0
        assert client.post('/api/managed/projects/synthetic/permissions/responses',json={}).status_code==403


def test_owner_escalation_then_grant_and_explicit_supersession(permissions):
    p=permissions
    req=request(p)
    response(p,req,'escalate')
    old=response(p,req)
    e=CATALOGUE.current('knowledge.head')
    data={'grantee':'executor','dimension':'tools','targets':[{'domain':e.id,'version':e.version,'schema_sha256':e.schema_sha256}],
        'purpose':'validation','snapshot_id':p.w['snapshot'],'duration':PERMANENT,'operation_key':'operation-1','parent':None,'replaces':old}
    new_req=run(p.ops,p.w['owner'],'permissions.request',{'request':data},'explicit-replacement').result['request_id']
    assert new_req!=req
    new=response(p,new_req)
    items={r['id']:r for r in inspect(p)['items']}
    assert not items[old]['active'] and items[new]['active']
    with pytest.raises(DomainRefusal):response(p,new_req)


def test_effective_snapshot_excludes_unavailable_ceiling_and_owner_only(permissions,context):
    p=permissions
    response(p,request(p))
    marker=p.service.prepare(p.w['project'],role='executor',purpose='validation',operation_key='operation-1',authority=p.ceilings)
    with Session(p.repo.engine) as s:
        assert p.service.get(s,p.w['project'],marker['id']).payload['grants']==[]
    req=request(p,operation='acceptance',dimension='acceptance',values=[{'capability':'acceptance.verify','entity':p.w['project'],'revision':p.w['revision']['revision_id'],'evidence':'synthetic-tree'}])
    grant=response(p,req)
    with Session(p.repo.engine) as s:
        target=p.service.get(s,p.w['project'],grant).payload['targets'][0]
    for layer in p.ceilings:p.ceilings[layer]['acceptance']=[targets.token(target)]
    marker=p.service.prepare(p.w['project'],role='executor',purpose='validation',operation_key='acceptance',authority=p.ceilings)
    with Session(p.repo.engine) as s:
        assert grant not in p.service.get(s,p.w['project'],marker['id']).payload['grants']


def test_executable_identity_arguments_and_drift(context,tmp_path):
    import hashlib
    executable=tmp_path/'synthetic-validator';executable.write_bytes(b'synthetic executable bytes')
    value={'executable':str(executable),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'argv':[str(executable),'--check'],'cwd':'.','environment':{}}
    first=targets.normalize('tools',value,str(context.root))
    second=targets.normalize('tools',{**value,'argv':[*value['argv'],'--plugin=other']},str(context.root))
    assert targets.token(first)!=targets.token(second)
    executable.write_bytes(b'changed synthetic executable bytes')
    with pytest.raises(ValueError):targets.normalize('tools',value,str(context.root))


def test_revocation_stops_fake_native_writer_with_existing_control(permissions,context,tmp_path):
    from threading import Event
    from my_harness.services.managed import _Journal
    from test_trace_observation import probe_adapter
    from test_cli_agents import wait_until
    p=permissions
    grant=response(p,request(p))
    allow(p,CATALOGUE.current('knowledge.head').tool_target)
    adapter=probe_adapter(tmp_path,'hang')
    adapter.agents['executor']=adapter.agents['reviewer']
    caller,claim,req=start_boundary(p,context,adapter=adapter)
    adapter.bind_process_journal(_Journal(p.repo,claim,Event()))
    with ThreadPoolExecutor(1) as pool:
        invocation=pool.submit(adapter.invoke,context,req)
        wait_until(lambda: req.id in adapter.active or invocation.done())
        if invocation.done():
            invocation.result()
        response(p,grant,'revoke')
        result=invocation.result(timeout=10)
    assert result.metadata_json and result.error is not None
    process=p.repo.processes(claim.id)[0]
    assert process['status'] in ('CANCELLED','FINISHED','STOPPED') or process['capture']['status']=='cancelled'
    assert process['capture']['status']=='cancelled'
    # No inference is reissued; the single managed usage intent is retained for normal settlement/recovery.
    from my_harness.storage.models import UsageInvocationRow
    with Session(p.repo.engine) as s:
        assert len(list(s.scalars(select(UsageInvocationRow))))==1


def test_operation_grant_cannot_admit_a_second_logical_operation(permissions,context):
    p=permissions
    allow(p,CATALOGUE.current('knowledge.head').tool_target)
    grant=response(p,request(p,duration=ONCE),duration=ONCE)
    caller,claim,req=start_boundary(p,context)
    marker=p.service.prepare(p.w['project'],role='executor',purpose='validation',operation_key='operation-1',authority=copy.deepcopy(p.ceilings))
    with Session(p.repo.engine) as s,s.begin():
        s.execute(text('DELETE FROM domain_commands WHERE 0'))
        with pytest.raises(DomainRefusal):
            p.service.seal(s,p.w['project'],marker,SimpleNamespace(key='operation-1',id='second-operation',invocation_id='second-invocation'),
                SimpleNamespace(role='executor',id='second-attempt'),p.ceilings)
    assert sum(r['kind']=='consumed' for r in inspect(p)['items'])==1


def test_manual_confirmation_evidence_is_retained(permissions):
    p=permissions
    grant=response(p,request(p))
    with Session(p.repo.engine) as s:
        row=s.get(PermissionRecordRow,grant)
        assert len(row.payload['actor']['confirmation']['preview_sha256'])==64
        req=s.get(PermissionRecordRow,row.payload['request_id'])
        assert req.payload['submitted_targets'] and req.payload['origin']=='owner_confirmed'


def test_catalogue_version_is_typed_and_missing_identities_deny(permissions,context):
    p=permissions
    entry=CATALOGUE.get('knowledge.head',1)
    with pytest.raises(ValueError):
        targets.normalize('tools',{'domain':entry.id,'version':True,'schema_sha256':entry.schema_sha256},str(context.root))
    with Session(p.repo.engine) as s:
        with pytest.raises(DomainRefusal):p.service.get(s,p.w['project'],None)
        with pytest.raises(DomainRefusal):p.service.inspect(s,None)
