"""P002-T016 (D299, D300): production `RoadmapEffects` for one registered project root.

Reads observe the current SQLite state (accepted knowledge, operational phases and operations, task runs and
commits, sealed reviews, jobs) and Git. Effects reuse the existing typed operations: reviewer jobs for the G12 gap
report and delegated task contracts (`storage/autonomous_jobs.py`), T015 plan proposal/staging and adoption, T014
task admission and commit, T015 check and closure. Every effect is idempotent by its operation key. Delegated plan
adoption and closure verify the sealed `owner_delegated` child again inside the effect's own writer transaction.
Native judge inference is not qualified (D290), so a judge request is created under the parent's delegation and
escalated to the owner.
"""
from contextlib import nullcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine import autonomy
from my_harness.storage import autonomous_runs as store
from my_harness.storage.models import (
    CheckoutLockRow, KnowledgeProjectRow, ManagedCommitRow, ManagedJobRow, ManagedRunRow, PermissionRecordRow,
    PhaseRow, UsageInvocationRow,
)

PENDING_INTEGRATION = 'integration_pending_gates'
# Durable stop class of a failed delegated task run; none of them is readmitted without an explicit owner resume.
def refused_failure(refusal):
    """Failure class of a delegated job by its admission evidence: a cap limit, ended authority, a pause that held
    a new inference, or (without a refusal) an operational failure."""
    if not refusal:
        return {'failure_class': 'operational'}
    kind = {'cap': 'cap', 'authority': 'authority', 'state': 'paused'}.get(refusal.get('kind'), 'cap')
    return {'failure_class': kind, 'cap_reason': refusal['reason']}


# Effect-boundary refusals that mean the delegated authority itself is gone: a durable FAILED stop, never an owner
# question. Every other typed refusal of a delegated effect (stale identity, contract or evidence) asks the owner.
AUTHORITY_REFUSALS = ('delegated_child_missing', 'delegated_run_inactive', 'delegated_child_stale',
                      'delegated_authority_revoked', 'delegated_scope')

TASK_FAILURES = {'STOPPED': 'operational', 'INTERRUPTED': 'operational', 'REFUSED': 'policy', 'BLOCKED': 'blocked',
                 'REVISION_LIMIT': 'revision_limit'}


def scope_view(revision) -> dict:
    """Product meaning bound by an authorization: phases, criteria and requirements by stable identity."""
    members = revision.members.values()
    links = revision.links
    targets = lambda item: sorted(f'{l.target}' for l in links if l.kind == 'criterion_of' and l.source == item)
    return {
        'phases': sorted([m.item_id, m.code, m.content.get('title'), m.content.get('objective'),
                          m.content.get('status'), m.content.get('tag')] for m in members if m.kind == 'phase'),
        'criteria': sorted([m.item_id, m.content.get('statement'), m.content.get('status'), targets(m.item_id)]
                           for m in members if m.kind == 'criterion'),
        'requirements': sorted([m.item_id, m.content.get('title'), m.content.get('statement'), m.content.get('status')]
                               for m in members if m.kind == 'requirement'),
    }


