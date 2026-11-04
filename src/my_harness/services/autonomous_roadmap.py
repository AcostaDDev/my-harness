"""P002-T016 (D276, D299): autonomous roadmap runs over the existing managed authority.

The service owns readiness, the start preview, the owner-confirmed seal, the per-project controls and the body of
the roadmap graph step. The graph (orchestration/roadmap.py, reached only through the runtime composition root)
holds routing progress; SQLite holds authority, state, bounds, questions and evidence. Effects go through a typed
`RoadmapEffects` port bound to one root; every delegated effect first seals a concrete `owner_delegated` child and
its bound consumption, then runs as a sealed journal operation with a deterministic key (D282, D287).

Gates G11, G12 and G17 arrive through `GatePolicy`. With the product policy they are pending, so readiness never
returns READY and a confirmation is refused before anything is sealed.
"""
from typing import Callable, Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine import autonomy
from my_harness.core.engine.autonomy import AutonomyRefusal as Refusal
from my_harness.storage import autonomous_runs as store
from my_harness.storage.graph_continuations import GraphContinuationRepository
from my_harness.storage.models import GraphThreadRow, WorkflowOperationRow
from my_harness.storage.permissions import actor

INFERENCE = autonomy.INFERENCE_ACTIONS
CHILD_KINDS = {'propose_plan': 'plan_proposal', 'adopt_plan': 'plan_adoption', 'plan_task': 'task_plan',
               'admit_task': 'task_admission', 'commit_task': 'task_commit', 'check_phase': 'phase_check',
               'close_phase': 'phase_closure', 'judge': 'judge_request'}


class RoadmapEffects(Protocol):
    """Typed effects for one project root. Reads observe SQLite/Git; effects are idempotent by `key`.

    Each effect returns {'status': 'done' | 'owner_required' | 'uncertain' | <failure class>, 'detail': {...}}."""

    def readiness(self) -> dict: ...
    def accepted_revision(self, session) -> dict | None: ...
    def observe(self) -> dict: ...
    def versions_sha256(self) -> str: ...
    def usage(self, children: list) -> dict: ...
    def writers_settled(self, children: list, *, session=None) -> dict: ...
    def revision_items(self, revision: Mapping) -> list: ...
    def gap_report(self, revision: Mapping) -> dict | None: ...
    def propose_plan(self, action: Mapping, key: str) -> dict: ...
    def plan_task(self, action: Mapping, key: str) -> dict: ...
    def commit_task(self, action: Mapping, child: Mapping, key: str) -> dict: ...
    def prepare_adoption(self, action: Mapping) -> dict: ...
    def adopt_plan(self, action: Mapping, child: Mapping, key: str) -> dict: ...
    def admit_task(self, action: Mapping, child: Mapping, key: str) -> dict: ...
    def check_phase(self, action: Mapping, key: str) -> dict: ...
    def close_phase(self, action: Mapping, child: Mapping, key: str) -> dict: ...
    def judge(self, action: Mapping, key: str) -> dict: ...
    def resume_review(self, action: Mapping, key: str) -> dict: ...
    def verify_held_review(self, held: Mapping) -> str | None: ...


