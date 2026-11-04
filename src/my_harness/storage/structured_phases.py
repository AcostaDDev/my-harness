"""T015: accepted-knowledge phase contracts over the existing phase journal and writer.

Definitions are operational projections, never another knowledge authority. Plans bind stable
members, coverage and a complete accepted revision. Drafts and reviewer proposals cannot adopt
product meaning. No autonomous authority is manufactured by this manual adapter.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine import knowledge_documents as documents
from my_harness.core.engine.phases import digest, phase_definition, document_hashes
from my_harness.services.knowledge_exchange import PhaseKnowledge
from my_harness.storage.managed import Conflict, _job
from my_harness.storage.models import (PhaseRow as Phase, PhaseDefinitionRow as Definition,
    PhaseOperationRow as Operation, ManagedRunRow as Run)
from my_harness.storage import knowledge_exchange as exchange
from my_harness.storage.permissions import actor
from my_harness.i18n import tr


def refuse(reason):
    raise Conflict(tr('phases.structured_refused', reason=reason))


def current(session, root):
    return PhaseKnowledge.accepted(session, root)


def stamp(revision):
    return {'id': revision.id, 'number': revision.number, 'sha256': revision.revision_sha256}


def projection(context, revision, code, coverage=None, *, planned=False):
    member = revision.item('phase', code)
    if member is None or member.content['status'] != 'planned':
        refuse('phase_not_in_accepted_roadmap')
    criteria = sorted((revision.members[l.source] for l in revision.links
                       if l.kind == 'criterion_of' and l.target == member.item_id), key=lambda m: m.code)
    criteria = [c for c in criteria if c.content['status'] == 'active']
    tasks = sorted((revision.members[l.source] for l in revision.links
                    if l.kind == 'part_of' and l.target == member.item_id), key=lambda m: m.code)
    if any(not t.code.startswith(code + '-T') for t in tasks):
        refuse('task_identity_outside_phase')
    available = {t.code: asdict(t) for t in tasks if t.content["status"] == "planned"}
    tasks = [t for t in tasks if t.content['status'] == 'planned'] if planned else []
    if planned and not tasks:
        refuse('plan_requires_tasks')
    coverage = coverage or {}
    if planned and set(t.code for t in tasks) - {t for values in coverage.values() if isinstance(values, list) for t in values}:
        refuse('tasks_require_criterion_coverage')
    if planned and (set(coverage) != {c.code for c in criteria} or any(
            not isinstance(value, list) or not value or len(set(value)) != len(value)
            or set(value) - {t.code for t in tasks} for value in coverage.values())):
        refuse('plan_requires_complete_criterion_coverage')
    definition = phase_definition(context, {'code': code, 'objective': member.content['objective'],
        'exit_criteria': [c.code + ': ' + c.content['statement'] for c in criteria],
        'tasks': [t.code for t in tasks], 'tag': member.content['tag'],
        'documents': sorted(set(documents.PATHS.values()) | {'docs/STATE.md', documents.META, 'AGENTS.md'})})
    definition['knowledge'] = {'revision': stamp(revision), 'phase_item_id': member.item_id,
        'criteria': {c.code: asdict(c) for c in criteria}, 'tasks': {t.code: asdict(t) for t in tasks},
        'coverage': coverage, 'planned': planned, 'available_tasks': available,
        'dependencies': {t.code: sorted(revision.members[l.target].code for l in revision.links
                                      if l.kind == 'depends_on' and l.source == t.item_id) for t in tasks},
        'replacement_lineage': {t.code: sorted(revision.members[l.target].code for l in revision.links
                                              if l.kind == 'replaces' and l.source == t.item_id) for t in tasks},
        'task_criteria': {t.code: {revision.members[l.source].code: asdict(revision.members[l.source])
                                 for l in revision.links if l.kind == 'criterion_of' and l.target == t.item_id}
                          for t in tasks}}
    return definition


def authority(session, phase):
    revision = current(session, phase.root)
    owner = exchange.owned_at_root(session, phase.root)
    return {'knowledge': {'revision': stamp(revision) if revision else None,
                         'ownership_id': owner.id if owner else None,
                         'manifest_sha256': digest(owner.payload['manifest']) if owner else None}}


def validate_plan(session, phase, revision, definition):
    """Plan edits cannot modify criteria/objectives or silently drop task history."""
    previous = current(session, phase.root)
    old = previous.members
    new = revision.members
    for ident, member in old.items():
        other = new.get(ident)
        if member.kind != 'task' and (other is None or asdict(other) != asdict(member)):
            refuse('plan_cannot_change_product_meaning')
        if member.kind == 'task' and other is None:
            refuse('plan_cannot_remove_task_identity')
    phase_item = definition['knowledge']['phase_item_id']
    scoped = {l.source for l in revision.links if l.kind == 'part_of' and l.target == phase_item}
    for ident, member in new.items():
        if (ident not in old or asdict(member) != asdict(old[ident])) and ident not in scoped and not (
                member.kind == 'criterion' and any(l.kind == 'criterion_of' and l.source == ident
                                                  and l.target in scoped for l in revision.links)):
            refuse('plan_outside_phase_scope')
    immutable = lambda links: {freeze(asdict(l)) for l in links if not (
        l.source in scoped and l.kind in ('part_of', 'depends_on', 'addresses', 'replaces') or
        l.kind == 'criterion_of' and l.target in scoped)}
    if immutable(previous.links) != immutable(revision.links):
        refuse('plan_outside_phase_scope')
    for link in revision.links:
        if link.kind == 'replaces' and link.source in scoped and link.target not in scoped:
            refuse('replacement_outside_phase')
        if link.kind == 'depends_on' and new[link.source].code in definition['tasks'] and new[link.target].content['status'] == 'withdrawn':
            refuse('dependency_withdrawn')
        if link.kind == 'depends_on' and link.source in scoped and link.target not in scoped:
            from my_harness.storage.models import ManagedCommitRow as Commit
            target = new[link.target]
            committed = session.scalar(select(Commit.operation_id).join(Run, Run.id == Commit.run_id).where(
                Run.root == phase.root, Run.task_id == target.code, Commit.status == 'COMMITTED'))
            if not committed:
                refuse('dependency_not_committed')
    for task in phase.definition['tasks']:
        if task not in definition['tasks']:
            original = previous.item('task', task)
            if not original or not any(l.kind == 'replaces' and l.target == original.item_id
                                       and new[l.source].code in definition['tasks'] for l in revision.links):
                refuse('withdrawn_task_requires_replacement_lineage')
    from my_harness.storage.phases import _latest
    check = _latest(session, phase.id, 'check')
    if check and check.result and check.result.get('result'):
        failed = [r['criterion'].split(':', 1)[0] for r in
                  check.result['result'].get('exit_criteria_results', []) if not r['passed']]
        added = set(definition['tasks']) - set(phase.definition['tasks'])
        if added and failed and not added <= {t for c in failed for t in definition['knowledge']['coverage'].get(c, [])}:
            refuse('remediation_must_cover_unmet_criteria')


class StructuredPhases:
    def __init__(self, managed):
        self.managed = managed

    def preview(self, context, code, *, phase_id=None, expected_version=None, draft_id=None, coverage=None):
        with Session(self.managed.engine) as session:
            revision = current(session, context.root)
            if revision is None:
                refuse('accepted_knowledge_required')
            phase = session.get(Phase, phase_id) if phase_id else None
            from my_harness.storage.phases import PhaseRepository, CHECKABLE
            if phase_id:
                phase = PhaseRepository(self.managed)._phase(session, phase_id, expected_version, context)
                if phase.status not in CHECKABLE or phase.code != code:
                    refuse('phase_not_plannable')
            if PhaseRepository._root_pending(session, str(context.root)):
                refuse('checkout_has_pending_work')
            from my_harness.storage.documents import unresolved
            if unresolved(session, str(context.root)):
                refuse('checkout_has_unresolved_intent')
            candidate = revision
            if draft_id:
                members, links = PhaseKnowledge.candidate(session, context.root, draft_id, revision.id)
                from dataclasses import replace
                candidate = replace(revision, members=members, links=tuple(links))
            definition = projection(context, candidate, code, coverage, planned=bool(phase_id))
            owner = exchange.owned_at_root(session, context.root)
            if owner:
                definition['documents'] = [t['path'] for t in owner.payload['manifest']['targets']]
            if phase:
                validate_plan(session, phase, candidate, definition)
            elif draft_id:
                refuse('activate_only_accepted_roadmap')
            else:
                existing = set(session.scalars(select(Phase.code).where(Phase.root == str(context.root))))
                remaining = sorted(m.code for m in revision.members.values() if m.kind == 'phase'
                                   and m.content['status'] == 'planned' and m.code not in existing)
                if not remaining or code != remaining[0]:
                    refuse('activate_next_accepted_phase_only')
            shown = {'format': 'structured-phase-1', 'phase_id': phase_id, 'code': code,
                'expected_version': expected_version, 'revision': stamp(revision), 'draft_id': draft_id,
                'draft_sha256': digest({'members': [asdict(m) for m in sorted(candidate.members.values(), key=lambda m: m.item_id)],
                                        'links': [asdict(l) for l in sorted(candidate.links, key=lambda l: l.key())]}),
                'definition': definition, 'origin': 'owner_confirmed'}
            if phase:
                from my_harness.core.engine.judge import input_check
                criteria = [m['item_id'] for m in definition['knowledge']['criteria'].values()]
                candidate = {'options': [{'id': digest(definition), 'admissible': True,
                    'tradeoffs': 'Validated phase plan inside accepted criteria.', 'criterion_ids': criteria}],
                    'criterion_ids': criteria}
                input_check('planning_choice', candidate)
                shown['judge_input'] = candidate
            return {**shown, 'preview_sha256': digest(shown)}

    def adopt(self, context, code, *, preview_sha256, key, reason, confirmed, delegated=None, **kwargs):
        """Owner-confirmed adoption by exact preview; or (T016) delegated adoption of a plan revision of an existing
        phase, whose sealed child is verified inside this writer transaction before anything is adopted."""
        if not isinstance(reason, str) or not reason.strip():
            refuse('explicit_owner_confirmation_required')
        if delegated is None and confirmed is not True or delegated is not None and (
                confirmed is not False or not kwargs.get('phase_id')):
            refuse('explicit_owner_confirmation_required')
        marker = digest({'code': code, 'preview_sha256': preview_sha256, 'reason': reason, **kwargs,
                         **({'child_id': delegated['child_id']} if delegated else {})})
        with self.managed._write() as session:
            revision = current(session, context.root)
            if revision is None:
                refuse('accepted_knowledge_required')
            records = exchange.records(session, revision.project_id, 'phase_adoption')
            existing = next((r for r in records if r.record_key == 'phase:' + key), None)
            if existing:  # an idempotent replay performs no new effect
                if existing.payload['request_sha256'] != marker:
                    refuse('idempotency_conflict')
                return existing.payload['phase_id']
            shown = self.preview(context, code, **kwargs)
            if shown['preview_sha256'] != preview_sha256:
                refuse('preview_stale')
            provenance = None
            if delegated:
                # T016 (D301): the child must name exactly this proposal, staged draft, preview and revision.
                provenance = delegated['verify'](session, adoption={
                    'preview_sha256': preview_sha256, 'draft_id': kwargs.get('draft_id'),
                    'coverage': kwargs.get('coverage'), 'revision_id': revision.id,
                    'expected_version': kwargs.get('expected_version')})
                op = session.get(Operation, provenance['proposal_operation_id'] or '')
                if (op is None or op.phase_id != kwargs['phase_id'] or op.kind != 'plan' or op.status != 'PROPOSED'
                        or not (op.result or {}).get('staged') or op.result.get('draft_id') != kwargs.get('draft_id')
                        or digest(op.result['result']) != provenance['proposal_sha256']
                        or op.result['result']['coverage'] != kwargs.get('coverage')):
                    refuse('delegated_adoption_mismatch')
            phase_id = kwargs.get('phase_id')
            definition = deepcopy(shown['definition'])
            if shown['draft_id']:
                revision = PhaseKnowledge.adopt(session, context.root, shown['draft_id'], revision.id,
                                                reason=reason, confirmed=confirmed, delegated=provenance)
                definition['knowledge']['revision'] = stamp(revision)
            from my_harness.storage.phases import insert_phase, _event, _invalidate_batches, _questions, _open, TERMINAL
            if not phase_id:
                if session.scalar(select(Phase.id).where(Phase.root == str(context.root),
                                                       Phase.status.notin_(TERMINAL))):
                    refuse('active_phase_exists')
                if session.scalar(select(Phase.id).where(Phase.root == str(context.root), Phase.code == code)):
                    refuse('phase_already_exists')
                phase_id = insert_phase(self.managed, session, str(context.root), definition, {},
                    source={'kind': 'accepted_knowledge', 'revision_id': revision.id})
            else:
                phase = session.get(Phase, phase_id)
                if phase.version != kwargs['expected_version']:
                    refuse('preview_stale')
                phase.definition = definition
                phase.definition_sha256 = digest(definition)
                phase.definition_number += 1
                phase.status = 'BLOCKED' if _open(_questions(session, phase.id)) else 'ACTIVE'
                session.add(Definition(id=str(uuid4()), phase_id=phase.id, number=phase.definition_number,
                    definition=definition, definition_sha256=phase.definition_sha256, documents={},
                    origin='amended', reason=reason,
                    actor={'principal': 'harness', **provenance} if provenance else actor(),
                    created_at=self.managed._now()))
                _invalidate_batches(self.managed, session, phase, reason)
                _event(self.managed, session, phase, 'phase_plan_adopted', {
                    'revision_id': revision.id, 'origin': 'owner_delegated' if provenance else 'owner_confirmed',
                    'preview_sha256': preview_sha256, 'definition_number': phase.definition_number,
                    **({'delegation': provenance} if provenance else {})})
            exchange.add(session, revision.project_id, 'phase_adoption', {
                'request_sha256': marker, 'phase_id': phase_id, 'preview': shown,
                'accepted_revision': stamp(revision), 'reason': reason,
                **({'delegation': provenance} if provenance else {})}, 'phase:' + key)
            return phase_id

    def propose(self, context, phase_id, expected, *, key, versions):
        from my_harness.storage.phases import PhaseRepository, _event, CHECKABLE
        request = freeze({'action': 'phase_check', 'mode': 'plan', 'phase_id': phase_id, 'expected_version': expected})
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            phase = PhaseRepository(self.managed)._phase(session, phase_id, expected, context)
            if phase.status not in CHECKABLE or not phase.definition.get('knowledge'):
                refuse('phase_not_plannable')
            if PhaseRepository._root_pending(session, phase.root):
                refuse('checkout_has_pending_work')
            job = self.managed._queue_new_run(session, assessment, context, versions, phase.code + '-PLAN',
                phase.code, key, request, purpose='phase_check')
            session.add(Operation(id=str(uuid4()), phase_id=phase.id, kind='plan', run_id=job.run_id,
                status='QUEUED', previous_status=phase.status,
                request={'knowledge': authority(session, phase)['knowledge'], 'definition_sha256': phase.definition_sha256, 'actor': actor()},
                created_at=self.managed._now()))
            phase.status = 'CHECKING'
            _event(self.managed, session, phase, 'phase_plan_requested', {'run_id': job.run_id, 'job_id': job.id})
            return job

    def stage(self, context, phase_id, operation_id, expected, *, proposal_sha256):
        """Persist an untrusted candidate as a draft; adoption is a separate confirmed CAS."""
        from my_harness.storage.phases import PhaseRepository, _event
        with self.managed._write() as session:
            op = session.get(Operation, operation_id)
            phase = session.get(Phase, phase_id)
            if (op and phase and phase.root == str(context.root) and op.phase_id == phase.id
                    and op.kind == 'plan' and op.status == 'PROPOSED' and op.result.get('staged')
                    and digest(op.result['result']) == proposal_sha256
                    and op.request['knowledge'] == authority(session, phase)['knowledge']
                    and op.request['definition_sha256'] == phase.definition_sha256):
                return {'draft_id': op.result['draft_id'], 'coverage': op.result['result']['coverage']}
            phase = PhaseRepository(self.managed)._phase(session, phase_id, expected, context)
            op = session.get(Operation, operation_id)
            if not op or op.phase_id != phase.id or op.kind != 'plan' or op.status != 'PROPOSED':
                refuse('proposal_not_available')
            result = op.result['result']
            if result.get('pending') or any(q['blocking'] for q in result.get('questions', [])):
                refuse('unresolved_planning_questions')
            if (digest(result) != proposal_sha256 or op.request['knowledge'] != authority(session, phase)['knowledge']
                    or op.request['definition_sha256'] != phase.definition_sha256):
                refuse('proposal_stale')
            revision = current(session, context.root)
            if op.result.get('staged'):
                return {'draft_id': op.result['draft_id'], 'coverage': result['coverage']}
            def validate(candidate):
                definition = projection(context, candidate, phase.code, result['coverage'], planned=True)
                validate_plan(session, phase, candidate, definition)
            draft = PhaseKnowledge.stage(session, context.root, revision.id, result['knowledge'], validate)
            op.result = {**op.result, 'draft_id': draft, 'staged': True}
            _event(self.managed, session, phase, 'phase_plan_staged', {'operation_id': op.id, 'draft_id': draft})
            return {'draft_id': draft, 'coverage': result['coverage']}


def closure_inputs(session, phase):
    revision = current(session, phase.root)
    owner = exchange.owned_at_root(session, phase.root)
    if not revision or not owner:
        refuse('accepted_knowledge_and_ownership_required')
    return {'domain': documents.snapshot(revision), 'ownership_id': owner.id,
            'manifest': owner.payload['manifest'], 'knowledge': authority(session, phase)['knowledge']}


def closure_preview(context, state, git):
    """Archive committed bytes; render fresh owned targets from sealed SQLite inputs, never Markdown."""
    from my_harness.core.engine.document_ops import _clean_capture, _sealed_preview
    from my_harness.core.engine.documents import require_layout
    from my_harness.services.knowledge_delivery import safe, baseline
    from my_harness.storage.knowledge import Revision
    from pathlib import Path
    target = require_layout(context)
    closed = state['phase']
    inputs = state['structured']
    data, manifest = inputs['domain'], inputs['manifest']
    archive = target.archive(closed['code'])
    folder = context.path(archive)
    if folder.exists() or folder.is_symlink():
        refuse('archive_collision')
    # safe() validates links, ancestors, case aliases and hardlinks for every destination before writes.
    captured = baseline(context.root, [t['path'] for t in manifest['targets']])
    evidence, provenance = _clean_capture(context, git)
    phases = sorted((m for m in data['members'] if m['kind'] == 'phase'
                     and m['content']['status'] == 'planned'), key=lambda m: m['code'])
    codes = [m['code'] for m in phases]
    if closed['status'] != 'ABANDONED' and closed['code'] not in codes:
        refuse('phase_not_in_accepted_roadmap')
    next_code = next((code for code in codes if code > closed['code']), None)
    following = None
    if next_code:
        if next_code in state['existing_codes']:
            refuse('successor_already_exists')
        # Rebuild the already verified sealed domain solely for the pure projection.
        from my_harness.core.engine.knowledge import Member, Link
        revision = Revision(data['revision']['id'], data['source_project_id'], data['revision']['number'],
            None, '', data['revision']['sha256'], 'owner_confirmed', {}, None, {}, '',
            {m['item_id']: Member(**m) for m in data['members']}, tuple(Link(**l) for l in data['links']))
        following = projection(context, revision, next_code)
    files = documents.phase_views(documents.render(data, manifest), active=next_code, pending=True,
        archives={**state['phases'], closed['code']: {
            'status': closed['status'], 'archive': f'archive/{folder.name}/'}},
        language=manifest['work_language'])
    if following:
        following['documents'] = [t['path'] for t in manifest['targets']]
    changes, names = [], set()
    def add(path, old, new):
        safe(context.root, path)
        if path.casefold() in names:
            refuse('archive_name_collision')
        names.add(path.casefold())
        changes.append((path, old, new))
    for path, content in captured['targets'].items():
        if content is not None:
            add(archive + '/documents/' + path, None, context.path(path).read_bytes())
    add(archive + '/knowledge.json', None, freeze(data))
    add(archive + '/evidence.json', None, freeze(state))
    work = context.path(target.phase_dir)
    if work.is_symlink():
        refuse('artifact_link')
    if work.exists():
        import os
        for parent, dirs, entries in os.walk(work, followlinks=False):
            dirs.sort()
            for name in dirs:
                if (p := Path(parent) / name).is_symlink():
                    refuse('artifact_link')
            for name in sorted(entries):
                p = Path(parent) / name
                relative = p.relative_to(context.root).as_posix()
                safe(context.root, relative)
                content = p.read_bytes()
                add(archive + '/artifacts/' + p.relative_to(work).as_posix(), None, content)
                add(relative, content, None)
    for path, content in files.items():
        add(path, captured['targets'][path], content)
    return _sealed_preview(context, evidence, provenance, provenance.base_tree, changes,
        'Structured phase archive and generated views (T015)',
        {'operation': 'phase_close', 'source': 'accepted_knowledge', 'snapshot': state,
         'archive': archive, 'next': following, 'structured': inputs,
         'required_documents': document_hashes(context, closed['definition']['documents']),
         'export': {'ownership_id': inputs['ownership_id'], 'manifest': manifest,
                    'revision_id': data['revision']['id'], 'revision_sha256': data['revision']['sha256'],
                    'files': files, 'baseline': captured}},
        large_archive_paths=frozenset(p for p, _, _ in changes if p.startswith(archive + '/')))


@contextmanager
def effect_guard(managed, claim):
    """Fresh database authority held through each Git reference effect, including recovery."""
    from my_harness.storage.phases import _operation, authority as phase_authority, stale_reasons
    from my_harness.storage.models import PhaseAuthorizationRow as Authorization
    with managed._write() as session:
        _, run = managed._owned(session, claim)
        op, phase = _operation(session, run)
        auth = session.get(Authorization, op.request['authorization_id'])
        scope = auth.scope if auth else {}
        delegated = scope.get('origin') == 'owner_delegated'
        if delegated:  # T016: the sealed child is verified again under the writer fence of each Git effect
            from my_harness.services.permission_lifecycle import PermissionLifecycle
            from my_harness.storage.autonomous_runs import verify_child
            from my_harness.core.engine.autonomy import AutonomyRefusal
            try:
                verify_child(session, PermissionLifecycle(managed.engine), scope.get('parent'), kind='phase_closure',
                             root=phase.root, phase=phase.code, binding=op.request['binding_sha256'])
            except AutonomyRefusal:
                delegated = None
        valid = (auth is not None and auth.phase_id == phase.id and auth.kind == 'close'
            and (delegated or scope.get('origin') == 'owner_confirmed' and not scope.get('parent')
                 and isinstance(auth.actor, dict) and bool(auth.actor.get('user')))
            and auth.status == 'ACTIVE' and auth.expires_at > managed._now()
            and scope.get('binding_sha256') == op.request['binding_sha256']
            and scope.get('check_operation_id') == op.request['check_operation_id']
            and scope.get('tag') == phase.definition['tag']
            and scope.get('tag_kind') == op.request['tag_kind']
            and auth.fingerprint == digest({'phase_id': phase.id, 'scope': scope, 'expires_at': auth.expires_at})
            and not stale_reasons(phase_authority(session, phase)[0], op.request['binding']))
        yield None if valid else tr('phases.structured_refused', reason='closure_authority_stale_or_invalid')


class GuardedPhaseGit:
    def __init__(self, git, managed, claim):
        self.git, self.managed, self.claim = git, managed, claim
        self.run_id = claim.run_id

    def __getattr__(self, name):
        return getattr(self.git, name)

    def capture(self, context):
        from my_harness.services.knowledge_delivery import safe
        from my_harness.storage.phases import _operation
        with Session(self.managed.engine) as session:
            _, phase = _operation(session, session.get(Run, self.run_id))
            for path in phase.definition['documents']:
                safe(context.root, path)
        return self.git.capture(context)

    def tag(self, context, intent, *, closure_intent):
        with effect_guard(self.managed, self.claim) as refusal:
            if refusal:
                refuse('closure_authority_stale_or_invalid')
            return self.git.tag(context, intent, closure_intent=closure_intent)

    def reconcile_published(self, context, intent, preview, tag_intent):
        import hashlib
        from my_harness.core.engine.commit import CommitUncertain
        with self.managed._write() as session:
            self.managed._owned(session, self.claim)
            head = self.git.published_commit(context, intent)
            if head is None:
                return None
            expected = {path: documents.sha(content) for path, content in preview['export']['files'].items()}
            expected.update({entry['path']: entry['after_sha256'] for entry in preview['documents']})
            for path, sha in expected.items():
                blob = self.git.read_blob(context, intent.expected_commit, path)
                if (None if blob is None else hashlib.sha256(blob).hexdigest()) != sha:
                    raise CommitUncertain(tr('documents.documents_changed_after_commit'))
            if preview['snapshot']['phase']['status'] == 'CLOSED' and preview['snapshot']['phase']['definition']['tag'] and not tag_intent:
                raise CommitUncertain(tr('phases.structured_refused', reason='missing_sealed_tag'))
            tag = self.git.published_tag(context, tag_intent) if tag_intent else None
            if head == intent.expected_commit:
                # The ref can have been published before the original writer refreshed its index.
                self.git.reconcile_published_index(context, intent)
            return {'commit': intent.expected_commit, 'tree': intent.expected_tree, 'tag': tag}

    def execute_documents(self, context, intent, entries):
        from dataclasses import replace
        from functools import partial
        from my_harness.services.knowledge_delivery import safe
        # Validate the complete target set before the first write, on every recovery attempt.
        for entry in entries:
            safe(context.root, entry['path'])
        with effect_guard(self.managed, self.claim) as refusal:
            if refusal:
                refuse('closure_authority_stale_or_invalid')
        def write(update):
            with effect_guard(self.managed, self.claim) as refusal:
                if refusal:
                    refuse('closure_authority_stale_or_invalid')
                safe(context.root, update.path)
                self.git._write_mechanical(context, replace(intent, mechanical=(update,)))
        @contextmanager
        def publish_guard():
            with effect_guard(self.managed, self.claim) as refusal:
                if refusal:
                    refuse('closure_authority_stale_or_invalid')
                yield None

        return self.git.execute_documents(context, intent, entries,
            write_document=write,
            publish=partial(self.git.execute, ref_guard=publish_guard),
            observe_document=partial(record_export_target, self.managed, self.run_id))


def task_evidence_current(session, phase, code, run_id):
    """A commit of an older task contract cannot satisfy an amended accepted task identity/version."""
    from my_harness.storage.models import ManagedEventRow, KnowledgeRevisionRow
    bound = session.scalar(select(ManagedEventRow.payload).where(
        ManagedEventRow.run_id == run_id, ManagedEventRow.kind == 'task_documents_frozen'))
    revision = current(session, phase.root)
    if phase.status in ('CLOSED', 'ABANDONED'):
        frozen = phase.definition['knowledge']['revision']['number']
        revision = PhaseKnowledge.accepted(session, phase.root, frozen)
    if not bound or not revision:
        return False
    intent = exchange.get(session, revision.project_id, bound['intent_id'])
    row = session.get(KnowledgeRevisionRow, intent.payload['revision_id'])
    if not row or row.status != 'ACCEPTED' or row.project_id != revision.project_id:
        return False
    accepted = PhaseKnowledge.accepted(session, phase.root, row.number)
    before, after = accepted.item('task', code), revision.item('task', code)
    if not before or not after or asdict(before) != asdict(after):
        return False
    def relevant(rev):
        links = [l for l in rev.links if l.source == after.item_id or l.kind == 'criterion_of' and l.target == after.item_id]
        criteria = [asdict(rev.members[l.source]) for l in links if l.kind == 'criterion_of']
        return sorted(freeze(asdict(l)) for l in links), sorted(freeze(c) for c in criteria)
    return relevant(accepted) == relevant(revision)


def seal_export(session, phase, op, payload):
    revision = current(session, phase.root)
    row = exchange.add(session, revision.project_id, 'export_intent',
        {**payload, 'phase_operation_id': op.id, 'phase_run_id': op.run_id}, 'phase-export:' + op.id)
    op.request = {**op.request, 'export_intent_id': row.id}


def record_export_commit(session, phase, op, intent):
    revision = current(session, phase.root)
    exchange.add(session, revision.project_id, 'export_commit', {
        'intent_id': op.request['export_intent_id'], 'commit': intent.expected_commit, 'tree': intent.expected_tree},
        'phase-export-commit:' + op.id)


def _export_target(session, phase, op, path, *, published=False):
    from my_harness.services.knowledge_delivery import read
    project = op.request['preview']['structured']['domain']['source_project_id']
    ident = op.request['export_intent_id']
    intent = exchange.get(session, project, ident)
    content = intent.payload['files'].get(path)
    if content is None:
        return
    if not published and read(phase.root, path) != content:
        refuse('export_target_changed')
    key = ident + ':target:' + documents.sha(path)
    if not any(r.record_key == key for r in exchange.records(session, project, 'export_target')):
        exchange.add(session, project, 'export_target', {
            'intent_id': ident, 'path': path, 'sha256': documents.sha(content), 'status': 'WRITTEN'}, key)


def record_export_target(managed, run_id, path):
    from my_harness.storage.phases import _operation
    with managed._write() as session:
        op, phase = _operation(session, session.get(Run, run_id))
        _export_target(session, phase, op, path)


def complete_export(session, phase, op, outcome):
    """Unchanged targets receive evidence too; the result transaction publishes one complete generation."""
    project = op.request['preview']['structured']['domain']['source_project_id']
    ident = op.request['export_intent_id']
    intent = exchange.get(session, project, ident)
    if any(intent.payload[key] != value for key, value in op.request['preview']['export'].items()):
        refuse('sealed_export_mismatch')
    for path in intent.payload['files']:
        _export_target(session, phase, op, path, published=outcome.get('published_recovery', False))
    exchange.add(session, project, 'export_completed', {
        'intent_id': ident, 'status': 'COMPLETED', 'commit': outcome['commit'],
        'revision_id': intent.payload['revision_id'], 'revision_sha256': intent.payload['revision_sha256']},
        'phase-export-completed:' + op.id)


def generation_files(session, root, revision, manifest):
    """Generate knowledge and operational views at ordinary task/export boundaries too."""
    files = documents.render(documents.snapshot(revision), manifest)
    phases = list(session.scalars(select(Phase).where(Phase.root == str(root)).order_by(Phase.created_at, Phase.id)))
    phases = [p for p in phases if p.definition.get('knowledge')]
    if not phases:
        return files
    active = next((p for p in phases if p.status not in ('CLOSED', 'ABANDONED')), None)
    from my_harness.storage.documents import phases_snapshot
    return documents.phase_views(files, active=active.code if active else None,
        pending=bool(active and not active.definition['knowledge']['planned']),
        archives=phases_snapshot(session, str(root)), language=manifest['work_language'])
