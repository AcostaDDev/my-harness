"""T010 technical review regressions. Synthetic identities, persisted rulings and local fake processes only."""
import copy
from dataclasses import replace
import hashlib
import json
from threading import Event
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.commands import ManagedCommandRunner
from my_harness.core.engine.contracts import AgentResult
from my_harness.core.engine.context import Command
from my_harness.core.engine.domain_catalogue import digest
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.validation import run_command
from my_harness.services.managed import _Journal
from my_harness.storage.models import JudgeRequestRow, JudgeRulingRow, PermissionRecordRow, ManagedEventRow
from my_harness.storage.operation_journal import InvocationOperation
from test_permission_lifecycle import (permissions, world, context, repository, request, response, allow,
    start_boundary, targets, CATALOGUE, DomainRefusal, PERMANENT)
from test_commands import configuration
from test_operation_journal import record_result
from test_cli_agents import wait_until


def policy(entries):
    return {'revision': 1, 'policy_version': 'synthetic-policy-1', 'reconsiderations': 2, 'active': True,
        'duties': ['permission'], 'effective_grants': [], 'compound_safe': True,
        'delegable': {'tools': entries}, 'duration_ceiling': PERMANENT,
        'permitted_alternatives': ['read-only'], 'intent_ids': ['intent-1']}


def canonical(context, name):
    e = CATALOGUE.current(name)
    return targets.normalize('tools', {'domain': e.id, 'version': e.version,
        'schema_sha256': e.schema_sha256}, str(context.root))


def persist_ruling(p, request_id):
    """A synthetic T009 terminal proposal, never a provider invocation or permission by itself."""
    from my_harness.core.engine.judge import FORMAT
    with Session(p.repo.engine) as s, s.begin():
        req = s.get(PermissionRecordRow, request_id)
        delegation = s.get(PermissionRecordRow, req.payload['parent']).payload['delegation']
        inputs = {'dimension': 'tools', 'targets': [targets.token(t) for t in req.payload['targets']],
            'capability': 'command', 'purpose': 'validation', 'blocker': 'Synthetic blocker', 'duration': PERMANENT}
        payload = {'format': FORMAT, 'inputs': inputs, 'policy': delegation,
            'evidence': {'fixture': 'synthetic'}, 'revision_id': p.w['revision']['revision_id']}
        judge = JudgeRequestRow(id=str(uuid4()), project_id=p.w['project'], snapshot_id=p.w['snapshot'],
            subject=req.payload['subject'], duty='permission',
            equivalence_sha256=digest({'project': p.w['project'], 'duty': 'permission', 'subject': req.payload['subject']}),
            evidence_sha256=digest({'evidence': payload['evidence'], 'context_sha256': req.payload['evidence']}),
            payload=payload, created_at=p.clock[0])
        s.add(judge); s.flush()
        ruling = JudgeRulingRow(id=str(uuid4()), request_id=judge.id, status='VALIDATED',
            payload={'candidate': {'duty': 'permission', 'outcome': 'grant', 'rationale': 'Synthetic ruling.',
                'evidence_ids': ['fixture'], 'duration': PERMANENT}, 'proposal_only': True,
                'origin': {'kind': 'owner_delegated', 'parent_id': req.payload['parent'],
                    'parent_revision': 1, 'policy_version': delegation['policy_version']}}, created_at=p.clock[0])
        s.add(ruling); s.flush()
        return ruling.id