class AutonomousRoadmap:
    def __init__(self, managed, permissions, effects: Callable[[str], RoadmapEffects], *, journal,
                 graphs: Callable | None = None, policy: autonomy.GatePolicy | None = None):
        self.managed, self.permissions, self.effects = managed, permissions, effects
        self.journal, self.policy = journal, policy or autonomy.product_policy()
        self._graph_factory, self._graphs = graphs, None

    # --- readiness, preview and confirmation (FL01) ------------------------------------------------------------

    def readiness(self, root, request: Mapping, *, own_run: str | None = None, generate: bool = True) -> dict:
        """FL01 readiness. The reviewer is asked only after every structural check passes, once per frozen revision:
        its report is sealed and reused (a confirmation never generates another, `generate=False`)."""
        effects = self.effects(str(root))
        observation = effects.readiness()
        if own_run is not None and observation.get('active_run') == own_run:
            observation = {**observation, 'active_run': None}
        try:
            autonomy.validate_bounds(request.get('bounds'))
            bounds_error = None
        except Refusal as error:
            bounds_error = error.code
        checks = autonomy.readiness_checks(observation, bounds_error)
        sealed, gap_error, context = None, None, None
        revision = observation.get('revision')
        if all(c['passed'] for c in checks) and 'G12' not in self.policy.pending() and revision:
            sealed, gap_error = self._gap_report(root, observation, effects, generate)
            context = {'revision': revision['number'], 'items': effects.revision_items(revision),
                       'answers': self._answers(root, revision)}
        report = sealed.payload.get('report') if sealed is not None else None
        if sealed is not None and sealed.payload.get('status') != 'reported':
            gap_error = 'gap_report_' + sealed.payload.get('status', 'invalid')
        verdict = autonomy.readiness_verdict(checks, report, self.policy, context, gap_error)
        gaps = [{**gap, 'gap_sha256': autonomy.gap_sha256(gap)} for gap in (report or {}).get('gaps', [])]
        return {'checks': checks, **verdict, 'gates': self.policy.stamp(), 'observation': observation,
                'default_bounds': dict(self.policy.default_bounds) if self.policy.default_bounds else None,
                'gap_report_sha256': sealed.sha256 if sealed is not None else None, 'gaps': gaps}

    def _answers(self, root, revision):
        with Session(self.managed.engine) as session:
            return sorted({a.gap_sha256 for a in store.gap_answers(session, root, revision['id'])})

    def _gap_report(self, root, observation, effects, generate):
        """(sealed record or None, error code or None) for the observed frozen revision."""
        revision = observation['revision']
        with Session(self.managed.engine) as session:
            sealed = self._plain_report(store.gap_report(session, root, revision['id'], self.policy.readiness_version))
        if sealed is not None or not generate:
            return sealed, None if sealed is not None else 'gap_report_unsealed'
        try:
            produced = effects.gap_report(revision)
        except Refusal as error:  # provider/integration failure: no verdict and no automatic retry here
            return None, error.code
        if produced is None:
            return None, 'gap_report_pending'
        try:
            payload = {'status': 'reported', 'report': autonomy.validate_gap_report(produced),
                       'readiness_version': self.policy.readiness_version}
        except Refusal:
            payload = {'status': 'malformed', 'readiness_version': self.policy.readiness_version}
        with self.managed._write() as session:
            return self._plain_report(store.seal_gap_report(
                session, root=root, project=observation['project_id'], revision=revision,
                readiness_version=self.policy.readiness_version, payload=payload, now=self.managed._now())), None

    @staticmethod
    def _plain_report(row):
        from types import SimpleNamespace
        return None if row is None else SimpleNamespace(payload=dict(row.payload), sha256=row.sha256)

    def answer_gap(self, root, *, gap_sha256, text, key):
        """Owner answer to an `owner_answer_required` gap of the sealed report of the current frozen revision."""
        if not isinstance(text, str) or not text.strip() or not isinstance(key, str) or not key or len(key) > 200:
            raise Refusal('answer_invalid')
        observation = self.effects(str(root)).readiness()
        revision = observation.get('revision')
        if not revision:
            raise Refusal('accepted_revision_required')
        with self.managed._write() as session:
            sealed = store.gap_report(session, root, revision['id'], self.policy.readiness_version)
            gaps = (sealed.payload.get('report') or {}).get('gaps', []) if sealed else []
            if not any(autonomy.gap_sha256(g) == gap_sha256 and g['classification'] == 'owner_answer_required'
                       for g in gaps):
                raise Refusal('gap_not_answerable')
            row = store.answer_gap(session, root=root, project=observation['project_id'], revision=revision,
                                   gap_sha256=gap_sha256, text=text.strip(), key=key, actor=actor(),
                                   now=self.managed._now())
            return {'id': row.id, 'gap_sha256': row.gap_sha256, 'revision_id': row.revision_id,
                    'origin': row.origin, 'created_at': row.created_at}

    def preview(self, root, request: Mapping, *, lineage: str | None = None, generate: bool = True) -> dict:
        own, version = None, None
        if lineage is not None:
            with Session(self.managed.engine) as session:
                run = session.scalar(select(store.Run).where(store.Run.lineage_id == lineage, store.Run.root == str(root)))
                if run is None:
                    raise LookupError(lineage)
                if run.status not in ('LIMIT_REACHED', 'WAITING_FOR_OWNER', 'PAUSED'):
                    raise Refusal('revision_requires_stopped_run')
                own, version = run.id, run.version
        report = self.readiness(root, request, own_run=own, generate=generate)
        observation = report['observation']
        if set(request) - {'bounds', 'caps', 'delegation'}:
            raise Refusal('request_invalid')
        caps = autonomy.validate_caps(request.get('caps') or {})
        delegation = autonomy.validate_delegation(request.get('delegation'))
        roadmap = observation.get('roadmap') or []
        acknowledgement = ({'version': self.policy.acknowledgement_version,
                            'sha256': autonomy.digest(dict(self.policy.acknowledgement)),
                            'text': dict(self.policy.acknowledgement)}
                           if self.policy.acknowledgement else {'version': None, 'sha256': None, 'text': None})
        shown = {'format': autonomy.PREVIEW_FORMAT, 'root': str(root), 'lineage_id': lineage,
                 **({'run_version': version} if version is not None else {}),
                 'project_id': observation.get('project_id'), 'revision': observation.get('revision'),
                 'scope': {'phases': [p['code'] for p in roadmap if p['authorized']],
                           'roadmap': [p['code'] for p in roadmap],
                           'scope_sha256': observation.get('scope_sha256')},
                 'delegation': delegation, 'bounds': request.get('bounds'), 'caps': caps,
                 'standing_grants': observation.get('standing_grants') or [],
                 'acknowledgement': acknowledgement, 'policy': self.policy.stamp(),
                 'configuration': {'versions_sha256': observation.get('versions_sha256')},
                 'git': observation.get('git'),
                 'readiness': {'verdict': report['verdict'], 'checks': report['checks'],
                               'gap_report_sha256': report['gap_report_sha256']}}
        shown['preview_sha256'] = autonomy.preview_sha256(shown)
        return {**shown, 'blocking': report.get('blocking', []), 'gaps': report['gaps'],
                'default_bounds': report['default_bounds'], 'pending_gates': list(self.policy.pending())}

    def confirm(self, root, request, *, preview_sha256, key, reason, confirmed, acknowledgement_version):
        """Seal an `owner_confirmed` authorization for the exact preview, then create and start its run."""
        return self._seal(root, request, preview_sha256=preview_sha256, key=key, reason=reason, confirmed=confirmed,
                          acknowledgement_version=acknowledgement_version, lineage=None)

    def revision_preview(self, root, run_id, request, *, expected_version):
        with Session(self.managed.engine) as session:
            run = self._owned(session, root, run_id)
            if run.version != expected_version:
                raise Refusal('run_version_stale')
            lineage = run.lineage_id
        preview = self.preview(root, request, lineage=lineage)
        if preview['run_version'] != expected_version:
            raise Refusal('run_version_stale')
        return preview

    def revise(self, root, run_id, request, *, preview_sha256, key, reason, confirmed, acknowledgement_version):
        """A new authorization revision (raised bounds or an owner amendment); consumption is never reset."""
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            if run.root != str(root):
                raise LookupError(run_id)
            lineage = run.lineage_id
        return self._seal(root, request, preview_sha256=preview_sha256, key=key, reason=reason, confirmed=confirmed,
                          acknowledgement_version=acknowledgement_version, lineage=lineage)

    def _seal(self, root, request, *, preview_sha256, key, reason, confirmed, acknowledgement_version, lineage):
        if confirmed is not True or not isinstance(reason, str) or not reason.strip():
            raise Refusal('explicit_owner_confirmation_required')
        if not isinstance(key, str) or not key or len(key) > 200:
            raise Refusal('idempotency_key_required')
        marker = autonomy.digest({'request': dict(request), 'preview_sha256': preview_sha256, 'reason': reason,
                                  'acknowledgement_version': acknowledgement_version, 'lineage': lineage})
        with Session(self.managed.engine) as session:
            existing = session.scalar(select(store.Authorization).where(store.Authorization.idempotency_key == key))
            if existing is not None:
                if existing.root != str(root) or existing.request_sha256 != marker:
                    raise Refusal('idempotency_conflict')
                run = session.scalar(select(store.Run).where(store.Run.lineage_id == existing.lineage_id))
                return self.reconcile_run(run.id)
        pending = self.policy.pending()
        if pending:
            raise Refusal('gates_pending', gates=list(pending))
        if acknowledgement_version != self.policy.acknowledgement_version:
            raise Refusal('acknowledgement_required')
        # Reuse the sealed gap report of the preview and revalidate its bindings; never generate another one.
        shown = self.preview(root, request, lineage=lineage, generate=False)
        if shown['preview_sha256'] != preview_sha256:
            raise Refusal('preview_stale')
        if shown['readiness']['verdict'] != 'READY':
            raise Refusal('readiness_not_ready', blocking=shown['blocking'])
        bounds = autonomy.validate_bounds(request['bounds'])
        now = self.managed._now()
        sealed = {k: v for k, v in shown.items() if k not in ('blocking', 'pending_gates', 'gaps', 'default_bounds')}
        effects = self.effects(str(root))
        with self.managed._write() as session:
            existing = session.scalar(select(store.Authorization).where(store.Authorization.idempotency_key == key))
            if existing is not None:
                if existing.root != str(root) or existing.request_sha256 != marker:
                    raise Refusal('idempotency_conflict')
                run_id = session.scalar(select(store.Run.id).where(store.Run.lineage_id == existing.lineage_id))
            else:
                project = store.project_id(session, root)
                if (project is None or project != shown['project_id']
                        or shown['revision'] != effects.accepted_revision(session)):
                    raise Refusal('preview_stale')
                if store.active_batches(session, root):
                    raise Refusal('manual_batch_active')
                current = store.active_run(session, root)
                previous = store.latest(session, lineage) if lineage else None
                if lineage is None and current is not None:
                    raise Refusal('autonomous_run_active')
                if lineage is not None:
                    if current is None or current.lineage_id != lineage or current.status not in (
                            'LIMIT_REACHED', 'WAITING_FOR_OWNER', 'PAUSED'):
                        raise Refusal('revision_requires_stopped_run')
                    if current.version != shown['run_version']:
                        raise Refusal('preview_stale')
                    if not autonomy.raised(previous.preview['bounds'], bounds):
                        raise Refusal('bounds_cannot_decrease')
                ident = store.preview_id(key)
                parent = self.permissions.roadmap_parent(session, project, authorization_id=ident,
                    phases=sealed['scope']['phases'], tiers=sealed['delegation']['tiers'],
                    delegation=self._judge_delegation(sealed, bounds, 1 if previous is None else previous.number + 1),
                    actor=actor())
                row, _ = store.seal(session, root=root, project=project, lineage_id=lineage or ident,
                                    previous=previous, key=key, request_sha256=marker, preview=sealed, actor=actor(),
                                    reason=reason.strip(), policy=self.policy.stamp(), permission_record_id=parent,
                                    now=now)
                if lineage is None:
                    run_id = store.create_run(session, root=root, authorization_row=row, now=now).id
                else:
                    self.permissions.end_roadmap(session, project, previous.permission_record_id,
                                                 reason='superseded by revision %d' % row.number, actor=actor())
                    current.authorization_id = row.id
                    run_id = current.id
                    for question in store.open_questions(session, current.id):
                        question.status, question.version, question.updated_at = 'SUPERSEDED', question.version + 1, now
                    store.move(session, current, (current.status,), 'RUNNING', reason='authorization_revised',
                               detail={'authorization_number': row.number, 'awaiting_graph': True}, now=now)
        return self.reconcile_run(run_id)

    @staticmethod
    def _judge_delegation(sealed, bounds, number):
        """T009 delegation contract of the parent: enabled duties, the confirmed reconsideration bound and the
        duration ceiling; no delegable grant dimensions (judge rulings never grant here)."""
        duties = sealed['delegation']['duties']
        if not duties:
            return None
        from my_harness.core.engine import domain_policy
        ceiling = sealed['delegation']['duration_ceiling']
        duration = ({'kind': 'operation', 'seconds': None} if ceiling['kind'] == 'operation'
                    else {'kind': 'time_limited', 'seconds': ceiling['seconds']})
        return {'revision': number, 'policy_version': domain_policy.POLICY_VERSION,
                'reconsiderations': bounds['judge_reconsiderations'], 'active': True, 'duties': list(duties),
                'effective_grants': [], 'compound_safe': False, 'delegable': {}, 'duration_ceiling': duration,
                'permitted_alternatives': [], 'intent_ids': []}

    # --- graph lifecycle -----------------------------------------------------------------------------------------

    def graphs(self):
        """Roadmap graph operations, built on first use so reads never import the graph runtime."""
        if self._graphs is None:
            if self._graph_factory is None:
                raise Refusal('graph_runtime_unavailable')
            self._graphs = self._graph_factory(self)
        return self._graphs

    def reconcile_run(self, run_id):
        """Starts the graph of a sealed run whose creation was interrupted, or resumes one a revision unblocked;
        never creates a second run or authorization."""
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            started = (run.detail or {}).get('graph_started')
            awaiting = (run.detail or {}).get('awaiting_graph')
            status, thread = run.status, run.thread_id
        if status == 'RUNNING' and not started:
            graphs = self.graphs()
            result = graphs.start_or_status(run_id, thread)
            self._mark(run_id, {'graph_started': True})
            self._sync(run_id, result)
        elif status == 'RUNNING' and awaiting:
            self._mark(run_id, {'awaiting_graph': False})
            self._sync(run_id, self.graphs().resume(thread))
        return self.status_by_id(run_id)

    def _mark(self, run_id, values):
        with self.managed._write() as session:
            run = store.run_by_id(session, run_id)
            run.detail = {**(run.detail or {}), **values}

    def _sync(self, run_id, result):
        """Graph-level stops become durable run stops; the run row stays the authority of state."""
        if result is None or result.status in ('WAITING', 'COMPLETED', 'REVOKED', 'CANCELLED'):
            return
        target = 'RECOVERY_REQUIRED' if result.status in ('RECOVERY_REQUIRED', 'RUNNING') else 'FAILED'
        reason = {'QUARANTINED': 'graph_quarantined', 'RUNNING': 'graph_writer_unconfirmed'}.get(
            result.status, result.reason or 'graph_failed')
        with self.managed._write() as session:
            run = store.run_by_id(session, run_id)
            if run.status == 'RUNNING':
                store.move(session, run, ('RUNNING',), target, reason=reason,
                           detail={'graph': {'status': result.status, 'detail': dict(result.detail or {})}},
                           now=self.managed._now())

    def journal_port(self, run_id):
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            return run.thread_id, run.root, {'kind': 'autonomous_authorization', 'id': run.authorization_id}

    # --- the roadmap step (body of the single graph loop node) -------------------------------------------------

    def advance(self, run_id, *, key: Callable, perform: Callable) -> dict:
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            auth = store.authorization(session, run.authorization_id)
            status, root = run.status, run.root
            preview = auth.preview
        if status in autonomy.TERMINAL:
            return {'route': 'end'}
        if status != 'RUNNING':
            return {'route': 'hold', 'wait': {'kind': 'owner', 'status': status}}
        effects = self.effects(root)
        try:
            stop = self._guard(run_id, effects)
            if stop:
                return self._stop(run_id, stop)
            view = self._acknowledged(run_id, effects.observe())
            action = autonomy.decide(view, preview['scope']['phases'])
            return self._act(run_id, effects, view, action, key, perform)
        except Refusal as error:
            return self._stop(run_id, {'status': 'FAILED', 'reason': error.code, 'detail': dict(error.detail)})

    def _acknowledged(self, run_id, view):
        """Failed delegated task runs the owner acknowledged with an explicit resume may be readmitted once each."""
        with Session(self.managed.engine) as session:
            seen = set((store.run_by_id(session, run_id).detail or {}).get('acknowledged_failures') or [])
        for phase in view.get('phases', []):
            for task in phase.get('tasks', []):
                if task.get('state') == 'failed' and task.get('run_id') in seen:
                    task['retry'] = True
                if task.get('contract') == 'failed' and task.get('contract_run_id') in seen:
                    task['contract_retry'] = True
        return view

    def _guard(self, run_id, effects):
        """Fresh authority, scope, policy and configuration before any decision (FL03 load-and-guard)."""
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            auth = store.authorization(session, run.authorization_id)
            latest = store.latest(session, run.lineage_id)
            parent_active = self._parent_active(session, auth)
        if latest.id != auth.id or not parent_active:
            return {'status': 'FAILED', 'reason': 'authority_inactive', 'detail': {}}
        if auth.policy.get('version') != self.policy.version or self.policy.pending():
            return {'status': 'FAILED', 'reason': 'policy_changed', 'detail': {'sealed': auth.policy.get('version')}}
        observation = effects.readiness()
        if observation.get('scope_sha256') != auth.preview['scope']['scope_sha256']:
            return {'status': 'WAITING_FOR_OWNER', 'reason': 'scope_amended',
                    'question': {'kind': 'scope_amended', 'subject': {'scope_sha256': observation.get('scope_sha256')}}}
        if effects.versions_sha256() != auth.preview['configuration']['versions_sha256']:
            return {'status': 'FAILED', 'reason': 'configuration_changed', 'detail': {}}
        return None

    def _parent_active(self, session, auth):
        parent = self.permissions.get(session, auth.project_id, auth.permission_record_id, 'authorization')
        return self.permissions.active(session, parent)

    def _stop(self, run_id, stop):
        now = self.managed._now()
        with self.managed._write() as session:
            run = store.run_by_id(session, run_id)
            if run.status != 'RUNNING':
                return {'route': 'end' if run.status in autonomy.TERMINAL else 'hold'}
            question = stop.get('question')
            refs = {}
            if question:
                row = store.ask(session, run, kind=question['kind'], subject=question['subject'],
                                binding=self._binding(session, run), now=now)
                refs = {'question_id': row.id}
            store.move(session, run, ('RUNNING',), stop['status'], reason=stop['reason'],
                       detail={'stop': stop.get('detail') or {}, **refs}, refs=refs, now=now)
            terminal = stop['status'] in autonomy.TERMINAL
        return {'route': 'end' if terminal else 'hold', 'wait': {'kind': 'owner', 'status': stop['status']}}

    def _binding(self, session, run):
        """The authorization and accepted revision observed under the same lock as the answer."""
        auth = store.authorization(session, run.authorization_id)
        return {'authorization_id': auth.id, 'authorization_number': auth.number,
                'revision': self.effects(run.root).accepted_revision(session)}

    def _act(self, run_id, effects, view, action, key, perform):
        kind = action['action']
        if kind == 'stop':
            return self._stop(run_id, action)
        if kind == 'fail':
            return self._stop(run_id, autonomy.failure_stop(action['kind'], {'phase': action.get('phase'),
                                                                              'classification': action.get('classification')}))
        if kind == 'wait_jobs':
            return {'route': 'hold', 'wait': {'kind': 'jobs', 'jobs': action['jobs']}}
        if kind == 'wait_owner':
            subject = {k: v for k, v in action.items() if k not in ('action', 'kind')}
            return self._stop(run_id, {'status': 'WAITING_FOR_OWNER', 'reason': 'owner_' + action['kind'],
                                       'question': {'kind': action['kind'], 'subject': subject}})
        if kind == 'complete':
            return self._complete(run_id, view)
        if kind == 'resume_review':
            return self._continue_review(run_id, effects, action, key, perform)
        return self._delegate(run_id, effects, view, action, key, perform)

    def _continue_review(self, run_id, effects, action, key, perform):
        """One continuation of a pause-held review in the same T014 run under its existing admission child: no new
        child, no task attempt or no-progress consumption. Its key names the persisted refusal, so a replay or a
        later step reconciles instead of queueing again; caps are still checked at the reviewer's admission."""
        refs = {'phase': action['phase'], 'task': action['task'], 'run_id': action['run_id'],
                'operation_id': f"held:{action['held']['refusal_event_id']}"}
        op_key = key('resume_review', refs)
        record = perform('resume_review', 'sealed_effect', refs, lambda: dict(effects.resume_review(action, op_key)))
        return self._outcome(run_id, 'resume_review', refs, record)

    def _complete(self, run_id, view):
        with Session(self.managed.engine) as session:
            auth = store.authorization(session, store.run_by_id(session, run_id).authorization_id)
            scope, roadmap = auth.preview['scope']['phases'], auth.preview['scope']['roadmap']
        result = autonomy.completion(view, scope, roadmap)
        if not result['completed']:
            return self._stop(run_id, {'status': 'FAILED', 'reason': 'completion_evidence_incomplete',
                                       'detail': {'missing': result['missing']}})
        return self._stop(run_id, {'status': 'COMPLETED', 'reason': 'roadmap_completed',
                                   'detail': {'phases': scope}})

    def _progress(self, view, action):
        phase = next((p for p in view['phases'] if p['code'] == action.get('phase')), {})
        check = phase.get('check') or {}
        # Canonical family identity, deduplicated: splitting a task into members of one family is not progress.
        families = lambda tasks: sorted({min(t['family']) for t in tasks})
        return {'phase_item': phase.get('item'), 'planned_families': families(phase.get('tasks') or []),
                'committed_families': families([t for t in phase.get('tasks') or [] if t['state'] == 'committed']),
                'check_classification': [check.get('verdict'), check.get('classification')] if check else None,
                'unmet_criteria': check.get('unmet') or [], 'open_questions': phase.get('questions') or [],
                'action': action['action'],
                'subject': min(action['family']) if action.get('family') else action.get('duty')}

    def _bound(self, view, action):
        """(bound, identity for consumption, identities counted) for the action, or None when unbounded."""
        phase = next((p for p in view['phases'] if p['code'] == action.get('phase')), {})
        item = phase.get('item') or action.get('phase')
        if action['action'] == 'admit_task':
            return 'task_attempts', action['task'], action['family']
        if action['action'] == 'propose_plan' and action.get('remediation'):
            ident = f"{item}:{action['remediation']}"
            return 'remediation_per_cause', ident, [ident]
        if action['action'] == 'propose_plan' and action.get('replan'):
            return 'replacement_plans', item, [item]
        if action['action'] == 'judge':
            # Canonical subject (G11): duty, phase identity and cause; never the operation that raised it, so a
            # new operation on the same subject shares the reconsideration budget.
            ident = autonomy.judge_subject(action['duty'], item, action.get('cause'))
            return 'judge_reconsiderations', ident, [ident]
        return None

    def _delegate(self, run_id, effects, view, action, key, perform):
        name = action['action']
        refs = {k: str(action[k]) for k in ('phase', 'task', 'duty', 'operation_id', 'run_id') if action.get(k)}
        if action.get('remediation'):
            refs['cause'] = action['remediation'][:40]
        op_key = key(name, refs)
        now = self.managed._now()
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            auth = store.authorization(session, run.authorization_id)
            sealed_children = store.children(session, run_id)
            bounds = auth.preview['bounds']
            caps = auth.preview['caps']
            existing_child = session.scalar(select(store.Child).where(store.Child.operation_key == op_key))
        if existing_child is None:
            if name in INFERENCE:
                stop = autonomy.cap_stop(caps, effects.usage(
                    [{**c.subject, 'operation_key': c.operation_key} for c in sealed_children],
                    basis=(caps.get('valuation') or {}).get('basis')), now)
                if stop:
                    return self._stop(run_id, {'status': 'LIMIT_REACHED', 'reason': stop['reason'], 'detail': stop})
            bounded = self._bound(view, action)
            fingerprint = self.policy.fingerprint(self._progress(view, action))
            # Adoption binds the exact staged proposal, preview and revision before its child is sealed.
            prepared = effects.prepare_adoption(action) if name == 'adopt_plan' else None
            if prepared and prepared.get('status'):
                return self._stop(run_id, {'status': 'WAITING_FOR_OWNER', 'reason': 'owner_adoption_unavailable',
                                           'detail': prepared.get('detail') or {},
                                           'question': {'kind': 'adoption_unavailable', 'subject': refs}})
            with Session(self.managed.engine) as session:
                limits = []
                if bounded:
                    bound, _, counted = bounded
                    limits.append((bound, store.consumed(session, run.root, bound, counted)))
                limits.append(('no_progress', store.consumed(session, run.root, 'no_progress', fingerprint)))
            for bound, used in limits:
                if used >= bounds[bound]:
                    return self._stop(run_id, {'status': 'LIMIT_REACHED', 'reason': 'bound_' + bound,
                                               'detail': {'bound': bound, 'consumed': used, 'limit': bounds[bound]}})
            with self.managed._write() as session:
                run = store.run_by_id(session, run_id)
                if run.status != 'RUNNING':
                    return {'route': 'hold'}
                permission = None
                if name == 'admit_task':
                    auth = store.authorization(session, run.authorization_id)
                    permission = self.permissions.task_child(session, auth.project_id,
                        parent=auth.permission_record_id, phase=action['phase'], task=action['task'],
                        paths=action['paths'], rule='roadmap.task_admission@1')
                subject = {**refs, 'action': name, **({'family': action['family']} if action.get('family') else {}),
                           **({'paths': action['paths']} if action.get('paths') else {}),
                           **({'binding_sha256': action['binding_sha256']} if action.get('binding_sha256') else {}),
                           **({'proposal_sha256': action['proposal']['sha256']} if action.get('proposal') else {}),
                           **({'judge_identity': bounded[1]} if name == 'judge' else {})}
                if action.get('task_view'):
                    subject['version_sha256'] = action['task_view']['version_sha256']
                elif action.get('version_sha256'):
                    subject['version_sha256'] = action['version_sha256']
                if action.get('contract_sha256'):
                    subject['contract_sha256'] = action['contract_sha256']
                if prepared:
                    subject.update(prepared)
                child_row = store.child(session, run, kind=CHILD_KINDS[name], key=op_key, subject=subject,
                                        rule=f'roadmap.{CHILD_KINDS[name]}@1', permission_record_id=permission, now=now,
                                        ruling_id=action.get('ruling_id'))
                if bounded:
                    bound, identity, _ = bounded
                    if bound != 'judge_reconsiderations' or self._judged_before(session, run_id, op_key, identity):
                        store.consume(session, run, bound=bound, identity=identity, key=f'{bound}:{op_key}',
                                      evidence={'child_id': child_row.id, 'action': name}, now=now)
                store.consume(session, run, bound='no_progress', identity=fingerprint, key=f'no_progress:{op_key}',
                              evidence={'child_id': child_row.id, 'action': name,
                                        'fingerprint_version': self.policy.fingerprint_version}, now=now)
                child = {'id': child_row.id, 'kind': child_row.kind, 'rule': child_row.rule,
                         'permission_record_id': permission, 'authorization_id': run.authorization_id,
                         'origin': 'owner_delegated', 'subject': subject, 'ruling_id': child_row.ruling_id}
        else:
            child = {'id': existing_child.id, 'kind': existing_child.kind, 'rule': existing_child.rule,
                     'permission_record_id': existing_child.permission_record_id,
                     'authorization_id': existing_child.authorization_id, 'origin': existing_child.origin,
                     'subject': existing_child.subject, 'ruling_id': existing_child.ruling_id}
        if name == 'judge':  # bind the request to the parent's delegation contract and the canonical subject
            action = {**action, 'parent': self._parent(run_id), 'judge_identity': child['subject']['judge_identity']}
        effect = {'propose_plan': lambda: effects.propose_plan(action, op_key),
                  'plan_task': lambda: effects.plan_task(action, op_key),
                  'commit_task': lambda: effects.commit_task(action, child, op_key),
                  'adopt_plan': lambda: effects.adopt_plan(action, child, op_key),
                  'admit_task': lambda: effects.admit_task(action, child, op_key),
                  'check_phase': lambda: effects.check_phase(action, op_key),
                  'close_phase': lambda: effects.close_phase(action, child, op_key),
                  'judge': lambda: effects.judge(action, op_key)}[name]
        record = perform(name, 'sealed_effect', refs, lambda: dict(effect()))
        return self._outcome(run_id, name, refs, record)

    def _outcome(self, run_id, name, refs, record):
        if record.state == 'ABANDONED':
            return {'route': 'continue'}  # owner-reconciled uncertainty: nothing reissued under this key
        outcome = dict(record.result or {})
        result = outcome.get('status')
        if result == 'done':
            return {'route': 'continue'}
        if result == 'pending':
            return {'route': 'hold', 'wait': {'kind': 'jobs', 'jobs': outcome.get('detail', {}).get('jobs', [])}}
        stop = autonomy.failure_stop(result or 'operational', {'action': name, **refs, **(outcome.get('detail') or {})})
        if stop['status'] == 'WAITING_FOR_OWNER':
            stop['question'] = {'kind': stop['reason'].removeprefix('owner_'), 'subject': {'action': name, **refs}}
        return self._stop(run_id, stop)

    def _parent(self, run_id):
        with Session(self.managed.engine) as session:
            run = store.run_by_id(session, run_id)
            return store.authorization(session, run.authorization_id).permission_record_id

    @staticmethod
    def _judged_before(session, run_id, op_key, identity):
        """A reconsideration is a later judge request for an equivalent subject (the first one is not counted)."""
        previous = session.scalars(select(store.Child).join(store.Run, store.Run.id == store.Child.run_id).where(
            store.Child.kind == 'judge_request', store.Child.operation_key != op_key,
            store.Run.root == session.get(store.Run, run_id).root))
        return any(c.subject.get('judge_identity') == identity for c in previous)

    # --- owner controls (FL02, FL12, FL13) -----------------------------------------------------------------------

    def _owned(self, session, root, run_id):
        run = store.run_by_id(session, run_id)
        if run.root != str(root):
            raise LookupError(run_id)
        return run

    def status(self, root):
        with Session(self.managed.engine) as session:
            run = session.scalar(select(store.Run).where(store.Run.root == str(root))
                                 .order_by(store.Run.created_at.desc(), store.Run.id).limit(1))
            return None if run is None else self._view(session, run)

    def status_for(self, root, run_id):
        with Session(self.managed.engine) as session:
            return self._view(session, self._owned(session, root, run_id))

    def status_by_id(self, run_id):
        with Session(self.managed.engine) as session:
            return self._view(session, store.run_by_id(session, run_id))

    def _view(self, session, run):
        current = store.authorization(session, run.authorization_id)
        consumption = {}
        for row in session.scalars(select(store.Consumption).where(store.Consumption.root == run.root)):
            consumption.setdefault(row.bound, {}).setdefault(row.identity, 0)
            consumption[row.bound][row.identity] += 1
        return store.view(run, current, questions_rows=store.questions(session, run.id),
                          children_rows=store.children(session, run.id), consumption=consumption)

    def events(self, root, run_id, *, after=0, limit=100):
        with Session(self.managed.engine) as session:
            self._owned(session, root, run_id)
            return [{'sequence': e.id, 'kind': e.kind, 'dedupe_key': e.dedupe_key, 'refs': e.refs,
                     'payload': e.payload, 'created_at': e.created_at}
                    for e in store.events(session, run_id, after, limit)]

    def answer(self, root, run_id, question_id, *, expected_version, answer, key):
        """Owner answer bound to the current question version, revision and authority; it does not resume."""
        if not isinstance(answer, Mapping) or not isinstance(answer.get('text'), str) or not answer['text'].strip():
            raise Refusal('answer_invalid')
        clean = {'text': answer['text'].strip(), 'choice': answer.get('choice')}
        now = self.managed._now()
        with self.managed._write() as session:
            run = self._owned(session, root, run_id)
            question = session.get(store.Question, question_id)
            if question is None or question.run_id != run.id:
                raise LookupError(question_id)
            if question.answer_key == key:
                if {k: question.answer.get(k) for k in ('text', 'choice')} != clean:
                    raise Refusal('idempotency_conflict')
                return store.question_view(question)
            if run.status in autonomy.TERMINAL:
                raise Refusal('run_terminal')
            if (run.status != 'WAITING_FOR_OWNER' or question.status != 'OPEN'
                    or question.version != expected_version):
                raise Refusal('question_stale')
            if question.binding != self._binding(session, run):
                question.status, question.version, question.updated_at = 'SUPERSEDED', question.version + 1, now
                store.event(session, run, 'question_superseded', {'question_id': question.id},
                            refs={'question_id': question.id}, dedupe=f'question:{question.id}:superseded', now=now)
                return {'superseded': True, **store.question_view(question)}
            auth = store.authorization(session, run.authorization_id)
            if not self._parent_active(session, auth):
                raise Refusal('authority_inactive')
            question.status, question.version, question.updated_at = 'ANSWERED', question.version + 1, now
            question.answer = {**clean, 'origin': 'owner_confirmed', 'actor': actor(), 'answered_at': now}
            question.answer_key = key
            store.event(session, run, 'question_answered', {'question_id': question.id},
                        refs={'question_id': question.id}, dedupe=f'question:{question.id}:answered', now=now)
            return store.question_view(question)

    def pause(self, root, run_id, *, expected_version, reason):
        with self.managed._write() as session:
            run = self._owned(session, root, run_id)
            store.move(session, run, ('RUNNING',), 'PAUSED', reason='owner_paused', detail={'note': reason},
                       expected_version=expected_version, now=self.managed._now())
        return self.status_by_id(run_id)

    def resume(self, root, run_id, *, expected_version):
        """Explicit owner resume after revalidating repository, authority, versions, bounds, caps and answers."""
        with Session(self.managed.engine) as session:
            run = self._owned(session, root, run_id)
            if run.version != expected_version:
                raise Refusal('run_version_stale')
            if run.status not in autonomy.RESUMABLE:
                raise Refusal('run_not_resumable', status=run.status)
            if store.open_questions(session, run.id):
                raise Refusal('questions_open')
            auth = store.authorization(session, run.authorization_id)
            children = [{**c.subject, 'operation_key': c.operation_key} for c in store.children(session, run.id)]
            thread, recovery = run.thread_id, (run.detail or {}).get('thread_recovery')
        effects = self.effects(str(root))
        observation = effects.readiness()
        tasks = [t for p in (effects.observe().get('phases') or []) for t in p.get('tasks', [])]
        # A pause that held the reviewer after the executor leaves that executor's work in the checkout. Only that
        # exact work (verified against its persisted evidence, authority, contract, identity and settled writer)
        # replaces the clean-checkout requirement; any other change, or any doubt, still refuses.
        held = [t['held'] for t in tasks if t.get('state') == 'held_review']
        held_refusal = (effects.verify_held_review(held[0]) if len(held) == 1 else 'held_review_ambiguous') \
            if held else None
        clean = bool(observation.get('git_clean') or (held and held_refusal is None))
        reasons = [name for name, ok in (('git_baseline_clean', clean),
                                         ('no_uncertain_writer', not observation.get('uncertain_writers')))
                   if not ok]
        if held_refusal:
            reasons.append(held_refusal)
        stop = self._guard(run_id, effects)
        if stop:
            reasons.append(stop['reason'])
        cap = autonomy.cap_stop(auth.preview['caps'], effects.usage(
            children, basis=(auth.preview['caps'].get('valuation') or {}).get('basis')), self.managed._now())
        if cap:
            reasons.append(cap['reason'])
        graphs = self.graphs()
        graph = graphs.status(thread).status
        if graph == 'QUARANTINED':
            reasons.append('graph_quarantined')  # release is a later explicit owner action (D283, T020)
        if reasons:
            raise Refusal('resume_revalidation_failed', reasons=reasons)
        failed = sorted({t['run_id'] for t in tasks if t.get('state') == 'failed' and t.get('run_id')}
                        | {t['contract_run_id'] for t in tasks if t.get('contract') == 'failed' and t.get('contract_run_id')})
        with self.managed._write() as session:
            run = self._owned(session, root, run_id)
            if run.version != expected_version:
                raise Refusal('run_version_stale')
            if store.open_questions(session, run.id):
                raise Refusal('questions_open')
            if (not self._parent_active(session, store.authorization(session, run.authorization_id))
                    or effects.accepted_revision(session) != observation.get('revision')):
                raise Refusal('resume_revalidation_failed', reasons=['authority_or_revision_changed'])
            seen = sorted(set((run.detail or {}).get('acknowledged_failures') or []) | set(failed))
            store.move(session, run, autonomy.RESUMABLE, 'RUNNING', reason='owner_resumed',
                       detail={'thread_recovery': False, 'acknowledged_failures': seen},
                       expected_version=expected_version, now=self.managed._now())
        if recovery:
            result = graphs.recover(thread)
        elif graph == 'WAITING':
            result = graphs.resume(thread)
        else:
            result = self._continue_thread(run_id, thread)
        self._sync(run_id, result)
        return self.status_by_id(run_id)

    def _continue_thread(self, run_id, thread):
        """A failed graph thread holds routing only; a new continuation thread starts once none of its sealed
        operations is pending. A pending one makes the run RECOVERY_REQUIRED instead (never reissued)."""
        from my_harness.storage.models import WorkflowOperationRow as Operation
        now = self.managed._now()
        with self.managed._write() as session:
            run = store.run_by_id(session, run_id)
            pending = list(session.scalars(select(Operation.id).where(
                Operation.thread_id == thread, Operation.status.in_(('INTENDED', 'UNCERTAIN')))))
            if pending:
                store.move(session, run, ('RUNNING',), 'RECOVERY_REQUIRED', reason='effect_uncertain',
                           detail={'operations': pending}, now=now)
                return None
            count = (run.detail or {}).get('continuations', 0) + 1
            run.thread_id = f'roadmap-{run.lineage_id}-c{count}'
            run.detail = {**(run.detail or {}), 'continuations': count, 'previous_thread': thread}
            new_thread = run.thread_id
            session.flush()
            store.event(session, run, 'graph_continued', {'previous_thread': thread, 'thread': run.thread_id},
                        dedupe=f'{run.id}:continued:{count}', now=now)
        return self.graphs().start_or_status(run_id, new_thread)

    def reconcile(self, root):
        """After a restart: start a sealed run whose graph never started; a graph thread still RUNNING has no
        proof that its writer stopped, so the run becomes RECOVERY_REQUIRED (INV-06, D282)."""
        with Session(self.managed.engine) as session:
            run = store.active_run(session, root)
            if run is None:
                return None
            run_id, status, thread = run.id, run.status, run.thread_id
            started = (run.detail or {}).get('graph_started')
        if status == 'RUNNING' and not started:
            return self.reconcile_run(run_id)
        if status == 'RUNNING':
            graph = self.graphs().status(thread)
            if graph.status == 'RUNNING':
                with self.managed._write() as session:
                    run = store.run_by_id(session, run_id)
                    store.move(session, run, ('RUNNING',), 'RECOVERY_REQUIRED', reason='graph_writer_unconfirmed',
                               detail={'thread': thread}, now=self.managed._now())
            else:
                self._sync(run_id, graph)
        return self.status_by_id(run_id)

    def revoke(self, root, run_id, *, expected_version, reason):
        """Blocks new admissions at once (T010 cascade) and stops the active delegated writer through the existing
        process control; uncertain effects still need stopped-writer evidence before reconciliation."""
        if not isinstance(reason, str) or not reason.strip():
            raise Refusal('reason_required')
        now = self.managed._now()
        with self.managed._write() as session:
            run = self._owned(session, root, run_id)
            if run.version != expected_version:
                raise Refusal('run_version_stale')
            auth = store.authorization(session, run.authorization_id)
            self.permissions.end_roadmap(session, auth.project_id, auth.permission_record_id, reason=reason.strip(),
                                         actor=actor())
            children = [{**c.subject, 'operation_key': c.operation_key} for c in store.children(session, run.id)]
            store.move(session, run, autonomy.ACTIVE, 'REVOKED', reason='owner_revoked',
                       detail={'note': reason.strip(), 'writers': self.effects(run.root).writers_settled(children, session=session)},
                       now=now)
            thread = run.thread_id
        if self._graph_factory is not None:
            self.graphs().revoke(thread)
        return self.status_by_id(run_id)

    def recover(self, root, run_id, *, expected_version, writer_stopped, reason):
        """FL13: with explicit stopped-writer evidence, classify the run's sealed effects under their original
        identities; an uncertain effect is abandoned by the owner, never reissued. Then RECOVERY_REQUIRED → PAUSED."""
        if writer_stopped is not True or not isinstance(reason, str) or not reason.strip():
            raise Refusal('writer_stop_confirmation_required')
        with self.managed._write() as session:
            run = self._owned(session, root, run_id)
            if run.version != expected_version:
                raise Refusal('run_version_stale')
            if run.status not in ('RECOVERY_REQUIRED', 'REVOKED'):
                raise Refusal('run_not_recoverable', status=run.status)
            thread_id, status = run.thread_id, run.status
            reconciled_key = f'{run.id}:reconciled:{run.version}'
            if status == 'REVOKED' and session.scalar(
                    select(store.Event.id).where(store.Event.dedupe_key == reconciled_key)) is not None:
                return self._view(session, run)
            children = [{**c.subject, 'operation_key': c.operation_key} for c in store.children(session, run.id)]
            settled = self.effects(run.root).writers_settled(children, session=session)
            if not settled.get('settled'):
                raise Refusal('writer_not_confirmed_stopped', writers=settled.get('active', []))
            stamp, owner = self.managed._now(), actor()
            changed = self.journal.recover(thread_id, writer_stopped=True, at=stamp, session=session, root=run.root)
            uncertain = session.scalars(select(WorkflowOperationRow.id).where(
                WorkflowOperationRow.thread_id == thread_id, WorkflowOperationRow.root == run.root,
                WorkflowOperationRow.status == 'UNCERTAIN')).all()
            abandoned = [self.journal.abandon(ident, reason=reason, actor=owner, at=stamp, session=session)['operation_id']
                         for ident in uncertain]
            thread = session.get(GraphThreadRow, thread_id)
            continuable = self._graph_factory is not None and thread.status in ('RUNNING', 'RECOVERY_REQUIRED')
            detail = {'recovered': {'classified': changed, 'abandoned': abandoned}, 'thread_recovery': continuable}
            if status == 'RECOVERY_REQUIRED':
                store.move(session, run, ('RECOVERY_REQUIRED',), 'PAUSED', reason='recovered', detail=detail,
                           expected_version=expected_version, now=stamp)
                if continuable and thread.status == 'RECOVERY_REQUIRED':
                    GraphContinuationRepository.transition_in(session, thread_id, ('RECOVERY_REQUIRED',), 'RUNNING',
                                                              reason='owner_reconciled')
            else:
                run.detail = {**(run.detail or {}), **detail}
                store.event(session, run, 'run_reconciled', detail, dedupe=reconciled_key, now=stamp)
        return self.status_by_id(run_id)

    def advance_all(self, _repository=None):
        """Supervisor hook: continue every RUNNING run whose graph waits only on settled harness jobs. Owner stops
        are never continued here; a repeated call or a concurrent one resumes a thread at most once (CAS)."""
        with Session(self.managed.engine) as session:
            roots = sorted(set(session.scalars(select(store.Run.root).where(store.Run.status == 'RUNNING'))))
        advanced = []
        for root in roots:
            try:
                result = self.advance_waiting(root)
            except (Refusal, ValueError, LookupError):
                continue  # another worker resumed it, or the root is not registered here
            if result is not None:
                advanced.append(result['id'])
        return advanced

    def advance_waiting(self, root):
        """Resumes a RUNNING run whose graph waits only on harness jobs that have settled (no owner action)."""
        with Session(self.managed.engine) as session:
            run = store.active_run(session, root)
            if run is None or run.status != 'RUNNING':
                return None
            thread = run.thread_id
            run_id = run.id
        with Session(self.managed.engine) as session:
            started = (store.run_by_id(session, run_id).detail or {}).get('graph_started')
        if not started:
            return self.reconcile_run(run_id)
        graphs = self.graphs()
        if graphs.status(thread).status != 'WAITING' or self.effects(str(root)).observe().get('in_flight'):
            return None
        self._sync(run_id, graphs.resume(thread))
        return self.status_by_id(run_id)
