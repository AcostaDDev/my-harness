"""T009 judge service. Explicit consumer interface; no scheduler, grant/adoption effect or productive delegation."""
from dataclasses import asdict, replace
import json
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import EFFORTS
from my_harness.core.engine import judge as core, tool_bridge
from my_harness.core.engine.contracts import AgentRequest, Attempt, Selection, context_snapshot, freeze
from my_harness.core.engine.domain_catalogue import CATALOGUE, digest
from my_harness.core.engine.prompts import builtin_catalog
from my_harness.i18n import tr
from my_harness.services.domain_operations import DomainRefusal
from my_harness.storage.frozen_context import ContextRepository, load
from my_harness.storage.models import (JudgeRequestRow as Request, JudgeInvocationRow as Binding,
    JudgeRulingRow as Ruling, JudgeDecisionLinkRow as Link, DomainCommandRow, ManagedAttemptRow,
    KnowledgeProjectRow, KnowledgeItemRow, KnowledgeRevisionMemberRow, ManagedJobRow, WorkflowOperationRow)
from my_harness.storage.operation_journal import InvocationOperation, now, record_event

CONTINUATIONS = {'permission': 'await_permission_application', 'planning_choice': 'await_choice_consumer',
                 'spec_gap': 'await_proposal_adoption', 'blocked_check': 'await_proposal_adoption'}


def view(row):
    return {'id': row.id, 'request_id': row.request_id, 'status': row.status, **row.payload}


