"""G16 E01–E21: synthetic knowledge, delegated policies/permissions and fake CLIs only. No native qualification."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
from threading import Event

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import EFFORTS, CLIConfig, CLIProcessAdapter
from my_harness.adapters.processes import identity
from my_harness.core.engine import judge as core, tool_bridge
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.services.domain_operations import DomainOperations, DomainRefusal, owner_reader
from my_harness.services.managed import _Journal
from my_harness.services.tool_bridge import BridgeFactory, InvocationResolver, Broker
from my_harness.storage.frozen_context import ReceiptSink
from my_harness.storage.models import JudgeRulingRow, JudgeInvocationRow, UsageInvocationRow, PermissionRequestRow, KnowledgeRevisionRow
from my_harness.storage.operation_journal import command_sink, OperationJournal
from test_domain_operations import TablePermissions
from test_frozen_context import world  # noqa: F401
from test_managed import PLAN, VERSIONS, context, repository  # noqa: F401
from test_operation_journal import thread
from test_configuration import setup as config_setup, dumps, project_data, active_global  # noqa: F401

DURATION = {'kind': 'operation', 'seconds': None}
POLICY = {'id': 'synthetic-delegation', 'revision': 1, 'policy_version': 'synthetic-1', 'active': True,
          'effective_grants': [], 'duties': list(core.DUTIES), 'reconsiderations': 1, 'compound_safe': True,
          'delegable': {'files': ['src/a.py']}, 'duration_ceiling': DURATION,
          'permitted_alternatives': ['read-only'], 'intent_ids': ['intent1']}
INPUTS = {
 'permission': {'dimension': 'files', 'targets': ['src/a.py'], 'capability': 'root_files', 'purpose': 'inspect',
                'blocker': 'missing scope', 'duration': DURATION},
 'planning_choice': {'options': [{'id': 'A', 'admissible': True, 'tradeoffs': 'preserves dependencies', 'criterion_ids': ['C1']},
                               {'id': 'B', 'admissible': False, 'tradeoffs': 'ineligible', 'criterion_ids': ['C1']}], 'criterion_ids': ['C1']},
 'spec_gap': {'gap': 'naming unspecified', 'requirement_ids': ['R1'], 'intent_id': 'intent1', 'delegated_intent': 'existing naming'},
 'blocked_check': {'classification': 'planning_ambiguity', 'blocked_evidence': 'ordering ambiguous', 'intent_id': 'intent1'},
}


def ruling(duty, w=None):
    extra = {'permission': {'duration': DURATION}, 'planning_choice': {'option_id': 'A'},
             'spec_gap': {'proposal': {'text': 'Use existing naming.', 'intent_id': 'intent1', 'requirement_ids': [w['ids']['R001'] if w else 'R1']}},
             'blocked_check': {'proposal': {'text': 'Order tasks by dependency.', 'intent_id': 'intent1'}}}[duty]
    return {'duty': duty, 'outcome': {'permission': 'grant', 'planning_choice': 'select'}.get(duty, 'propose'),
            'rationale': 'Synthetic evidence.', 'evidence_ids': ['ev1'], **extra}


class SyntheticDelegations:
    def __init__(self):
        self.policy = copy.deepcopy(POLICY)

    def judge_policy(self, session, project, duty, subject):
        return self.policy


@pytest.fixture
def judge_world(world, repository, context, tmp_path, request):
    client = getattr(request, 'param', 'codex')
    version = '0.165.0' if client == 'codex' else '2.1.312'
    world['snapshot'] = world['contexts'].prepare_for(context, [world['ids']['R001']], client=client)
    cell = tool_bridge.Qualification(client, version, 'judge', 'T009-synthetic', provenance='simulated')
    config = CLIConfig(client, (sys.executable, '-I', str(Path(__file__).with_name('tool_bridge_client.py')),
                               client, version, 'available-no-calls'), version,
                       (('BRIDGE_PID', str(tmp_path / 'bridge.pid')),), 5)
    adapter = CLIProcessAdapter({'reviewer': config, 'executor': config, 'judge': config}, tmp_path / 'judge-captures')
    permissions = TablePermissions(repository.engine)
    permissions.allow(*(e.id for e in core.CATALOGUE if e.id.startswith('judge.') or e.id in ('knowledge.lookup', 'knowledge.search')))
    delegation = SyntheticDelegations()
    ops = DomainOperations(repository.engine, resolver=InvocationResolver(), permissions=permissions,
                           authorizations=delegation, delivery=ReceiptSink('tool_result'), audit_sinks=(command_sink,),
                           judge_qualifications=(cell,))
    adapter.bind_tool_bridges(BridgeFactory(ops, qualifications=(cell,)))
    versions = {**VERSIONS, **adapter.frozen_versions(), 'judge_model': 'synthetic-model', 'judge_effort': 'medium'}
    thread(repository.engine)
    return {**world, 'ops': ops, 'service': ops.judges, 'adapter': adapter, 'cell': cell,
            'versions': versions, 'delegation': delegation, 'permissions': permissions}


def create(w, context, duty='permission', **changes):
    inputs = copy.deepcopy(changes.pop('inputs', INPUTS[duty]))
    for field, code in (('requirement_ids','R001'),('criterion_ids','C001')):
        if field in inputs:
            inputs[field] = [w['ids'][code] if value in ('R1','C1') else value for value in inputs[field]]
    if duty == 'planning_choice':
        for option in inputs['options']:
            option['criterion_ids'] = inputs['criterion_ids']
    return w['service'].create(context, w['versions'], duty=duty, subject=changes.pop('subject', 'subject'),
        inputs=inputs, evidence=changes.pop('evidence', {'ev1': 'Synthetic evidence.'}),
        snapshot_id=w['snapshot'], **changes)


def start(w, repository, context, duty):
    row = create(w, context, duty)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, w['versions'], key=duty)
    claim = repository.claim(lease_seconds=120)
    request = w['service'].assemble(w['project'], row['id'], context, w['adapter'],
                                    language=repository.job_language(claim))
    repository.register_owner(claim, identity())
    request = w['service'].start(repository, claim, request, thread_id='thread-1', key='judge')
    w['adapter'].bind_process_journal(_Journal(repository, claim, Event()))
    return row, request, job, claim


@pytest.mark.parametrize('duty', core.DUTIES)
def test_four_accounted_duties_scoped_submission_and_replay(judge_world, repository, context, duty):
    w=judge_world
    row, request, job, claim = start(w, repository, context, duty)
    with Session(repository.engine) as session:
        caller = w['ops'].resolver.resolve(session, request.id)
    broker = Broker(w['ops'], caller)
    scoped = {e.id for e in w['ops'].scoped(caller)}
    assert scoped == {'knowledge.lookup', 'knowledge.search', f'judge.{duty}.submit'}
    value = ruling(duty, w)
    entry = core.CATALOGUE.current(f'judge.{duty}.submit')
    result = w['ops'].execute(caller, entry.ref, {'candidate': value}, key='submit')
    assert result.result['status'] == 'CANDIDATE'
    assert w['ops'].execute(caller, entry.ref, {'candidate': value}, key='submit').replayed
    assert w['service'].read(w['project'], row['id'])['ruling'] is None  # no early approval
    native = AgentResult(freeze(value), terminal_observed=True, exit_code=0, status='complete')
    w['service'].record_result(repository, claim, request, native)
    finished = w['service'].read(w['project'], row['id'])
    assert finished['ruling']['status'] == 'VALIDATED'
    assert finished['ruling']['origin']['kind'] == 'owner_delegated'
    assert finished['ruling']['proposal_only']
    assert create(w, context, duty)['id'] == row['id']
    assert w['service'].reconcile(w['project'], row['id'])['ruling'] == finished['ruling']
    with Session(repository.engine) as session:
        assert session.query(UsageInvocationRow).count() == 1
        assert session.query(JudgeInvocationRow).count() == 1
        assert session.query(JudgeRulingRow).count() == 1
        assert session.query(PermissionRequestRow).count() == 0
    with pytest.raises(ValueError):
        w['service'].assemble(w['project'], row['id'], context, w['adapter'], qualifications=(w['cell'],))


@pytest.mark.parametrize('duty', core.DUTIES)
@pytest.mark.parametrize('case', ['unknown_field', 'missing_field', 'bad_evidence', 'invented_choice', 'owner_power'])
def test_adversarial_incomplete_candidates(duty, case):
    value = ruling(duty)
    if case == 'unknown_field': value['grant_effective_permission'] = True
    elif case == 'missing_field': value.pop('rationale')
    elif case == 'bad_evidence': value['evidence_ids'] = ['invented']
    elif case == 'invented_choice': value['option_id'] = 'C'
    else: value['changes'] = [{'kind': 'criterion', 'text': 'drop C1'}]
    with pytest.raises(ValueError):
        core.candidate(duty, INPUTS[duty], {'ev1': 'evidence'}, POLICY, freeze(value))


@pytest.mark.parametrize('capability', sorted(core.OWNER_ONLY))
def test_owner_only_gated_even_if_delegable(capability):
    inputs = {**INPUTS['permission'], 'capability': capability}
    assert core.eligibility('permission', inputs, POLICY) == 'owner_only'


def test_duration_compound_and_denial_limits():
    value = {**ruling('permission'), 'duration': {'kind': 'permanent', 'seconds': None}}
    with pytest.raises(ValueError): core.candidate('permission', INPUTS['permission'], {'ev1': 'e'}, POLICY, freeze(value))
    assert core.eligibility('permission', INPUTS['permission'], {**POLICY, 'compound_safe': False}) == 'owner_only'
    value = {**ruling('permission'), 'outcome': 'deny', 'alternative': '../outside'}; value.pop('duration')
    with pytest.raises(ValueError): core.candidate('permission', INPUTS['permission'], {'ev1': 'e'}, POLICY, freeze(value))


@pytest.mark.parametrize('classification', ['authentication', 'environment', 'integrity', 'writer_uncertainty', 'authority'])
def test_ineligible_blocker_never_infers(judge_world, context, classification):
    row = create(judge_world, context, 'blocked_check', inputs={**INPUTS['blocked_check'], 'classification': classification})
    assert row['ruling']['reason'] == 'ineligible_blocker' and row['invocation_id'] is None


@pytest.mark.parametrize('duty', core.DUTIES)
@pytest.mark.parametrize('status', ['timeout', 'failed', 'refused', 'malformed', 'abstain', 'escalate'])
def test_failure_evidence_no_retry(judge_world, repository, context, duty, status):
    w=judge_world
    row, request, job, claim = start(w, repository, context, duty)
    payload = ruling(duty, w)
    if status in ('abstain','escalate'):
        payload = {k:v for k,v in payload.items() if k in ('duty','rationale','evidence_ids')}; payload['outcome']=status
    raw = '{broken' if status=='malformed' else freeze(payload)
    result = AgentResult(raw, terminal_observed=True, exit_code=0,
                         status='complete' if status in ('malformed','abstain','escalate') else status)
    w['service'].record_result(repository, claim, request, result)
    stopped = create(w, context, duty)
    assert stopped['id'] == row['id'] and stopped['ruling']['status'] in ('FAILED','ESCALATED')
    assert stopped['ruling']['raw_reference']['attempt_id'] == request.id
    assert stopped['invocation_id']


def test_equivalence_bound_recovery_and_fencing(judge_world, repository, context):
    w=judge_world
    row, request, job, claim = start(w, repository, context, 'permission')
    broad = create(w, context, inputs={**INPUTS['permission'], 'targets':['src/**']})
    assert broad['id']==row['id'] and broad['continuation']=='observe_existing_invocation'
    assert create(w, context, evidence={'ev1':'new synthetic evidence'}, reconsider=True)['ruling']['reason']=='unresolved_prior_inference'
    OperationJournal(repository.engine).recover('thread-1', writer_stopped=True, at='2999-01-01T00:00:00+00:00')
    recovered=w['service'].reconcile(w['project'],row['id'])
    assert recovered['ruling']['status']=='UNCERTAIN'
    with pytest.raises(Exception):
        w['service'].start(repository, replace(claim, owner_token='stale'), request, thread_id='thread-1',key='another')
    with Session(repository.engine) as session: assert session.query(UsageInvocationRow).count()==1


def test_native_admission_never_uses_reviewer_qualification(judge_world, context):
    w=judge_world
    row=create(w,context)
    with pytest.raises(ValueError): w['service'].assemble(w['project'],row['id'],context,w['adapter'],qualifications=tool_bridge.NATIVE)
    assert core.admit_profile(w['adapter'].agents,w['versions'],efforts=EFFORTS,qualifications=(w['cell'],)).provenance=='simulated'
    with pytest.raises(ValueError): core.admit_profile(w['adapter'].agents,{**w['versions'],'judge_cli':'0.166.0'},efforts=EFFORTS,qualifications=(w['cell'],))
    with pytest.raises(ValueError): core.admit_profile({'reviewer':w['adapter'].agents['reviewer']},w['versions'],efforts=EFFORTS)


def test_default_product_delegation_denies_and_missing_evidence(judge_world, context):
    w=judge_world
    w['service'].operations.authorizations=object()
    assert create(w,context)['ruling']['reason']=='not_delegated'
    w['service'].operations.authorizations=w['delegation']
    assert create(w,context,subject='missing',evidence={})['ruling']['reason']=='missing_evidence'


def test_exact_new_configuration_opt_in_and_old_hashes(config_setup, monkeypatch):
    from my_harness.services.configuration import parse, runtime
    from my_harness.services.local_config import _build
    repo,data,folder=config_setup
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('configuration parse launched process'))
    old=freeze(parse(dumps(data),'global'))
    data['agents']['judge']=copy.deepcopy(data['agents']['reviewer'])
    with pytest.raises(ValueError): parse(dumps(data),'global')
    data['format']='local-config-11'
    new=parse(dumps(data),'global')
    config=_build(runtime(new),folder/'global.toml',allow_empty_compositions=True,editor=True,allow_judge=True)[0]
    assert 'judge' in config.registrar.agents
    for bad in ({'effort':'unknown'},{'model':'-flag'},{'provider':'other'},{'tools':['Write']}):
        candidate=copy.deepcopy(data); candidate['agents']['judge'].update(bad)
        with pytest.raises(ValueError):parse(dumps(candidate),'global')
    data['agents'].pop('judge');data['format']='local-config-9'
    assert freeze(parse(dumps(data),'global'))==old


@pytest.mark.parametrize('judge_world', ['codex', 'claude'], indirect=True)
@pytest.mark.parametrize('duty', core.DUTIES)
def test_fake_cli_fresh_read_only_judge_and_accounting(judge_world, repository, context, duty):
    w = judge_world
    adapter = w['adapter']
    adapter.agents['judge'] = replace(adapter.agents['judge'], environment=(*adapter.agents['judge'].environment,
                                      ('JUDGE_PAYLOAD', freeze(ruling(duty, w)))))
    w['versions'].update(adapter.frozen_versions())
    row, request, job, claim = start(w, repository, context, duty)
    result = adapter.invoke(context, request)
    assert result.status == 'complete', result.error
    w['service'].record_result(repository, claim, request, result)
    assert w['service'].read(w['project'], row['id'])['ruling']['status'] == 'VALIDATED'
    with Session(repository.engine) as session:
        invocation = session.query(UsageInvocationRow).one()
        assert invocation.agent == 'judge' and invocation.requested_model == 'synthetic-model'
    receipts = w['contexts'].deliveries(w['project'], invocation.id)
    assert receipts and {r['channel'] for r in receipts} == {'initial_context'}
    assert request.fresh_session and not json.loads(request.prompt_snapshot_json).get('session_id')
    repository.close_owner(claim)


def test_bounded_explicit_reconsideration(judge_world, repository, context):
    w=judge_world
    row, request, job, claim=start(w,repository,context,'permission')
    w['service'].record_result(repository,claim,request,
        AgentResult(freeze(ruling('permission')),True,0,status='complete'))
    assert create(w,context,evidence={'ev1':'second'},reconsider=True)['ruling'] is None
    assert create(w,context,evidence={'ev1':'third'},reconsider=True)['ruling']['reason']=='reconsideration_bound'


def test_delegation_change_before_start_and_result(judge_world, repository, context):
    w=judge_world
    row,request,job,claim=start(w,repository,context,'permission')
    w['delegation'].policy['active']=False
    w['service'].record_result(repository,claim,request,
        AgentResult(freeze(ruling('permission')),True,0,status='complete'))
    assert w['service'].read(w['project'],row['id'])['ruling']['status']=='ESCALATED'


def test_ruling_records_are_insert_only(judge_world, context, repository):
    w=judge_world
    create(w,context,evidence={})
    with repository.engine.connect() as c:
        for statement in ('DELETE FROM judge_requests','UPDATE judge_rulings SET status=\'VALIDATED\'',
                          'INSERT OR REPLACE INTO judge_rulings SELECT * FROM judge_rulings'):
            with pytest.raises(Exception,match='immutable'): c.execute(text(statement))


def test_project_judge_is_frozen_and_optional(config_setup, tmp_path):
    from my_harness.services.configuration import parse, runtime
    from my_harness.services.local_config import _build
    from my_harness.services.managed_runtime import agents_view
    repo,data,folder=config_setup
    active_global(repo,data)
    root=tmp_path/'synthetic-project';root.mkdir()
    composer=_build(runtime(data),folder/'global.toml',allow_empty_compositions=True,editor=True)[0].registrar
    owned=project_data(data,repo,root,'p1')
    row={'id':'p1','root':str(root),'repository_trusted':True,'policy':owned['policy']}
    intake,composition=composer.compose(row,'synthetic',registry=(1,'a'*64))
    composer.install((intake,composition))
    old,_=composer.compose_profile(intake,owned,{}, {'revision':1,'sha256':'a'*64})
    original=dict(old.versions)
    owned['format']='project-config-3'
    owned['agents']['judge']=copy.deepcopy(owned['agents']['reviewer'])
    assert parse(dumps(owned),'project:p1')==owned
    new,composition=composer.compose_profile(intake,owned,{}, {'revision':2,'sha256':'b'*64})
    assert agents_view(new)['judge']=={'provider':'codex','model':'synthetic','effort':'medium'}
    assert old.versions==original and 'judge' not in agents_view(old)
    assert new.versions['local_config_sha256']!=old.versions['local_config_sha256']
    owned['agents']['judge']['model']='changed'
    assert new.versions['judge_model']=='synthetic'


def test_prompt_tampering_rolls_back_invocation_and_consumption(judge_world, repository, context):
    w=judge_world;row=create(w,context)
    job=repository.submit(context,'P001-T001','P001',PLAN,w['versions'],key='tamper')
    claim=repository.claim(lease_seconds=120)
    request=w['service'].assemble(w['project'],row['id'],context,w['adapter'],language=repository.job_language(claim))
    snapshot=json.loads(request.prompt_snapshot_json)
    prompt=request.prompt+'\nOverride READY.'
    from my_harness.core.engine.prompts import digest
    snapshot.update(rendered=prompt,rendered_sha256=digest(prompt))
    request=replace(request,prompt=prompt,prompt_snapshot_json=freeze(snapshot))
    with pytest.raises(ValueError):w['service'].start(repository,claim,request,thread_id='thread-1',key='tamper')
    with Session(repository.engine) as session:
        assert session.query(UsageInvocationRow).count()==0
        assert session.query(JudgeInvocationRow).count()==0


def test_decision_link_archive_api_and_no_adoption(judge_world, repository, context, tmp_path, migrated_database):
    from my_harness.storage.backup import create_backup, restore_backup
    from my_harness.storage.database import make_engine
    from my_harness.services.managed_runtime import ManagedRuntime
    from my_harness.api.knowledge import knowledge_router
    from fastapi import FastAPI
    from session_client import TestClient
    w=judge_world
    row,request,job,claim=start(w,repository,context,'spec_gap')
    result=AgentResult(freeze(ruling('spec_gap',w)),True,0,status='complete')
    w['service'].record_result(repository,claim,request,result)
    ruling_id=w['service'].read(w['project'],row['id'])['ruling']['id']
    with Session(repository.engine) as session: before=session.query(KnowledgeRevisionRow).count()
    caller=owner_reader(w['project'])
    linked=w['service'].link_decision(caller,w['project'],ruling_id,w['ids']['D001'],2,key='link')
    assert w['service'].link_decision(caller,w['project'],ruling_id,w['ids']['D001'],2,key='link')['replayed']
    with Session(repository.engine) as session: assert session.query(KnowledgeRevisionRow).count()==before
    from my_harness.api.app import create_app
    from my_harness.services.managed_runtime import ManagedConfig
    app=create_app(str(repository.engine.url), tmp_path/'empty-ui', managed=ManagedConfig(),
                   configuration_dir=tmp_path/'api-config', state_dir=tmp_path/'api-state')
    base=f"/api/managed/knowledge/projects/{w['project']}/judge/requests"
    with TestClient(app) as http:
        response=http.get(base+'/'+row['id'])
        assert response.status_code==200 and response.json()['decision_links'][0]['id']==linked['link_id']
        assert http.get(base).json()['total']==1
        assert http.get(base.replace(w['project'],'foreign')+'/'+row['id']).status_code==404
    repository.close_owner(claim)
    create_backup(migrated_database[0].removeprefix('sqlite:///'),tmp_path/'judge-backup',writers_stopped=True)
    restore_backup(tmp_path/'judge-backup',tmp_path/'judge-archive')
    engine=make_engine('sqlite:///'+str(tmp_path/'judge-archive/state.sqlite3'))
    try:
        archive=ManagedRuntime(engine).judges()
        assert archive.read(w['project'],row['id'])['ruling']['id']==ruling_id
        assert archive.list(w['project'])['total']==1
        with pytest.raises(Exception):archive.reconcile(w['project'],row['id'])
    finally:engine.dispose()


@pytest.mark.parametrize('outcome', ['abstain', 'escalate'])
def test_abstention_consumes_reconsideration_bound(judge_world, repository, context, outcome):
    w = judge_world
    row, request, job, claim = start(w, repository, context, 'permission')
    value = {'duty': 'permission', 'outcome': outcome, 'rationale': 'Evidence remains ambiguous.', 'evidence_ids': ['ev1']}
    result = AgentResult(freeze(value), True, 0, status='complete')
    w['service'].record_result(repository, claim, request, result)
    w['service'].record_result(repository, claim, request, result)  # lost acknowledgement, same result
    second = create(w, context, evidence={'ev1': 'Second observation.'}, reconsider=True)
    assert second['ruling'] is None
    second_request = w['service'].assemble(w['project'], second['id'], context, w['adapter'],
                                           language=repository.job_language(claim))
    second_request = w['service'].start(repository, claim, second_request, thread_id='thread-1', key='reconsider')
    w['service'].record_result(repository, claim, second_request, result)
    third = create(w, context, evidence={'ev1': 'Third observation.'}, reconsider=True)
    assert third['ruling']['reason'] == 'reconsideration_bound'
    with Session(repository.engine) as session:
        assert session.query(UsageInvocationRow).count() == 2


def test_changed_canonical_context_is_new_evidence(judge_world, repository, context):
    from test_domain_operations import put, requirement
    from test_frozen_context import adopt
    w = judge_world
    row, request, job, claim = start(w, repository, context, 'permission')
    w['service'].record_result(repository, claim, request, AgentResult(freeze(ruling('permission')), True, 0, status='complete'))
    draft, sha = w['writer'].open(w['revision']['revision_id'])
    w['writer'].apply(draft, sha, [put('requirement', 'R001', requirement('New accepted evidence.'))])
    adopt(w['ops'], w['owner'], draft, w['revision']['revision_id'])
    w['snapshot'] = w['contexts'].prepare_for(context, [w['ids']['R001']], client='codex')
    assert create(w, context, reconsider=True)['id'] != row['id']


def test_wrong_duty_and_candidate_disagreement_escalate(judge_world, repository, context):
    w = judge_world
    row, request, job, claim = start(w, repository, context, 'permission')
    with Session(repository.engine) as session:
        caller = w['ops'].resolver.resolve(session, request.id)
    with pytest.raises(DomainRefusal):
        w['ops'].execute(caller, core.CATALOGUE.current('judge.spec_gap.submit').ref,
                         {'candidate': ruling('spec_gap', w)}, key='wrong-duty')
    w['ops'].execute(caller, core.CATALOGUE.current('judge.permission.submit').ref,
                     {'candidate': ruling('permission')}, key='candidate')
    denial = {'duty': 'permission', 'outcome': 'deny', 'rationale': 'Changed conclusion.', 'evidence_ids': ['ev1'], 'alternative': None}
    w['service'].record_result(repository, claim, request, AgentResult(freeze(denial), True, 0, status='complete'))
    assert w['service'].read(w['project'], row['id'])['ruling']['status'] == 'ESCALATED'


def test_missing_canonical_reference_and_unadmissible_option_stop_before_inference(judge_world, context):
    w = judge_world
    missing = {**INPUTS['spec_gap'], 'requirement_ids': ['invented']}
    assert create(w, context, 'spec_gap', inputs=missing)['ruling']['reason'] == 'missing_reference'
    empty = {'criterion_ids': ['C1'], 'options': []}
    assert create(w, context, 'planning_choice', inputs=empty)['ruling']['reason'] == 'no_admissible_option'


def test_native_start_rejects_unqualified_marker_before_accounting(judge_world, repository, context):
    from my_harness.services.judge import JudgeService
    w = judge_world
    row = create(w, context)
    productive = JudgeService(w['ops'])  # exact native matrix only, no simulated cell
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, w['versions'], key='native-admission')
    claim = repository.claim(lease_seconds=120)
    request = w['service'].assemble(w['project'], row['id'], context, w['adapter'],
                                    language=repository.job_language(claim))
    with pytest.raises(ValueError):
        productive.start(repository, claim, request, thread_id='thread-1', key='native-admission')
    with Session(repository.engine) as session:
        assert session.query(UsageInvocationRow).count() == 0
        assert session.query(JudgeInvocationRow).count() == 0


def test_judge_binds_the_jobs_frozen_language(judge_world, repository, context):
    from test_language_directive import associate, visual
    w = judge_world
    associate(repository.engine, context.root, 'es')
    visual(repository, 'es')
    row = create(w, context)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, w['versions'], key='judge-language')
    claim = repository.claim(lease_seconds=120)
    language = repository.job_language(claim)
    request = w['service'].assemble(w['project'], row['id'], context, w['adapter'], language=language)
    request = w['service'].start(repository, claim, request, thread_id='thread-1', key='judge-language')
    snapshot = json.loads(request.prompt_snapshot_json)
    assert snapshot['language']['ui_language'] == 'es'
    assert snapshot['language']['work_language'] == 'es'


@pytest.mark.parametrize('judge_world', ['codex', 'claude'], indirect=True)
@pytest.mark.parametrize('duty', core.DUTIES)
@pytest.mark.parametrize('failure', [None, 'provider', 'quota', 'auth'])
def test_native_malformed_output_owner_route_and_operational_failures(judge_world, repository, context, duty, failure):
    from my_harness.core.engine.domain_catalogue import digest
    from my_harness.storage.models import ManagedAttemptRow
    w = judge_world
    adapter = w['adapter']
    extra = (('JUDGE_RAW_OUTPUT', '{broken'),) if failure is None else (('JUDGE_FAILURE', failure),)
    adapter.agents['judge'] = replace(adapter.agents['judge'],
        environment=(*adapter.agents['judge'].environment, *extra))
    w['versions'].update(adapter.frozen_versions())
    row, request, job, claim = start(w, repository, context, duty)
    result = adapter.invoke(context, request)  # Real AgentStream and adapter, synthetic CLI only.
    metadata = json.loads(result.metadata_json)
    assert result.terminal_observed and result.exit_code == 0 and result.payload_json is None
    assert result.status == ('invalid' if failure is None else 'failed')
    assert metadata['malformed_output'] is (failure is None)
    assert result.error == ('CLI invalid' if failure is None else 'CLI failed')
    artifact = metadata['artifacts']['stdout']
    original = Path(artifact['path']).read_bytes()
    import hashlib
    assert hashlib.sha256(original).hexdigest() == artifact['sha256']
    assert (b'{broken' if failure is None else ('synthetic ' + failure).encode()) in original
    w['service'].record_result(repository, claim, request, result)
    w['service'].record_result(repository, claim, request, result)  # Lost acknowledgement replay.
    stopped = create(w, context, duty)
    ruling_result = stopped['ruling']
    assert ruling_result['status'] == ('ESCALATED' if failure is None else 'FAILED')
    assert ruling_result['continuation'] == ('owner' if failure is None else 'operational_stop')
    assert ruling_result['raw_reference'] == {'attempt_id': request.id, 'field': 'result_json'}
    assert ruling_result['native_result_sha256'] == digest(json.loads(freeze(result.__dict__)))
    assert w['service'].reconcile(w['project'], row['id'])['ruling'] == ruling_result
    with pytest.raises(ValueError):
        w['service'].assemble(w['project'], row['id'], context, adapter)
    with Session(repository.engine) as session:
        persisted = session.get(ManagedAttemptRow, request.id)
        assert json.loads(persisted.result_json)['metadata_json'] == result.metadata_json
        assert session.query(UsageInvocationRow).count() == 1
        assert session.query(JudgeInvocationRow).count() == 1
        assert session.query(JudgeRulingRow).count() == 1
    assert Path(artifact['path']).read_bytes() == original
    repository.close_owner(claim)


@pytest.mark.parametrize('changes', [
    {'metadata_json': None}, {'metadata_json': '{broken'},
    {'metadata_json': '{"malformed_output":false}'},
    {'terminal_observed': False}, {'exit_code': 1}, {'exit_code': None},
    {'status': 'partial'}, {'status': 'timeout'}, {'status': 'cancelled'}, {'status': 'interrupted'},
    {'error': 'transport failed'},
])
def test_invalid_without_clean_payload_failure_evidence_stays_operational(judge_world, repository, context, changes):
    w = judge_world
    row, request, job, claim = start(w, repository, context, 'permission')
    result = AgentResult(None, True, 0, error='CLI invalid', status='invalid',
                         metadata_json=freeze({'malformed_output': True}))
    w['service'].record_result(repository, claim, request, replace(result, **changes))
    outcome = w['service'].read(w['project'], row['id'])['ruling']
    assert outcome['status'] == 'FAILED' and outcome['continuation'] == 'operational_stop'


@pytest.mark.parametrize('judge_world', ['codex', 'claude'], indirect=True)
@pytest.mark.parametrize('provider_failure', [False, True])
def test_native_protocol_invalid_does_not_mask_operational_failure(judge_world, repository, context, provider_failure):
    w = judge_world
    adapter = w['adapter']
    extra = (('JUDGE_PROTOCOL_FAULT', '1'),)
    if provider_failure:
        extra += (('JUDGE_FAILURE', 'provider'),)
    else:
        extra += (('JUDGE_RAW_OUTPUT', '{broken'),)
    adapter.agents['judge'] = replace(adapter.agents['judge'],
        environment=(*adapter.agents['judge'].environment, *extra))
    w['versions'].update(adapter.frozen_versions())
    row, request, job, claim = start(w, repository, context, 'permission')
    result = adapter.invoke(context, request)
    assert result.status == 'invalid' and result.terminal_observed and result.exit_code == 0
    assert json.loads(result.metadata_json)['malformed_output'] is False
    w['service'].record_result(repository, claim, request, result)
    outcome = w['service'].read(w['project'], row['id'])['ruling']
    assert outcome['status'] == 'FAILED' and outcome['continuation'] == 'operational_stop'
    repository.close_owner(claim)