@pytest.mark.parametrize('argv', [
    ['push', 'origin', 'main'], ['-C', '.', 'push'], ['reset', '--hard'], ['branch', '-D', 'topic'],
    ['tag', '-f', 'v1'], ['rebase', 'main'], ['publish'], ['deploy'], ['install', 'https://undelegated.test'],
    ['config', '--global', 'credential.helper', 'anything'], ['read-secret'], ['edit-policy'],
])
def test_opaque_native_effect_cannot_be_delegated_or_consumed(permissions, context, tmp_path, argv):
    p = permissions
    # The name is deliberately unrelated to Git/npm/etc: no executable-name containment claim.
    exe = tmp_path / ('git' if argv[0] == 'push' else 'synthetic-wrapper')
    exe.write_bytes(b'Synthetic opaque executable identity; never executed.')
    raw = {'executable': str(exe), 'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
        'argv': [str(exe), *argv], 'cwd': '.', 'environment': {}}
    target = targets.normalize('tools', raw, str(context.root))
    assert targets.owner_only(target)
    allow(p, targets.token(target))
    with pytest.raises(DomainRefusal):
        p.service.authorize(p.w['project'], grantee='executor', targets_list=[target],
            purpose='validation', delegation=policy([targets.token(target)]))
    # Previously persisted vulnerable authorizations must also fail at the full ruling-consumption boundary.
    # Append synthetic pre-correction evidence without using the corrected authorization admission.
    with Session(p.repo.engine) as s, s.begin():
        parent = p.service.append(s, p.w['project'], 'authorization', {'parent': None, 'origin': 'owner_confirmed',
            'grantee': 'executor', 'targets': [target], 'purpose': 'validation', 'expires_at': None,
            'policy_version': 'domain-policy-1', 'delegation': policy([targets.token(target)])}, 'old-authorization')
        req = p.service.append(s, p.w['project'], 'request', {'parent': parent.id, 'targets': [target],
            'grantee': 'executor', 'purpose': 'validation', 'operation_key': 'operation-1', 'duration': PERMANENT,
            'subject': 'synthetic-old-native-subject', 'snapshot_id': p.w['snapshot'], 'evidence': 'synthetic',
            'source_attempt_id': None, 'replaces': None, 'policy_version': 'domain-policy-1'}, 'old-request')
        req_id = req.id
    ruling = persist_ruling(p, req_id)
    with pytest.raises(DomainRefusal):
        p.service.consume_ruling(p.w['project'], req_id, ruling)
    with Session(p.repo.engine) as s:
        assert not list(s.scalars(select(PermissionRecordRow).where(PermissionRecordRow.kind == 'grant')))


def test_catalogue_owner_operations_and_legitimate_consumer(permissions, context):
    p = permissions
    assert targets.owner_only(canonical(context, 'permissions.respond'))
    target = canonical(context, 'knowledge.head')
    assert not targets.owner_only(target)
    allow(p, targets.token(target))
    parent = p.service.authorize(p.w['project'], grantee='executor', targets_list=[target],
        purpose='validation', delegation=policy([targets.token(target)]))
    req = request(p, parent=parent)
    ruling = persist_ruling(p, req)
    applied = p.service.consume_ruling(p.w['project'], req, ruling)
    assert applied['state'] == 'grant'
    with Session(p.repo.engine) as s:
        assert s.get(PermissionRecordRow, applied['record_id']).payload['origin'] == 'owner_delegated'


@pytest.mark.parametrize('widen', ['delegable', 'dimension', 'duration', 'duties', 'reconsiderations',
    'intent_ids', 'permitted_alternatives', 'effective_grants', 'policy_version', 'revision', 'active', 'compound_safe'])
def test_delegation_cannot_promote_any_parent_bound(permissions, context, widen):
    p = permissions
    ts = [canonical(context, n) for n in ('knowledge.head', 'knowledge.get')]
    parent_policy = policy([targets.token(ts[0])])
    if widen == 'active': parent_policy['active'] = False
    if widen == 'compound_safe': parent_policy['compound_safe'] = False
    if widen == 'duration': parent_policy['duration_ceiling'] = {'kind': 'operation', 'seconds': None}
    parent = p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', delegation=parent_policy)
    child = copy.deepcopy(parent_policy)
    if widen == 'delegable': child['delegable']['tools'] = [targets.token(ts[1])]
    elif widen == 'dimension': child['delegable']['network'] = ['exact:synthetic']
    elif widen == 'duration': child['duration_ceiling'] = PERMANENT
    elif widen == 'duties': child['duties'].append('spec_gap')
    elif widen == 'reconsiderations': child['reconsiderations'] += 1
    elif widen in ('intent_ids', 'permitted_alternatives'): child[widen].append('additional')
    elif widen == 'effective_grants': child[widen].append({'id': 'fabricated'})
    elif widen == 'policy_version': child[widen] = 'wider-policy'
    elif widen == 'revision': child[widen] += 1
    else: child[widen] = True
    with pytest.raises(DomainRefusal):
        p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
            purpose='validation', parent=parent, delegation=child)


def test_multiple_generations_narrow_and_independent_owner_authority(permissions, context):
    p = permissions
    ts = [canonical(context, n) for n in ('knowledge.head', 'knowledge.get')]
    original = policy([targets.token(t) for t in ts])
    parent = p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', delegation=original)
    narrow = {**original, 'reconsiderations': 1, 'intent_ids': [], 'permitted_alternatives': [],
        'delegable': {'tools': [targets.token(ts[0])]}}
    child = p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', parent=parent, delegation=narrow)
    grandchild = p.service.authorize(p.w['project'], grantee='executor', targets_list=[ts[0]],
        purpose='validation', parent=child, delegation={**narrow, 'reconsiderations': 0})
    with pytest.raises(DomainRefusal):
        p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
            purpose='validation', parent=child, delegation=original)
    independent = p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', delegation=original)
    response(p, parent, 'revoke')
    with Session(p.repo.engine) as s:
        assert not p.service.active(s, s.get(PermissionRecordRow, grandchild))
        assert p.service.active(s, s.get(PermissionRecordRow, independent))