class JudgeService:
    def __init__(self, operations, *, qualifications=None):
        self.operations, self.engine = operations, operations.engine
        self.qualifications = tuple(tool_bridge.NATIVE if qualifications is None else qualifications)

    def _policy(self, session, project_id, duty, subject):
        provider = self.operations.authorizations
        if not hasattr(provider, 'judge_policy'):
            return None
        value = provider.judge_policy(session, project_id, duty, subject)
        if value is not None:
            # A future T016 provider supplies explicit bounds/identity. No default autonomy values here.
            required = ('id', 'revision', 'policy_version', 'reconsiderations', 'active', 'duties', 'effective_grants')
            if (any(k not in value for k in required) or type(value['reconsiderations']) is not int or
                    value['reconsiderations'] < 0 or type(value['revision']) is not int or
                    value['revision'] < 1 or type(value['active']) is not bool or
                    not isinstance(value['id'], str) or not value['id'].strip() or
                    not isinstance(value['policy_version'], str) or not value['policy_version'].strip() or
                    not isinstance(value['effective_grants'], list) or not isinstance(value['duties'], list) or
                    any(d not in core.DUTIES for d in value['duties'])):
                raise ValueError(tr('judge.invalid'))
            value = json.loads(freeze(value))
        return value

    def _current(self, session, row):
        policy = self._policy(session, row.project_id, row.duty, row.subject)
        if policy != row.payload['policy'] or not policy or not policy['active']:
            raise ValueError(tr('judge.delegation_changed'))
        return policy

    def create(self, context, versions, *, duty, subject, inputs, evidence, snapshot_id, reconsider=False):
        core.input_check(duty, inputs)
        if (type(reconsider) is not bool or not isinstance(subject, str) or not 1 <= len(subject) <= 100 or not isinstance(evidence, dict) or
                len(evidence) > 50 or any(not isinstance(k, str) or not 1 <= len(k) <= 100 or
                    not isinstance(v, str) or not v.strip() for k, v in evidence.items()) or
                len(freeze({'inputs': inputs, 'evidence': evidence}).encode()) > 32768):
            raise ValueError(tr('judge.invalid'))
        with Session(self.engine) as session, session.begin():
            session.execute(text('DELETE FROM judge_requests WHERE 0'))
            snapshot, data = load(session, snapshot_id)
            project = session.get(KnowledgeProjectRow, snapshot.project_id)
            if project.root != str(context.root):
                raise ValueError(tr('judge.invalid'))
            policy = self._policy(session, project.id, duty, subject)
            # The trusted consumer supplies the stable subject across broadened/rephrased requests.
            equivalent = digest({'project': project.id, 'duty': duty, 'subject': subject})
            evidence_sha = digest({'evidence': evidence, 'context_sha256': snapshot.sha256})
            prior = list(session.scalars(select(Request).where(Request.project_id == project.id,
                Request.equivalence_sha256 == equivalent).order_by(Request.created_at, Request.id)))
            repeated = next((r for r in prior if r.evidence_sha256 == evidence_sha), None)
            if repeated:
                return self._read(session, repeated, replayed=True)
            reason = core.eligibility(duty, inputs, policy)
            for field, kind in (('requirement_ids', 'requirement'), ('criterion_ids', 'criterion')):
                if field in inputs:
                    known = set(session.scalars(select(KnowledgeItemRow.id).join(KnowledgeRevisionMemberRow,
                        KnowledgeRevisionMemberRow.item_id == KnowledgeItemRow.id).where(
                        KnowledgeRevisionMemberRow.revision_id == snapshot.revision_id, KnowledgeItemRow.kind == kind)))
                    if not set(inputs[field]) <= known:
                        reason = reason or 'missing_reference'
            if prior:
                previous_bindings = [session.get(Binding, r.id) for r in prior]
                previous_rulings = [session.scalar(select(Ruling).where(Ruling.request_id == r.id)) for r in prior]
                if any(b and (r is None or r.status == 'UNCERTAIN') for b, r in zip(previous_bindings, previous_rulings)):
                    reason = 'unresolved_prior_inference'
                elif not reconsider:
                    reason = 'new_decision_required'
                elif not policy or sum(bool(b) or r is None for b, r in zip(previous_bindings, previous_rulings)) > policy['reconsiderations']:
                    reason = 'reconsideration_bound'
            if not evidence:
                reason = reason or 'missing_evidence'
            profile = {k: versions.get('judge_' + k) for k in ('provider', 'model', 'effort', 'cli')}
            if not all(profile.values()):
                reason = reason or 'profile_required'
            if profile['provider'] and profile['provider'] != data['client']:
                raise ValueError(tr('judge.invalid'))
            row = Request(id=str(uuid4()), project_id=project.id, snapshot_id=snapshot_id, duty=duty, subject=subject,
                          equivalence_sha256=equivalent, evidence_sha256=evidence_sha,
                          payload={'format': core.FORMAT, 'inputs': inputs, 'evidence': evidence,
                                   'policy': policy, 'profile': profile, 'revision_id': snapshot.revision_id,
                                   'prompt_version': 'judge-' + duty.replace('_', '-') + '-1',
                                   'template_sha256': builtin_catalog()['judge-' + duty.replace('_', '-')].sha256}, created_at=now())
            session.add(row)
            session.flush()
            record_event(session, kind='judge.requested', dedupe_key='judge:request:' + row.id,
                         root=project.root, payload={'request_id': row.id, 'duty': duty,
                                                    'evidence_sha256': evidence_sha})
            if reason:
                self._ruling(session, row, 'ESCALATED', {'reason': reason, 'continuation': 'owner'})
            return self._read(session, row)

    def _read(self, session, row, *, replayed=False):
        ruling = session.scalar(select(Ruling).where(Ruling.request_id == row.id))
        binding = session.get(Binding, row.id)
        links = session.scalars(select(Link).where(Link.ruling_id == ruling.id)).all() if ruling else []
        return {'id': row.id, 'duty': row.duty, 'payload': row.payload, 'snapshot_id': row.snapshot_id,
                'ruling': view(ruling) if ruling else None, 'replayed': replayed,
                'invocation_id': binding.invocation_id if binding else None,
                'decision_links': [{'id': l.id, 'decision_id': l.decision_id, 'revision_id': l.revision_id} for l in links],
                'continuation': ruling.payload['continuation'] if ruling else ('observe_existing_invocation' if binding else 'prepare')}

    def list(self, project_id, *, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError(tr('judge.invalid'))
        from sqlalchemy import func
        with Session(self.engine) as session:
            if session.get(KnowledgeProjectRow, project_id) is None:
                raise LookupError(tr('judge.not_found'))
            rows = session.scalars(select(Request).where(Request.project_id == project_id)
                .order_by(Request.created_at, Request.id).offset(offset).limit(limit)).all()
            total = session.scalar(select(func.count()).select_from(Request).where(Request.project_id == project_id))
            return {'items': [self._read(session, row) for row in rows], 'offset': offset, 'limit': limit, 'total': total}

    def read(self, project_id, request_id):
        with Session(self.engine) as session:
            row = session.get(Request, request_id)
            if row is None or row.project_id != project_id:
                raise LookupError(tr('judge.not_found'))
            return self._read(session, row)

    def assemble(self, project_id, request_id, context, adapter, *, qualifications=None, language=None):
        """Trusted consumer supplies managed.job_language(claim); start rechecks the frozen pair. No launch here."""
        qualifications = self.qualifications if qualifications is None else qualifications
        with Session(self.engine) as session:
            row = session.get(Request, request_id)
            if row is None or row.project_id != project_id:
                raise LookupError(tr('judge.not_found'))
            state = self._read(session, row)
            if state['ruling'] or state['invocation_id']:
                raise ValueError(tr('judge.no_progress'))
            self._current(session, row)
            versions = {'judge_' + k: v for k, v in row.payload['profile'].items()}
            profile = core.admit_profile(adapter.agents, versions, efforts=EFFORTS, qualifications=qualifications)
            contexts = ContextRepository(self.engine)
            prompt, snapshot = contexts.render(project_id, row.snapshot_id, builtin_catalog(),
                'judge-' + row.duty.replace('_', '-'), {'INPUT_JSON': freeze(row.payload)}, context, language)
            snap = json.loads(snapshot)
            snap['judge'] = {'request_id': row.id, 'duty': row.duty, 'request_sha256': digest(row.payload),
                             'profile': asdict(profile), 'prompt_version': row.payload['prompt_version']}
            request = AgentRequest(str(uuid4()), 'judge', Selection(profile.model, profile.effort, 'owner_selected'),
                                   prompt, None, context_snapshot(context), prompt_snapshot_json=freeze(snap))
            cell = tool_bridge.qualification(qualifications, profile.provider, profile.cli_version, 'judge', profile.evidence)
            return tool_bridge.policy(request, core.refs(row.duty), cell)

    def seal(self, session, operation, request, versions):
        marker = json.loads(request.prompt_snapshot_json)['judge']
        row = session.get(Request, marker['request_id'])
        if (row is None or marker['duty'] != row.duty or marker['request_sha256'] != digest(row.payload) or
                operation.refs.get('judge_request_id') != row.id or session.get(Binding, row.id) or
                session.scalar(select(Ruling.id).where(Ruling.request_id == row.id))):
            raise ValueError(tr('judge.invalid'))
        self._current(session, row)
        others = session.scalars(select(Request).where(Request.project_id == row.project_id,
            Request.equivalence_sha256 == row.equivalence_sha256, Request.id != row.id)).all()
        for other in others:
            prior_binding = session.get(Binding, other.id)
            prior_ruling = session.scalar(select(Ruling).where(Ruling.request_id == other.id))
            if prior_binding and (prior_ruling is None or prior_ruling.status == 'UNCERTAIN'):
                raise ValueError(tr('judge.no_progress'))
        from my_harness.core.engine.prompts import render_attempt
        from my_harness.core.engine.serialization import restore_context
        context_row, context_data = load(session, row.snapshot_id, row.project_id)
        catalog = builtin_catalog()
        name = 'judge-' + row.duty.replace('_', '-')
        if catalog[name].sha256 != row.payload['template_sha256']:
            raise ValueError(tr('judge.invalid'))
        expected_prompt, expected_snapshot = render_attempt(catalog, name, {'INPUT_JSON': freeze(row.payload)},
            restore_context(request.context_json), session.get(ManagedJobRow, operation.job_id).language_context,
            canonical={'id': context_row.id, 'sha256': context_row.sha256, 'data': context_data})
        actual = json.loads(request.prompt_snapshot_json)
        if request.prompt != expected_prompt or any(actual.get(k) != v for k, v in json.loads(expected_snapshot).items()):
            raise ValueError(tr('judge.invalid'))
        frozen = row.payload['profile']
        profile = marker['profile']
        cell = tool_bridge.qualification(self.qualifications, profile['provider'], profile['cli_version'],
                                        'judge', profile['evidence'])
        if cell.provenance != profile['provenance']:
            raise ValueError(tr('judge.invalid'))
        snapshot = json.loads(request.prompt_snapshot_json)
        if (any(versions.get('judge_' + k) != v for k, v in frozen.items()) or
                request.selection.model != frozen['model'] or request.selection.effort != frozen['effort'] or
                snapshot['canonical_context']['id'] != row.snapshot_id or
                snapshot['canonical_context']['revision_id'] != row.payload['revision_id'] or
                marker['prompt_version'] != row.payload['prompt_version'] or
                marker['profile']['provider'] != frozen['provider'] or
                marker['profile']['model'] != frozen['model'] or marker['profile']['effort'] != frozen['effort'] or
                marker['profile']['cli_version'] != frozen['cli']):
            raise ValueError(tr('judge.invalid'))
        session.add(Binding(request_id=row.id, attempt_id=request.id, invocation_id=operation.invocation_id,
                            operation_id=operation.id, created_at=now()))
        session.flush()

    def start(self, managed, claim, request, *, thread_id, key):
        history = managed.get_run(claim.run_id).history
        request = replace(request, task_json=history.task_json)
        row = json.loads(request.prompt_snapshot_json)['judge']
        return managed.agent_started(claim, history, request,
            InvocationOperation(thread_id, key, {'judge_request_id': row['request_id']}), judge=self)

    def record_result(self, managed, claim, request, result):
        history = managed.get_run(claim.run_id).history
        previous = next((a for a in history.attempts if a.request.id == request.id), None)
        if previous is not None:
            if previous != Attempt(request, result):
                raise ValueError(tr('judge.invalid'))
            return
        managed.checkpoint(claim, replace(history, attempts=history.attempts + (Attempt(request, result),)), 'judge', judge=self)

    def submit(self, call):
        """Handler inside the shared DomainOperations transaction. This records a candidate, not a terminal ruling."""
        call.authorize()
        binding = call.session.scalar(select(Binding).where(Binding.invocation_id == call.caller.invocation_id))
        row = call.session.get(Request, binding.request_id) if binding else None
        if (row is None or row.project_id != call.project_id or call.entry.id != f'judge.{row.duty}.submit'):
            raise DomainRefusal('caller_not_allowed')
        self._current(call.session, row)
        value = core.candidate(row.duty, row.payload['inputs'], row.payload['evidence'], row.payload['policy'],
                               freeze(call.arguments['candidate']))
        return {'request_id': row.id, 'ruling_id': None, 'status': 'CANDIDATE', 'continuation': 'await_invocation_result',
                'candidate': value}

    def _ruling(self, session, row, status, payload, binding=None):
        prior = session.scalar(select(Ruling).where(Ruling.request_id == row.id))
        if prior:
            return prior
        origin = {'kind': 'owner_delegated', 'parent_id': row.payload['policy']['id'],
                  'parent_revision': row.payload['policy']['revision'],
                  'policy_version': row.payload['policy']['policy_version']} if row.payload['policy'] else None
        result = Ruling(id=str(uuid4()), request_id=row.id, status=status,
            payload={**payload, 'origin': origin, 'actor': 'judge' if binding else 'harness',
                     'proposal_only': True, 'operation_id': binding.operation_id if binding else None,
                     'attempt_id': binding.attempt_id if binding else None,
                     'invocation_id': binding.invocation_id if binding else None}, created_at=now())
        session.add(result)
        session.flush()
        project = session.get(KnowledgeProjectRow, row.project_id)
        operation = session.get(WorkflowOperationRow, binding.operation_id) if binding else None
        record_event(session, kind='judge.ruled', dedupe_key='judge:ruling:' + row.id, root=project.root,
            thread_id=operation.thread_id if operation else None,
            operation_id=binding.operation_id if binding else None,
            invocation_id=binding.invocation_id if binding else None,
            payload={'request_id': row.id, 'ruling_id': result.id, 'status': status,
                     'continuation': payload['continuation']})
        return result

    def settle(self, session, attempt):
        binding = session.scalar(select(Binding).where(Binding.attempt_id == attempt.id))
        if binding is None:
            raise ValueError(tr('judge.invalid'))
        row = session.get(Request, binding.request_id)
        native = json.loads(attempt.result_json)
        raw = native.get('payload_json')
        payload = {'continuation': 'owner', 'native_result_sha256': digest(native),
                   'raw_reference': {'attempt_id': attempt.id, 'field': 'result_json'}}
        status = 'ESCALATED'
        try:
            metadata = json.loads(native.get('metadata_json') or '{}')
        except (ValueError, TypeError):
            metadata = {}
        malformed_output = (native.get('status') == 'invalid' and native.get('terminal_observed') is True
            and type(native.get('exit_code')) is int and native['exit_code'] == 0
            and native.get('error') == 'CLI invalid' and isinstance(metadata, dict)
            and metadata.get('malformed_output') is True)
        if malformed_output:
            payload['reason'] = 'malformed_or_invalid_candidate'
        elif (native.get('status') not in (None, 'complete', 'completed') or not native.get('terminal_observed') or
                type(native.get('exit_code')) is not int or native['exit_code'] != 0 or native.get('error')):
            failure = native.get('status') or 'provider_failure'
            status = 'ESCALATED' if failure == 'refused' else 'FAILED'
            payload.update(reason=failure, continuation='owner' if status == 'ESCALATED' else 'operational_stop')
        else:
            try:
                self._current(session, row)
                value = core.candidate(row.duty, row.payload['inputs'], row.payload['evidence'], row.payload['policy'], raw)
                submitted = session.scalars(select(DomainCommandRow).where(
                    DomainCommandRow.operation_id == f'judge.{row.duty}.submit', DomainCommandRow.outcome == 'ACCEPTED',
                    DomainCommandRow.scope == 'invocation:' + binding.invocation_id)).all()
                if any(c.result['candidate'] != value for c in submitted):
                    raise ValueError(tr('judge.invalid'))
                payload['candidate'] = value
                payload['reason'] = value['outcome']
                if value['outcome'] not in ('escalate', 'abstain'):
                    status = 'VALIDATED'
                    payload['continuation'] = CONTINUATIONS[row.duty]
            except (ValueError, TypeError, KeyError):
                payload['reason'] = 'malformed_or_invalid_candidate'
        return self._ruling(session, row, status, payload, binding)

    def reconcile(self, project_id, request_id):
        """Observe shared journal recovery only. Never launch or infer from lease expiry."""
        with Session(self.engine) as session, session.begin():
            session.execute(text('DELETE FROM judge_rulings WHERE 0'))
            row = session.get(Request, request_id)
            if row is None or row.project_id != project_id:
                raise LookupError(tr('judge.not_found'))
            binding = session.get(Binding, row.id)
            if binding and not session.scalar(select(Ruling.id).where(Ruling.request_id == row.id)):
                attempt = session.get(ManagedAttemptRow, binding.attempt_id)
                operation = session.get(WorkflowOperationRow, binding.operation_id)
                if attempt.result_json:
                    self.settle(session, attempt)
                elif operation.status in ('UNCERTAIN', 'ABANDONED', 'FAILED'):
                    self._ruling(session, row, 'UNCERTAIN', {'reason': 'inference_uncertain',
                                 'continuation': 'recovery_required'}, binding)
            return self._read(session, row, replayed=True)

    def link_decision(self, caller, project_id, ruling_id, decision_id, revision_number, *, key):
        if caller.knowledge_project_id != project_id:
            raise DomainRefusal('caller_not_allowed')
        entry = CATALOGUE.current('judge.decision.link')
        return self.operations.execute(caller, entry.ref, {'ruling_id': ruling_id, 'decision_id': decision_id,
                                        'revision': revision_number}, key).body()

    def link(self, call):
        call.authorize()
        session = call.session
        ruling = session.get(Ruling, call.arguments['ruling_id'])
        row = session.get(Request, ruling.request_id) if ruling else None
        if row is None or row.project_id != call.project_id:
            raise DomainRefusal('not_found')
        revision = call.knowledge.revision(call.project_id, call.arguments['revision'])
        member = revision.members.get(call.arguments['decision_id'])
        if member is None or member.kind != 'decision':
            raise ValueError(tr('judge.invalid'))
        prior = session.scalar(select(Link).where(Link.ruling_id == ruling.id, Link.decision_id == member.item_id,
                                                  Link.revision_id == revision.id))
        if prior:
            return {'link_id': prior.id}
        link = Link(id=str(uuid4()), ruling_id=ruling.id, decision_id=member.item_id, revision_id=revision.id, created_at=now())
        session.add(link)
        session.flush()
        record_event(session, kind='judge.decision_linked', dedupe_key='judge:link:' + link.id,
            root=session.get(KnowledgeProjectRow, call.project_id).root,
            payload={'ruling_id': ruling.id, 'decision_id': member.item_id, 'revision_id': revision.id})
        return {'link_id': link.id}