class ManagedRoadmapEffects:
    def __init__(self, repository, project, git, permissions):
        self.repository, self.project, self.git, self.permissions = repository, project, git, permissions
        self.root = str(project.context.root)

    def versions_sha256(self):
        return autonomy.digest(dict(self.project.versions))

    def _prepared(self, session):
        from my_harness.storage.managed import Conflict
        from my_harness.storage.preparation import admit
        try:
            admit(session, self.root, dict(self.project.versions), 'task')
        except (Conflict, ValueError, OSError):
            return False
        return True

    def _compatible(self):
        versions = self.project.versions
        if versions.get('agent_adapter') != 'cli-14':
            return True
        from my_harness.adapters.cli_compatibility import MINIMUM, eligible
        for role in ('reviewer', 'executor'):
            provider, observed = versions.get(f'{role}_provider'), versions.get(f'{role}_cli')
            if provider not in MINIMUM or observed is None or not versions.get(f'{role}_cli_launch_sha256'):
                return False
            if not eligible(provider, observed):
                return False
        return True

    def accepted_revision(self, session):
        from my_harness.services.knowledge_exchange import PhaseKnowledge
        revision = PhaseKnowledge.accepted(session, self.root)
        return {'id': revision.id, 'number': revision.number, 'sha256': revision.revision_sha256} if revision else None

    def readiness(self):
        from my_harness.services.knowledge_exchange import PhaseKnowledge
        from my_harness.storage.documents import unresolved
        with Session(self.repository.engine) as session:
            project = session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == self.root))
            revision = PhaseKnowledge.accepted(session, self.root)
            operational = {row.code: row.status for row in session.scalars(select(PhaseRow).where(
                PhaseRow.root == self.root))}
            roadmap, scope = [], None
            if revision is not None:
                members = revision.members
                for member in sorted((m for m in members.values() if m.kind == 'phase'
                                      and m.content['status'] == 'planned'), key=lambda m: m.code):
                    criteria = sorted(l.source for l in revision.links if l.kind == 'criterion_of'
                                      and l.target == member.item_id and members[l.source].content['status'] == 'active')
                    status = operational.get(member.code)
                    roadmap.append({'code': member.code, 'item': member.item_id, 'criteria': criteria,
                                    'operational': status, 'authorized': status not in ('CLOSED', 'ABANDONED')})
                scope = autonomy.scope_digest(scope_view(revision))
            # The G12 reviewer job itself is not a pending effect of the checkout (it is reported as pending report).
            jobs = list(session.scalars(select(ManagedJobRow.id).join(ManagedRunRow, ManagedRunRow.id == ManagedJobRow.run_id)
                                        .where(ManagedRunRow.root == self.root, ManagedRunRow.purpose != 'autonomy',
                                               ManagedJobRow.status.in_(('QUEUED', 'ACTIVE')))))
            uncertain = list(session.scalars(select(ManagedJobRow.id).join(
                ManagedRunRow, ManagedRunRow.id == ManagedJobRow.run_id).where(
                ManagedRunRow.root == self.root, ManagedJobRow.status == 'RECOVERY_REQUIRED')))
            locks = session.scalar(select(CheckoutLockRow.root).where(CheckoutLockRow.root == self.root))
            intents = session.scalar(select(ManagedCommitRow.operation_id).join(
                ManagedRunRow, ManagedRunRow.id == ManagedCommitRow.run_id).where(
                ManagedRunRow.root == self.root, ManagedCommitRow.status == 'INTENT'))
            active = store.active_run(session, self.root)
            grants = [r.id for r in session.scalars(select(PermissionRecordRow).where(
                PermissionRecordRow.project_id == project, PermissionRecordRow.kind == 'grant'))
                if project and self.permissions.active(session, r)] if project else []
            observation = {
                'project_id': project, 'roadmap': roadmap, 'scope_sha256': scope,
                'revision': {'id': revision.id, 'number': revision.number, 'sha256': revision.revision_sha256}
                if revision else None,
                'prepared': self._prepared(session), 'clients_compatible': self._compatible(),
                'uncertain_writers': uncertain + ([locks] if locks and not jobs else []),
                'pending_effects': jobs + ([intents] if intents else []) + (['documents'] if unresolved(session, self.root) else []),
                'active_run': active.id if active else None,
                'manual_batches': store.active_batches(session, self.root),
                'standing_grants': grants, 'versions_sha256': self.versions_sha256()}
        if self.git is None:  # no configured Git writer: the baseline cannot be observed, so it is not clean
            return {**observation, 'git_clean': False, 'git': {'error': 'git_unavailable'}}
        try:
            evidence = self.git.capture(self.project.context)
            observation['git_clean'] = not evidence.changed_paths
            observation['git'] = {'head': evidence.base_revision, 'fingerprint': evidence.fingerprint}
        except (OSError, ValueError, RuntimeError) as error:
            observation['git_clean'] = False
            observation['git'] = {'error': type(error).__name__}
        return observation

    def usage(self, children, basis=None):
        """Observed usage of the run's delegated managed runs from the existing ledger (D276 caps)."""
        with Session(self.repository.engine) as session:
            return store.observed_usage(session, store.delegated_runs(session, children), basis)

    def revision_items(self, revision):
        """Item identities of the frozen accepted revision the service holds (G12 citation check)."""
        from my_harness.services.knowledge_exchange import PhaseKnowledge
        with Session(self.repository.engine) as session:
            accepted = PhaseKnowledge.accepted(session, self.root, revision['number'])
        if accepted is None or accepted.id != revision['id'] or accepted.revision_sha256 != revision['sha256']:
            return []
        return sorted(accepted.members)

    def writers_settled(self, children, *, session=None):
        with (Session(self.repository.engine) if session is None else nullcontext(session)) as session:
            runs = store.delegated_runs(session, children)
            active = list(session.scalars(select(ManagedJobRow.id).where(
                ManagedJobRow.run_id.in_(runs), ManagedJobRow.status.in_(('ACTIVE', 'RECOVERY_REQUIRED'))))) if runs else []
        return {'settled': not active, 'active': active}

    # --- routing observation ------------------------------------------------------------------------------

    def observe(self):
        from my_harness.services.knowledge_exchange import PhaseKnowledge
        from my_harness.storage import autonomous_jobs as jobs
        from my_harness.storage.models import (PhaseDefinitionRow, PhaseOperationRow, PhaseQuestionRow,
                                               AutonomousReviewRow)
        from my_harness.storage.structured_phases import task_evidence_current
        from my_harness.storage.task_lineage import family
        with Session(self.repository.engine) as session:
            revision = PhaseKnowledge.accepted(session, self.root)
            if revision is None:
                return {'phases': [], 'in_flight': [], 'uncertain': ['accepted_revision_missing']}
            rows = {row.code: row for row in session.scalars(select(PhaseRow).where(PhaseRow.root == self.root))}
            pending = list(session.scalars(select(ManagedJobRow.id).join(ManagedRunRow, ManagedRunRow.id == ManagedJobRow.run_id)
                                           .where(ManagedRunRow.root == self.root, ManagedJobRow.status.in_(('QUEUED', 'ACTIVE')))))
            uncertain = list(session.scalars(select(ManagedJobRow.id).join(ManagedRunRow, ManagedRunRow.id == ManagedJobRow.run_id)
                                             .where(ManagedRunRow.root == self.root, ManagedJobRow.status == 'RECOVERY_REQUIRED')))
            delegated = self._delegated_task_runs(session)
            closed_evidence = {}
            phases = []
            for member in sorted((m for m in revision.members.values() if m.kind == 'phase'
                                  and m.content['status'] == 'planned'), key=lambda m: m.code):
                row = rows.get(member.code)
                entry = {'code': member.code, 'item': member.item_id, 'operational': row.status if row else None,
                         'phase_id': row.id if row else None, 'version': row.version if row else None,
                         'planned': False, 'tasks': [], 'proposal': None, 'check': None, 'questions': [],
                         'closure': None, 'coverage_complete': False}
                phases.append(entry)
                knowledge = row.definition.get('knowledge') if row else None
                if not knowledge:
                    continue
                entry['planned'] = bool(knowledge['planned'])
                criteria = knowledge['criteria']
                entry['coverage_complete'] = entry['planned'] and set(knowledge['coverage']) == set(criteria)
                entry['questions'] = sorted(session.scalars(select(PhaseQuestionRow.id).where(
                    PhaseQuestionRow.phase_id == row.id, PhaseQuestionRow.status == 'OPEN')))
                ops = list(session.scalars(select(PhaseOperationRow).where(PhaseOperationRow.phase_id == row.id)
                                           .order_by(PhaseOperationRow.created_at, PhaseOperationRow.id)))
                latest = lambda kind: next((o for o in reversed(ops) if o.kind == kind), None)
                amended = session.scalar(select(PhaseDefinitionRow.created_at).where(
                    PhaseDefinitionRow.phase_id == row.id).order_by(PhaseDefinitionRow.number.desc()).limit(1))
                check, plan, close = latest('check'), latest('plan'), latest('close')
                if check is not None and check.result is not None:
                    result = check.result.get('result') or {}
                    unmet = [criteria[r['criterion'].split(':', 1)[0]]['item_id']
                             for r in result.get('exit_criteria_results', []) if not r.get('passed')
                             and r['criterion'].split(':', 1)[0] in criteria]
                    classification = (result.get('blocked_classification') if check.status == 'BLOCKED'
                                      else check.result.get('classification'))
                    entry['check'] = {'operation_id': check.id, 'verdict': check.status, 'classification': classification,
                                      'unmet': unmet, 'binding_sha256': check.result.get('binding_sha256'),
                                      'judge_input': check.result.get('judge_input'),
                                      'stale': bool(amended and amended > check.created_at) or (
                                          check.status == 'READY' and row.status not in ('READY_TO_CLOSE', 'CLOSING')),
                                      'ruling_id': self._ruling(session, check.id),
                                      **(self._check_failure(session, check) if check.status == 'FAILED' else {})}
                if plan is not None and plan.result is not None:
                    result = plan.result.get('result') or {}
                    current = (plan.request.get('definition_sha256') == row.definition_sha256)
                    if plan.status == 'PROPOSED' and current and not (amended and amended > plan.created_at):
                        entry['proposal'] = {'operation_id': plan.id, 'status': 'PROPOSED',
                                             'sha256': plan.result.get('proposal_sha256'),
                                             'blocking_questions': bool(result.get('pending')) or any(
                                                 q.get('blocking') for q in result.get('questions', [])),
                                             'choice_required': False,
                                             'after_check': bool(check and plan.created_at > check.created_at)}
                    elif plan.status == 'FAILED' and current:
                        entry['proposal'] = {'operation_id': plan.id, 'status': 'FAILED',
                                             **refused_failure(store.admission_refusal(session, plan.run_id))}
                if row.status == 'CLOSED' and close is not None:
                    successor = (close.result or {}).get('next_phase_id')
                    successor_row = session.get(PhaseRow, successor) if successor else None
                    # The evidence is the exact READY check the closure operation sealed, not the latest check.
                    sealed = session.get(PhaseOperationRow, (close.request or {}).get('check_operation_id') or '')
                    passed_items = self._passed_criteria(sealed, criteria)
                    evidence = sealed is not None and sealed.status == 'READY' and passed_items == {
                        c['item_id'] for c in criteria.values()}
                    entry['closure'] = {'criteria_evidence': evidence,
                                        'successor': successor_row.code if successor_row else None,
                                        'operation_id': close.id, 'check_operation_id': sealed.id if sealed else None}
                    entry['coverage_complete'] = entry['coverage_complete'] and evidence
                    closed_evidence[member.item_id] = {
                        'criteria': passed_items if evidence else set(),
                        'tasks': {knowledge['tasks'][t]['item_id'] for t in row.definition['tasks']
                                  if t in knowledge['tasks']} if evidence else set()}
                for code in row.definition['tasks']:
                    task = knowledge['tasks'].get(code)
                    if task is None:
                        continue
                    # Contract identity: the accepted task, its and the phase's criteria and its relations (D301).
                    version, accepted_criteria = self.contract_identity(revision, code)
                    runs = list(session.scalars(select(ManagedRunRow).where(
                        ManagedRunRow.root == self.root, ManagedRunRow.task_id == code, ManagedRunRow.purpose == 'task')
                        .order_by(ManagedRunRow.created_at.desc(), ManagedRunRow.id.desc())))
                    state, run_id, failure, held = 'pending', None, None, None
                    for run in runs:
                        committed = session.scalar(select(ManagedCommitRow.operation_id).where(
                            ManagedCommitRow.run_id == run.id, ManagedCommitRow.status == 'COMMITTED'))
                        if committed and task_evidence_current(session, row, code, run.id):
                            state, run_id = 'committed', run.id
                            break
                    if state != 'committed':
                        # Only runs this autonomous lineage admitted for this phase and exact contract identity are
                        # its own; any other pending acceptance is foreign and never committed by delegation.
                        own = delegated['task_admission'].get((member.code, code, version), [])
                        mine = [run for run in runs if run.id in own]
                        foreign = [run for run in runs if run.id not in own and run.status == 'ACCEPTANCE_READY'
                                   and run.phase_id == member.code]
                        if mine:
                            latest_run = mine[0]
                            run_id = latest_run.id
                            refusal = store.admission_refusal(session, latest_run.id)
                            held = store.held_review(session, latest_run)
                            if held is not None:
                                state = 'held_review'  # executor work kept; reviewer awaits the explicit resume
                            elif latest_run.status == 'ACCEPTANCE_READY':
                                state = 'accepted' if self._delegation_active(session, latest_run.id) else 'failed'
                                failure = None if state == 'accepted' else 'authority'
                            elif latest_run.status in TASK_FAILURES:
                                state = 'failed'
                                failure = (refused_failure(refusal)['failure_class'] if refusal
                                           else TASK_FAILURES[latest_run.status])
                                if store.continuation_refused(latest_run):
                                    failure = 'review_evidence_changed'
                        elif foreign:
                            state, run_id = 'foreign_acceptance', foreign[0].id
                    contract, review, contract_run, contract_failure = self._contract(
                        session, delegated['task_plan'].get((member.code, code, version), []))
                    paths = review.payload['contract']['allowed_paths'] if contract == 'proposed' else []
                    member_id = task['item_id']
                    entry['tasks'].append({
                        'code': code, 'item': member_id, 'family': family(session, self.root, code),
                        'state': state, 'run_id': run_id, 'version_sha256': version,
                        'depends_on': knowledge['dependencies'].get(code, []), 'contract': contract, 'paths': paths,
                        'plan_text': review.payload.get('plan_text') if contract == 'proposed' else None,
                        'contract_sha256': review.payload.get('contract_sha256') if contract == 'proposed' else None,
                        'title': task['content']['title'],
                        'objective': task['content'].get('expected_result'),
                        'criteria': accepted_criteria, 'contract_run_id': contract_run,
                        **({'contract_failure': contract_failure} if contract_failure else {}),
                        'criterion_items': sorted({member_id, row.definition['knowledge']['phase_item_id'],
                                                   *[c['item_id'] for c in knowledge.get('task_criteria', {}).get(code, {}).values()],
                                                   *[c['item_id'] for c in criteria.values()]}),
                        **({'failure_class': failure} if failure else {}),
                        **({'held': held} if held else {}),
                        **({'cap_reason': store.admission_refusal(session, run_id)['reason']}
                           if failure in ('cap', 'authority', 'paused') else {})})
            return {'phases': phases, 'in_flight': pending, 'uncertain': uncertain,
                    'requirements': self._requirement_coverage(revision, closed_evidence)}

    def _delegated_task_runs(self, session):
        """kind → (phase, task, contract identity) → managed runs (newest first) created by the active autonomous
        run's `task_admission` and `task_plan` children, found through each job's idempotency key."""
        result = {'task_admission': {}, 'task_plan': {}}
        run = store.active_run(session, self.root)
        if run is None:
            return result
        for child in store.children(session, run.id):
            if child.kind not in result:
                continue
            job = session.scalar(select(ManagedJobRow).where(ManagedJobRow.idempotency_key == child.operation_key))
            if job is not None:
                key = (child.subject.get('phase'), child.subject.get('task'), child.subject.get('version_sha256'))
                result[child.kind].setdefault(key, []).insert(0, job.run_id)
        return result

    @staticmethod
    def contract_identity(revision, code):
        """Digest of the accepted inputs that determine a delegated task contract, with its accepted criteria:
        the task item, its criteria (or the phase's when it has none), its phase and dependency/lineage links."""
        from dataclasses import asdict
        task = revision.item('task', code)
        if task is None:
            return None, []
        links, members = revision.links, revision.members
        active = lambda ident: members[ident].content.get('status') == 'active'
        own = sorted((members[l.source] for l in links if l.kind == 'criterion_of' and l.target == task.item_id
                      and active(l.source)), key=lambda m: m.code)
        phases = sorted(l.target for l in links if l.kind == 'part_of' and l.source == task.item_id)
        phase_criteria = sorted((members[l.source] for l in links if l.kind == 'criterion_of' and l.target in phases
                                 and active(l.source)), key=lambda m: m.code)
        identity = autonomy.digest({
            'task': asdict(task), 'criteria': [asdict(m) for m in own], 'phases': phases,
            'phase_criteria': [asdict(m) for m in phase_criteria],
            'depends_on': sorted(l.target for l in links if l.kind == 'depends_on' and l.source == task.item_id),
            'replaces': sorted(l.target for l in links if l.kind == 'replaces' and l.source == task.item_id)})
        return identity, [m.content['statement'] for m in (own or phase_criteria)]

    @staticmethod
    def _contract(session, runs):
        """Durable outcome of this run's latest contract job for the identity: missing, pending, proposed, refused,
        failed (with its admission or operational class) or uncertain; never a silent `missing` after a job ran."""
        from my_harness.storage.models import AutonomousReviewRow
        if not runs:
            return 'missing', None, None, None
        run_id = runs[0]
        job = session.scalar(select(ManagedJobRow).where(ManagedJobRow.run_id == run_id)
                             .order_by(ManagedJobRow.id.desc()).limit(1))
        if job.status in ('QUEUED', 'ACTIVE'):
            return 'pending', None, run_id, None
        if job.status == 'RECOVERY_REQUIRED':
            return 'uncertain', None, run_id, 'uncertain'
        review = session.scalar(select(AutonomousReviewRow).where(
            AutonomousReviewRow.record_key == 'task_plan:' + job.idempotency_key))
        if review is not None:
            return review.payload['status'], review, run_id, None
        return 'failed', None, run_id, refused_failure(store.admission_refusal(session, run_id))['failure_class']

    @staticmethod
    def _passed_criteria(check, criteria):
        if check is None or not check.result:
            return set()
        results = (check.result.get('result') or {}).get('exit_criteria_results', [])
        codes = {r['criterion'].split(':', 1)[0] for r in results if r.get('passed')}
        return {criteria[code]['item_id'] for code in codes if code in criteria}

    @staticmethod
    def _requirement_coverage(revision, closed):
        """Each active requirement of the accepted revision is covered only by a CLOSED phase's sealed READY
        evidence: the phase addresses it, a passed criterion of the phase is a criterion of it, or a task of that
        closed plan addresses it. Wording or planning alone never counts."""
        members, links = revision.members, revision.links
        result = []
        for item in sorted(m.item_id for m in members.values()
                           if m.kind == 'requirement' and m.content.get('status') == 'active'):
            sources = {l.source for l in links if l.target == item and l.kind in ('addresses', 'criterion_of')}
            covered = any(phase in sources or evidence['criteria'] & sources or evidence['tasks'] & sources
                          for phase, evidence in closed.items() if evidence['criteria'])
            result.append({'item': item, 'covered': covered})
        return result

    @staticmethod
    def _check_failure(session, check):
        return refused_failure(store.admission_refusal(session, check.run_id))

    def _delegation_active(self, session, run_id):
        return not self.permissions.delegated_inactive(session, run_id)

    @staticmethod
    def _ruling(session, operation_id):
        """The validated T009 ruling of an autonomous judge request about this operation, if any."""
        from my_harness.storage.models import JudgeRequestRow, JudgeRulingRow
        for request in session.scalars(select(JudgeRequestRow).where(JudgeRequestRow.subject.like('roadmap:%'))
                                       .order_by(JudgeRequestRow.created_at.desc())):
            if (request.payload.get('evidence') or {}).get('check_operation_id') != operation_id:
                continue
            ruling = session.scalar(select(JudgeRulingRow).where(JudgeRulingRow.request_id == request.id))
            if ruling is not None and ruling.status == 'VALIDATED':
                return ruling.id
        return None

    # --- effects (idempotent by the sealed operation key) ---------------------------------------------------

    def _phase(self, code):
        with Session(self.repository.engine) as session:
            row = session.scalar(select(PhaseRow).where(PhaseRow.root == self.root, PhaseRow.code == code))
            if row is None:
                raise autonomy.AutonomyRefusal('phase_not_operational', phase=code)
            return row.id, row.version

    @staticmethod
    def _queued(job):
        return {'status': 'pending', 'detail': {'jobs': [job.id], 'run_id': job.run_id}}

    def _call(self, operation):
        """Typed refusals of the reused operations become a durable owner stop, never a retry."""
        from my_harness.storage.managed import Conflict
        try:
            return operation()
        except autonomy.AutonomyRefusal:
            raise
        except (Conflict, ValueError, LookupError) as error:
            return {'status': 'owner_required', 'detail': {'refusal': str(error)[:300]}}

    def gap_report(self, revision):
        """Queue the G12 reviewer job for this frozen revision once; `None` while it runs (sealed on settlement)."""
        from my_harness.services.knowledge_exchange import PhaseKnowledge
        from my_harness.storage import autonomous_jobs as jobs
        from my_harness.core.engine.autonomy import product_policy
        version = product_policy().readiness_version
        key = jobs.readiness_key(self.root, revision, version)
        with Session(self.repository.engine) as session:
            existing = jobs.job(session, key)
            accepted = PhaseKnowledge.accepted(session, self.root, revision['number'])
        if existing is not None:
            if existing.status in ('QUEUED', 'ACTIVE'):
                return None
            raise autonomy.AutonomyRefusal('gap_report_failed', job=existing.id)
        items = sorted(m.item_id for m in accepted.members.values() if m.kind in ('phase', 'criterion', 'requirement'))
        jobs.queue(self.repository, self.project.context, dict(self.project.versions), kind='readiness', key=key,
                   phase_id='ROADMAP', payload={'revision': revision, 'version': version, 'item_ids': items})
        return None

    def plan_task(self, action, key):
        from my_harness.storage import autonomous_jobs as jobs
        task = action['task_view']
        revision = self.readiness()['revision']
        return self._call(lambda: self._queued(jobs.queue(
            self.repository, self.project.context, dict(self.project.versions), kind='task_plan', key=key,
            phase_id=action['phase'], payload={
                'revision': revision, 'item_ids': task['criterion_items'], 'task_id': task['code'],
                'phase_id': action['phase'], 'title': task['title'], 'criteria': task['criteria'],
                'objective': task['objective'], 'version_sha256': task['version_sha256'],
                'inputs': {'task_id': task['code'], 'phase_id': action['phase'], 'criteria': task['criteria']}})))

    def propose_plan(self, action, key):
        from my_harness.storage.structured_phases import StructuredPhases
        phase_id, version = self._phase(action['phase'])
        return self._call(lambda: self._queued(StructuredPhases(self.repository).propose(
            self.project.context, phase_id, version, key=key, versions=dict(self.project.versions))))

    def prepare_adoption(self, action):
        """Read-side preparation before the child is sealed: stage the untrusted proposal as a draft (T015) and
        compute the exact preview. Nothing is adopted; the child then binds these values."""
        return self._call(lambda: self._prepare_adoption(action))

    def _prepare_adoption(self, action):
        from my_harness.storage.structured_phases import StructuredPhases
        phases = StructuredPhases(self.repository)
        phase_id, version = self._phase(action['phase'])
        proposal = action['proposal']
        staged = phases.stage(self.project.context, phase_id, proposal['operation_id'], version,
                              proposal_sha256=proposal['sha256'])
        _, current = self._phase(action['phase'])
        shown = phases.preview(self.project.context, action['phase'], phase_id=phase_id, expected_version=current,
                               **staged)
        return {'phase_id': phase_id, 'expected_version': current, 'draft_id': staged['draft_id'],
                'coverage': staged['coverage'], 'preview_sha256': shown['preview_sha256'],
                'revision_id': shown['revision']['id'], 'proposal_operation_id': proposal['operation_id'],
                'proposal_sha256': proposal['sha256']}

    def adopt_plan(self, action, child, key):
        """Adopts exactly what the child was sealed for; the child is verified inside T015's adoption transaction."""
        from my_harness.storage.structured_phases import StructuredPhases
        bound = child['subject']

        def adopt():
            StructuredPhases(self.repository).adopt(
                self.project.context, action['phase'], preview_sha256=bound['preview_sha256'], key=key,
                reason=f"Delegated plan adoption ({child['rule']}, child {child['id']})", confirmed=False,
                delegated=self.delegation(child, 'plan_adoption', phase=action['phase']),
                phase_id=bound['phase_id'], expected_version=bound['expected_version'], draft_id=bound['draft_id'],
                coverage=bound['coverage'])
            return {'status': 'done', 'detail': {'phase_id': bound['phase_id'], 'preview_sha256': bound['preview_sha256']}}
        return self._call(adopt)

    def _bounded(self, operation):
        """`_call` for an effect whose T014 transaction verifies the delegated child: authority refusals stop the run
        (FAILED); stale identity, contract or evidence is a typed owner stop with its code, and nothing was created."""
        try:
            return self._call(operation)
        except autonomy.AutonomyRefusal as error:
            if error.code in AUTHORITY_REFUSALS:
                raise
            return {'status': 'owner_required', 'detail': {'refusal': error.code, **{
                k: v for k, v in error.detail.items() if isinstance(v, (str, int, type(None)))}}}

    def commit_task(self, action, child, key):
        """Commit of reviewed, accepted content (harness_deterministic under the child); T014's reference guard
        rechecks the delegated authority at the Git effect."""
        return self._bounded(lambda: self._commit(action, child, key))

    def admit_task(self, action, child, key):
        """T014 admission of exactly the sealed contract: the plan text must still parse to its sealed digest, and
        T014's queue transaction verifies the child, the contract digest and the current identity again."""
        import json
        from my_harness.core.engine.planning import deterministic_task
        try:
            parsed = json.loads(deterministic_task(self.project.context, action['task'], action['phase'],
                                                   action.get('plan_text') or ''))
        except (ValueError, TypeError):
            parsed = None
        if parsed is None or autonomy.digest(parsed) != action.get('contract_sha256') or \
                child['subject'].get('contract_sha256') != action.get('contract_sha256') or \
                self._current_identity(action['task']) != child['subject'].get('version_sha256'):
            return {'status': 'owner_required', 'detail': {'refusal': 'task_contract_mismatch'}}
        def verify(session, request):
            store.verify_task_admission(session, self.permissions, child['id'], root=self.root,
                                        phase=action['phase'], task=action['task'], request=request,
                                        identity=self._identity_in(session, action['task']))
        return self._bounded(lambda: self._queued(self.repository.submit(
            self.project.context, action['task'], action['phase'], action['plan_text'], dict(self.project.versions),
            key=key, delegated_authorization=child['permission_record_id'], delegated=verify)))

    def resume_review(self, action, key):
        """Explicit continuation of a pause-held review: T014's revalidation (no `retry_executor`) of the same run,
        with the frozen contract and the executor's work. T014's resume transaction verifies the held evidence, the
        delegated authority, contract and identity, a settled writer and the checkout against the evidence."""
        held = action['held']
        checkout = self._checkout()

        def verify(session, run):
            store.verify_held_review(session, self.permissions, run, root=self.root, held=held,
                                     identity=self._identity_in(session, run.task_id), checkout=checkout,
                                     running=True)
        return self._bounded(lambda: self._queued(self.repository.resume(
            held['run_id'], key=key, expected_version=held['version'], retry_executor=False, delegated=verify,
            expected_evidence=held['evidence'])))

    def verify_held_review(self, held):
        """None when the held review may continue now; otherwise the refusal code (used by the owner resume)."""
        checkout = self._checkout()
        with Session(self.repository.engine) as session:
            run = session.get(ManagedRunRow, held['run_id'])
            try:
                store.verify_held_review(session, self.permissions, run, root=self.root, held=held,
                                         identity=self._identity_in(session, run.task_id if run is not None else None),
                                         checkout=checkout)
            except autonomy.AutonomyRefusal as error:
                return error.code
        return None

    def _checkout(self):
        """Current content evidence of the checkout (the fields T014 freezes in a review cycle), or None."""
        if self.git is None:
            return None
        try:
            evidence = self.git.capture(self.project.context)
        except (OSError, ValueError, RuntimeError):
            return None
        return {'base_revision': evidence.base_revision, 'fingerprint': evidence.fingerprint,
                'changed_paths': list(evidence.changed_paths)}

    def _commit(self, action, child, key):
        with Session(self.repository.engine) as session:
            current = self._current_identity(action['task'])
            own = self._delegated_task_runs(session)['task_admission'].get(
                (action['phase'], action['task'], current), [])
            if (action.get('version_sha256') != current or action['run_id'] not in own
                    or not self._delegation_active(session, action['run_id'])):
                return {'status': 'owner_required', 'detail': {'refusal': 'acceptance_not_delegated'}}
        record = self.repository.get_run(action['run_id'])
        if record.status != 'ACCEPTANCE_READY':
            return {'status': 'owner_required', 'detail': {'refusal': 'acceptance_not_ready'}}

        def verify(session, run):
            store.verify_task_commit(session, self.permissions, child['id'], root=self.root, phase=action['phase'],
                                     task=action['task'], managed_run=run,
                                     identity=self._identity_in(session, action['task']))
        return self._queued(self.repository.submit_commit(action['run_id'], key=key, expected_version=record.version,
                                                          delegated=verify))

    def _current_identity(self, code):
        with Session(self.repository.engine) as session:
            return self._identity_in(session, code)

    def _identity_in(self, session, code):
        """Contract identity from the accepted knowledge as read by `session` (inside T014's transaction when called
        from a delegated check)."""
        from my_harness.services.knowledge_exchange import PhaseKnowledge
        if code is None:
            return None
        revision = PhaseKnowledge.accepted(session, self.root)
        return self.contract_identity(revision, code)[0] if revision else None

    def check_phase(self, action, key):
        from my_harness.storage.phases import PhaseRepository
        phase_id, version = self._phase(action['phase'])
        return self._call(lambda: self._queued(PhaseRepository(self.repository).submit_check(
            self.project.context, phase_id, version, key=key, versions=dict(self.project.versions))))

    def close_phase(self, action, child, key):
        from my_harness.storage.phases import PhaseRepository
        phase_id, version = self._phase(action['phase'])
        return self._call(lambda: self._queued(PhaseRepository(self.repository).submit_close(
            self.project.context, phase_id, version, key=key, versions=dict(self.project.versions),
            binding_sha256=action['binding_sha256'], ttl_seconds=3600, tag_kind=self.project.tag_kind, git=self.git,
            reason=f"Delegated closure ({child['rule']}, child {child['id']})",
            delegated=self.delegation(child, 'phase_closure', phase=action['phase'], binding=action['binding_sha256']))))

    def judge(self, action, key):
        """A T009 request bound to the active parent's delegation contract (`roadmap:<parent>` subject, canonical
        subject digest). Native judge inference is not qualified (D290), so the result is always an owner stop that
        carries the exact request and ruling; no ruling adopts, closes or replaces READY."""
        from my_harness.services.domain_operations import DomainOperations
        from my_harness.services.judge import JudgeService
        from my_harness.storage.frozen_context import ContextRepository
        if not action.get('judge_input') or not action.get('parent'):
            return {'status': 'owner_required', 'detail': {'reason': 'judge_input_unavailable'}}
        revision = self.readiness()['revision']
        versions = dict(self.project.versions)
        client = versions.get('judge_provider') or versions.get('reviewer_provider') or 'codex'

        def create():
            snapshot = ContextRepository(self.repository.engine).prepare_for(
                self.project.context, [action['phase_item']], client=client, revision=revision['number'])
            judges = JudgeService(DomainOperations(self.repository.engine, authorizations=self.permissions))
            state = judges.create(self.project.context, versions, duty=action['duty'],
                                  subject=f"roadmap:{action['parent']}:{action['judge_identity'][:40]}",
                                  inputs=action['judge_input'], evidence={'check_operation_id': action['operation_id']},
                                  snapshot_id=snapshot)
            ruling = state.get('ruling') or {}
            return {'status': 'owner_required', 'detail': {
                'reason': 'judge_escalated' if ruling else 'judge_inference_unqualified',
                'judge_request_id': state.get('id'), 'ruling_id': ruling.get('id'),
                'ruling_status': ruling.get('status')}}
        return self._call(create)

    def delegation(self, child, kind, **subject):
        """Provenance and the effect-boundary check that T015 calls inside its own writer transaction."""
        from my_harness.storage.autonomous_runs import verify_child
        permissions = self.permissions

        def verify(session, **bound):
            return verify_child(session, permissions, child['id'], kind=kind, root=self.root, **subject, **bound)
        return {'child_id': child['id'], 'rule': child['rule'], 'authorization_id': child['authorization_id'],
                'verify': verify}