def post_executor(p, context, command):
    runner = ManagedCommandRunner(configuration(context, command))
    grant = response(p, request(p))
    allow(p, CATALOGUE.current('knowledge.head').tool_target)
    caller, claim, req = start_boundary(p, context, adapter=runner)
    record_result(p.repo, claim, SimpleNamespace(run_id=claim.run_id), req,
        AgentResult('{}', False, 1, status='complete'))
    journal = _Journal(p.repo, claim, Event())
    runner.bind_process_journal(journal)
    return runner, journal, grant, caller, claim, req


def test_post_executor_revocation_refuses_before_native_launch(permissions, context, tmp_path):
    p = permissions
    launched = tmp_path / 'must-not-exist'
    cmd = Command(('python', '-c', f'from pathlib import Path; Path({str(launched)!r}).touch()'))
    runner, journal, grant, caller, claim, req = post_executor(p, context, cmd)
    response(p, grant, 'revoke')
    with Session(p.repo.engine) as s:
        assert p.service.cancelled(s, claim.run_id)
    with pytest.raises(JournalError):
        run_command(context, runner, cmd, journal)
    assert not launched.exists() and not p.repo.command_processes(claim.id)
    with Session(p.repo.engine) as s:
        started = s.scalars(select(ManagedEventRow).where(ManagedEventRow.kind == 'command_started')).one()
        assert started.payload['permission_attempt_id'] == req.id


def test_post_executor_revocation_cancels_live_native_command(permissions, context):
    p = permissions
    cmd = Command(('python', '-c', 'import time; print("synthetic",flush=True); time.sleep(30)'), timeout_seconds=10)
    runner, journal, grant, caller, claim, req = post_executor(p, context, cmd)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(run_command, context, runner, cmd, journal)
        wait_until(lambda: any(e['kind'] == 'command_process_bytes' for e in p.repo.events(claim.run_id)))
        response(p, grant, 'revoke')
        result = future.result(timeout=10)
    assert not result.passed and 'cancelled' in result.error.lower()
    [process] = p.repo.command_processes(claim.id)
    assert process['status'] == 'STOPPED' and process['capture']['group_state'] == 'dead'
    assert process['capture']['streams'] and 'synthetic' in result.stdout
    from my_harness.storage.models import UsageInvocationRow
    with Session(p.repo.engine) as s:
        assert len(list(s.scalars(select(UsageInvocationRow)))) == 1


def test_new_executor_authority_replaces_old_stage_without_rebinding_old_command(permissions, context):
    p = permissions
    cmd = Command(('python', '-c', 'print("synthetic validation")'))
    runner, journal, grant, caller, claim, req = post_executor(p, context, cmd)
    old_command = journal.command_started(cmd)
    response(p, grant, 'revoke')
    response(p, request(p, operation='next-authority'))
    marker = p.service.prepare(p.w['project'], role='executor', purpose='validation',
        operation_key='next-attempt', authority=copy.deepcopy(p.ceilings))
    prompt_snapshot = json.loads(req.prompt_snapshot_json)
    prompt_snapshot['permissions'] = marker
    next_req = replace(req, id=str(uuid4()), permission_snapshot_json=None, prompt_snapshot_json=json.dumps(prompt_snapshot))
    next_req = p.repo.agent_started(claim, p.repo.get_run(claim.run_id).history, next_req,
        InvocationOperation('thread-1', 'next-attempt'))
    record_result(p.repo, claim, SimpleNamespace(run_id=claim.run_id), next_req,
        AgentResult('{}', False, 1, status='complete'))
    assert journal.command_cancel_requested(old_command)
    assert not journal.cancel_requested()
    result = run_command(context, runner, cmd, journal)
    assert result.passed
    events = [e for e in p.repo.events(claim.run_id) if e['kind'] == 'command_started']
    assert events[-1]['payload']['permission_attempt_id'] == next_req.id


def test_old_widened_child_cannot_feed_a_new_ruling(permissions, context):
    p = permissions
    ts = [canonical(context, n) for n in ('knowledge.head', 'knowledge.get')]
    allow(p, *(targets.token(t) for t in ts))
    parent_policy = policy([targets.token(ts[0])])
    parent = p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', delegation=parent_policy)
    # Synthetic old lineage, persisted before the correction; no trigger/history is rewritten.
    with Session(p.repo.engine) as s, s.begin():
        child = p.service.append(s, p.w['project'], 'authorization', {'parent': parent, 'origin': 'owner_delegated',
            'grantee': 'executor', 'targets': ts, 'purpose': 'validation', 'expires_at': None,
            'policy_version': 'domain-policy-1', 'delegation': policy([targets.token(ts[1])])}, 'old-widened-child')
        req = p.service.append(s, p.w['project'], 'request', {'parent': child.id, 'targets': [ts[1]],
            'grantee': 'executor', 'purpose': 'validation', 'operation_key': 'operation-1', 'duration': PERMANENT,
            'subject': 'old-widened-subject', 'snapshot_id': p.w['snapshot'], 'evidence': 'synthetic',
            'source_attempt_id': None, 'replaces': None, 'policy_version': 'domain-policy-1'}, 'old-child-request')
        req_id = req.id
    ruling = persist_ruling(p, req_id)
    with pytest.raises(DomainRefusal):
        p.service.consume_ruling(p.w['project'], req_id, ruling)
    with Session(p.repo.engine) as s:
        assert not list(s.scalars(select(PermissionRecordRow).where(PermissionRecordRow.kind == 'grant')))


def test_current_legacy_executor_does_not_inherit_historical_revocation(permissions, context):
    p = permissions
    cmd = Command(('python', '-c', 'print("synthetic legacy validation")'))
    runner, journal, grant, caller, claim, req = post_executor(p, context, cmd)
    response(p, grant, 'revoke')
    snapshot = json.loads(req.prompt_snapshot_json)
    del snapshot['permissions']
    legacy = replace(req, id=str(uuid4()), permission_snapshot_json=None, prompt_snapshot_json=json.dumps(snapshot))
    legacy = p.repo.agent_started(claim, p.repo.get_run(claim.run_id).history, legacy,
        InvocationOperation('thread-1', 'legacy-current-attempt'))
    record_result(p.repo, claim, SimpleNamespace(run_id=claim.run_id), legacy,
        AgentResult('{}', False, 1, status='complete'))
    assert not journal.cancel_requested()
    assert run_command(context, runner, cmd, journal).passed


def test_revocation_between_runner_check_and_intent_is_refused(permissions, context, monkeypatch):
    p = permissions
    cmd = Command(('python', '-c', 'print("must not launch")'))
    runner, journal, grant, caller, claim, req = post_executor(p, context, cmd)
    original = journal.command_cancel_requested
    def revoke_after_check(command_id):
        assert not original(command_id)
        response(p, grant, 'revoke')
        return False  # emulate revocation committing just after the runner's preliminary read
    monkeypatch.setattr(journal, 'command_cancel_requested', revoke_after_check)
    with pytest.raises(JournalError):
        run_command(context, runner, cmd, journal)
    assert not p.repo.command_processes(claim.id)


@pytest.mark.parametrize('dimension,raw', [
    ('files', [{'path': 'app/first.txt', 'operation': 'read'}, {'path': 'app/second.txt', 'operation': 'read'}]),
    ('network', [{'destination': 'https://first.test'}, {'destination': 'https://second.test'}]),
])
def test_inherited_delegable_subset_is_dimension_specific(permissions, context, dimension, raw):
    p = permissions
    ts = [targets.normalize(dimension, value, str(context.root)) for value in raw]
    parent_policy = policy([])
    parent_policy['delegable'] = {dimension: [targets.token(ts[0])]}
    parent = p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', delegation=parent_policy)
    child = copy.deepcopy(parent_policy)
    child['delegable'][dimension] = [targets.token(ts[1])]
    with pytest.raises(DomainRefusal):
        p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
            purpose='validation', parent=parent, delegation=child)
    child['delegable'][dimension] = []
    assert p.service.authorize(p.w['project'], grantee='executor', targets_list=ts,
        purpose='validation', parent=parent, delegation=child)


def test_argumentless_preparation_hook_remains_compatible(permissions, context):
    from my_harness.adapters.preparation import PreparationCommandRunner
    p = permissions
    cmd = Command(('python', '-c', 'print("synthetic preparation-compatible command")'))
    _, journal, grant, caller, claim, req = post_executor(p, context, cmd)
    # The preparation journal has its own cancellation authority, not a managed command's pinned attempt.
    class SeparateJournal:
        repository, claim = p.repo, journal.claim
        command_process_event = journal.command_process_event
        def cancel_requested(self):
            return False
    runner = PreparationCommandRunner(configuration(context, cmd))
    runner.journal = SeparateJournal()
    result = run_command(context, runner, cmd, journal)
    assert result.passed
