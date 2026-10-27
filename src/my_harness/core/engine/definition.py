"""H6.5 (D072 §5.1, D073): conversational creation and planning. Standard library, no effects.

Two conversations on top of the chat infrastructure (D035): `definition` (new project, from a
brief) and `phase_planning` (plan for the empty active phase or the next one). Each turn is a new
read-only invocation of the reviewer with the context frozen when it was queued. The output has a fixed schema;
an invalid output stops the turn without fallback or retry. The agent never writes: the harness writes
the drafts when applying a confirmed proposal, with CAS over the hash read in the turn.
Acceptance is a deterministic preview that leads to the D037 bootstrap with the v2 template.
"""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import PurePosixPath
import re

from my_harness.core.engine.chat import _text, _texts, digest
from my_harness.core.engine.context import policy_payload
from my_harness.core.engine.contracts import (
    ContractError, IncompleteContract, Selection, context_snapshot, freeze, invoke_agent, stop_history,
)
from my_harness.core.engine.document_text import HISTORICAL, work_language, words
from my_harness.core.engine.documents import (
    ANY_MARKER, MAX_DOCUMENT_BYTES, MAX_AGENTS_LINES, MAX_WRAPPER_LINES, Layout,
    _fields, _first, blocks, budget_warnings, decision_index, inline,
    parse_roadmap, phase_data, plan_tasks, render_decisions, render_next_steps, render_roadmap, render_state,
    protected_write, replace_block, require_layout, skeleton,
)
from my_harness.core.engine.phases import phase_definition
from my_harness.core.engine.planning import FIELD_NAMES, bullet_items, deterministic_task, section
from my_harness.core.engine.prompts import dump_catalog, render_attempt
from my_harness.i18n import tr

MAX_BRIEF_BYTES = 256 * 1024
# Drafts frozen in a turn: all of them, in full; above this limit, the turn is not queued.
MAX_CONTEXT_DRAFT_BYTES = 2 * 1024 * 1024
MAX_DRAFTS = 20
MAX_QUESTIONS = 30
MAX_PENDING = 30
DRAFT_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.md')
# Onboarding shares the read-only definition role and schema, with its own template and frozen context.
KINDS = {'definition': ('define-project', 'definition'), 'phase_planning': ('plan-phase', 'planning'),
         'onboarding': ('onboard-project', 'definition')}
DRAFT_KINDS = ('definition', 'onboarding')
TEMPLATE = {'name': 'project-definition', 'version': '4'}  # 4: mandatory documents and D088 prompts


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def brief(text) -> dict:
    """User Markdown frozen with its hash. Commands, paths and selections are not interpreted."""
    if not isinstance(text, str) or not text.strip() or '\0' in text:
        raise ValueError(tr('definition.brief_non_empty_nul'))
    size = len(text.encode('utf-8'))
    if size > MAX_BRIEF_BYTES:
        raise ValueError(tr('definition.brief_exceeds_kib', limit=MAX_BRIEF_BYTES // 1024))
    return {'content': text, 'sha256': text_hash(text), 'size': size}


def question_id(text: str) -> str:
    return hashlib.sha256(' '.join(text.split()).encode('utf-8')).hexdigest()


# --- draft paths -------------------------------------------------------------------------------


def definition_layout(context) -> Layout:
    target = require_layout(context)
    if target.docs in ('', '.') or target.docs.startswith('/'):
        raise ValueError(tr('definition.definition_requires_state_next'))
    if '.git' in PurePosixPath(target.docs).parts:
        raise ValueError(tr('definition.documentation_folder_cannot_git'))
    return target


def fixed_drafts(target: Layout) -> tuple[str, ...]:
    """Paths of the D088 v2 template (`skeleton`); neither the title nor the commands change the paths."""
    return tuple(sorted(skeleton(target, 'x')))


def required_documents(target: Layout) -> tuple[str, ...]:
    """The eleven documents of the accepted result, including those completed by the template (D089)."""
    return (*target.instructions, *target.product_documents, *target.phase_documents)


def default_documents(target: Layout) -> tuple[str, ...]:
    """D089: only instructions and the no-persistence diagram have default content."""
    return (*target.instructions, target.ddbb_diagram)


def draft_directories(target: Layout) -> frozenset[str]:
    parts = target.docs.split('/')
    return frozenset(['/'.join(parts[:n]) for n in range(1, len(parts) + 1)] + [target.flows_dir])


def allowed_draft(target: Layout, path: str) -> bool:
    """Only the D088 template and `flows/*.md`; any other file is foreign."""
    if not isinstance(path, str):
        return False
    if path in fixed_drafts(target):
        return True
    folder = target.flows_dir
    return path.startswith(folder + '/') and DRAFT_NAME.fullmatch(path[len(folder) + 1:]) is not None


def allowed_drafts_view(target: Layout) -> dict:
    return {'fixed': list(fixed_drafts(target)), 'patterns': [f'{target.flows_dir}/*.md'],
            'required': list(required_documents(target))}


def _block_names(target: Layout, path: str) -> set[str]:
    return {target.state: {'state'}, target.next_steps: {'state'}, target.roadmap: {'roadmap'},
            target.decisions: {'decisions'}}.get(path, set())


# --- structured outputs ------------------------------------------------------------------------


def _questions(value) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_QUESTIONS:
        raise ContractError(tr('definition.questions_list_most_items', max_questions=MAX_QUESTIONS))
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'text', 'blocking'} or type(item['blocking']) is not bool:
            raise ContractError(tr('definition.each_question_contain_exactly'))
        text = _text(item['text'], 'question', limit=4000)
        if question_id(text) in seen:
            raise ContractError(tr('definition.duplicate_question'))
        seen.add(question_id(text))
        result.append({'id': question_id(text), 'text': text, 'blocking': item['blocking']})
    return result


def _content(value, name) -> str:
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ContractError(tr('definition.non_empty_nul_free', name=name))
    if len(value.encode('utf-8')) > MAX_DOCUMENT_BYTES:
        raise ContractError(tr('definition.exceeds_512_kib', name=name))
    return value


def validate_definition_result(data, target: Layout) -> dict:
    """Fixed schema: answer, questions, complete drafts per document and open items; nothing else."""
    if not isinstance(data, dict) or set(data) != {'answer', 'questions', 'drafts', 'pending'}:
        raise ContractError(tr('definition.definition_result_contain_exactly'))
    drafts = data['drafts']
    if not isinstance(drafts, list) or len(drafts) > MAX_DRAFTS:
        raise ContractError(tr('definition.drafts_list_most_items', max_drafts=MAX_DRAFTS))
    result, paths = [], set()
    for item in drafts:
        if not isinstance(item, dict) or set(item) != {'path', 'content', 'reason'}:
            raise ContractError(tr('definition.each_draft_contain_exactly'))
        if not allowed_draft(target, item['path']):
            raise ContractError(tr('definition.draft_path_outside_d088', path=repr(item['path'])))
        if item['path'] in paths:
            raise ContractError(tr('definition.each_document_may_proposed'))
        paths.add(item['path'])
        result.append({'path': item['path'], 'content': _content(item['content'], 'Draft content'),
                       'reason': _text(item['reason'], 'draft reason', limit=4000)})
    return {'answer': _text(data['answer'], 'answer'), 'questions': _questions(data['questions']),
            'drafts': result, 'pending': _texts(data['pending'], 'pending items', limit=MAX_PENDING)}


def validate_plan(content: str, code: str) -> list[tuple[str, str]]:
    """NEXT_STEPS plan of the next phase: tasks with their prefix and only the `managed-state` block."""
    if set(blocks(content)) - {'state'}:
        raise ValueError(tr('definition.plan_may_contain_managed'))
    tasks = plan_tasks(content, code)
    if not tasks:
        raise ValueError(tr('definition.plan_needs_least_one', code=code))
    return tasks


def validate_planning_result(data, following: str | None) -> dict:
    if not isinstance(data, dict) or set(data) != {'answer', 'questions', 'plan', 'pending'}:
        raise ContractError(tr('definition.planning_result_contain_exactly'))
    plan = data['plan']
    if plan is not None:
        if following is None:
            raise ContractError(tr('definition.roadmap_has_no_further'))
        if not isinstance(plan, dict) or set(plan) != {'content', 'reason'}:
            raise ContractError(tr('definition.plan_contain_exactly_content'))
        content = _content(plan['content'], 'Plan content')
        try:
            validate_plan(content, following)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        plan = {'content': content, 'reason': _text(plan['reason'], 'plan reason', limit=4000)}
    return {'answer': _text(data['answer'], 'answer'), 'questions': _questions(data['questions']), 'plan': plan,
            'pending': _texts(data['pending'], 'pending items', limit=MAX_PENDING)}


# --- turn --------------------------------------------------------------------------------------


def planning_turn(context, history, snapshot: dict, agents, observe, journal, catalog, language=None,
                  profile_validator=None):
    """One invocation with the frozen request; what was observed (drafts or checkout) cannot change."""

    def done(history, status, reasons, *, result=None, observed=None):
        return replace(history, status='completed', stop=None) if status == 'ANSWERED' else history, {
            'status': status, 'reasons': list(reasons), 'result': result, 'observed': observed}

    kind = snapshot['kind']
    template, role = KINDS[kind]
    intake = snapshot['context'].get('capabilities') == 'project-intake-1'
    if intake:
        template += '-profile'
    if digest(snapshot['context']) != snapshot['context_sha256']:
        raise ContractError('Frozen planning context changed after it was queued')
    journal.checkpoint(history, kind)
    try:
        before = observe()
    except Exception as exc:
        reason = tr('definition.observe_before', error=f'{type(exc).__name__}: {exc}')
        return done(stop_history(history, kind, reason), 'FAILED', [reason])
    queued_observation = ({k: v for k, v in before.items() if k != 'snapshot'}
                          if kind == 'onboarding' else before)
    if snapshot.get('observed') is not None and queued_observation != snapshot['observed']:
        # The proposals' CAS uses the frozen hashes: if they no longer match, the agent is not even invoked.
        reason = tr('definition.drafts_changed_queued')
        return done(stop_history(history, kind, reason), 'FAILED', [reason], observed={'before': before})
    try:
        catalog_json = dump_catalog(catalog)
        prompt, prompt_snapshot = render_attempt(catalog, template, {
            'CONTEXT_JSON': freeze(snapshot['context']), 'MESSAGE': snapshot['message']}, context, language)
    except (ValueError, KeyError, TypeError) as exc:
        return done(stop_history(history, 'prompts', str(exc)), 'FAILED', [str(exc)])
    history = replace(history, prompt_catalog_json=catalog_json)
    selection = Selection(context.policy.planner_model, context.policy.planner_effort,
                          f'Explicit planner policy for the read-only {kind.replace("_", " ")} conversation')
    history, data = invoke_agent(context, history, agents, role, selection, prompt, journal,
                                 prompt_snapshot_json=prompt_snapshot)
    try:
        after = observe()
    except Exception as exc:
        reason = tr('definition.observe_after', error=f'{type(exc).__name__}: {exc}')
        return done(stop_history(history, kind, reason) if history.stop is None else history, 'FAILED', [reason],
                    observed={'before': before, 'after': None})
    observed = {'before': before, 'after': after, 'unchanged': after == before}
    if after != before:
        reason = tr('definition.target_changed_turn')
        return done(stop_history(history, kind, reason) if history.stop is None else history, 'FAILED', [reason],
                    result=data, observed=observed)
    if data is None:
        return done(history, 'FAILED', [history.stop.reason], observed=observed)
    try:
        if kind in DRAFT_KINDS:
            if intake:
                if not isinstance(data, dict) or set(data) != {'answer', 'questions', 'drafts', 'pending', 'profile'}:
                    raise ContractError(tr('profile_proposal.invalid'))
                result = validate_definition_result({k: v for k, v in data.items() if k != 'profile'},
                                                    definition_layout(context))
                if profile_validator is None:
                    raise ContractError(tr('profile_proposal.invalid'))
                result['profile'] = profile_validator(data['profile'], snapshot['context'], result['drafts'], context=context)
            else:
                result = validate_definition_result(data, definition_layout(context))
        else:
            following = snapshot['context']['next']
            result = validate_planning_result(data, following['code'] if following else None)
    except ContractError as exc:
        return done(stop_history(history, kind, str(exc)), 'FAILED', [str(exc)], result=data, observed=observed)
    return done(history, 'ANSWERED', [], result=result, observed=observed)


# --- acceptance --------------------------------------------------------------------------------


def _task_fields(text: str, task_id: str) -> dict:
    raw = _fields('\n'.join(section(text, rf'^##\s+{re.escape(task_id)}\s+[—-].*$').splitlines()[1:]))
    return {key: _first(raw, names) for key, names in FIELD_NAMES.items()}


def template_identity(target: Layout, language: str = HISTORICAL) -> dict:
    sha = hashlib.sha256(freeze({'skeleton': skeleton(target, '{title}', language=language),
                                 'allowed': allowed_drafts_view(target)}).encode('utf-8')).hexdigest()
    return {**TEMPLATE, 'sha256': sha, 'id': f"{TEMPLATE['name']}:{TEMPLATE['version']}:{sha}"}


def render_definition(conversation: dict, documents: list[dict], language: str = HISTORICAL) -> str:
    """Mechanical summary of the conversation from SQLite; free text escaped inline."""
    w = words(language)
    lines = [w['definition_title'], '', w['definition_note'], '',
             w['definition_conversation'].format(id=conversation['id'], title=inline(conversation['title'])),
             f"**Brief:** [BRIEF.md](BRIEF.md) · `{conversation['brief']['sha256'][:12]}` "
             f"({conversation['brief']['size']} bytes)", '', w['definition_turns'], '',
             w['turns_table'], '|---|---|---|---|---|']
    for turn in conversation['turns']:
        lines.append(f"| {turn['number']} | {inline(turn['status'])} | {inline(turn['message'], 200, language)} "
                     f"| {inline(turn.get('answer'), 300, language)} | {len(turn.get('drafts') or [])} |")
    if not conversation['turns']:
        lines.append(f"| — | {w['no_turns']} | — | — | — |")
    lines += ['', w['drafts_heading'], '']
    lines += [f"- {inline(entry['path'])}: "
              + (w['draft_proposal'].format(proposal=entry['proposal_number'], turn=entry['turn_number'])
                 if entry['source'] == 'proposal' else w['draft_edit'])
              + f" ({_short(entry.get('before'), language)} → {_short(entry.get('after'), language)})"
              for entry in conversation['log']] or [w['no_drafts']]
    lines += ['', w['last_questions'], '']
    lines += [f"- {inline(q['text'])} — " + (w['deferred'] + inline(q['deferred']['reason']) if q.get('deferred')
                                              else w['blocking'] if q['blocking'] else w['non_blocking'])
              for q in conversation['questions']] or [w['none_f']]
    lines += ['', w['last_pending'], '']
    lines += [f'- {inline(item)}' for item in conversation['pending']] or [w['none_m']]
    lines += ['', w['accepted_documents'], '', w['documents_table'], '|---|---|---|']
    lines += [f"| {inline(doc['path'])} | `{doc['sha256'][:12]}` | {inline(w[ORIGINS[doc['origin']]])} |"
              for doc in documents]
    return '\n'.join(lines) + '\n'


ORIGINS = {'draft': 'origin_draft', 'draft+blocks': 'origin_draft_blocks', 'template': 'origin_template',
           'archive': 'origin_archive'}


def _short(value, language) -> str:
    return words(language)['absent'] if value is None else f'`{value[:12]}`'


def acceptance(context, conversation: dict, inspection: dict, texts: dict[str, str]) -> dict:
    """Deterministic acceptance preview: blockers or the complete files of the root commit.

    `conversation`: SQLite snapshot (brief, turns, open questions with deferrals, open items,
    draft register). `inspection`: drafts, foreign and invalid files of the destination.
    `texts`: content of each draft, with the inspection hash."""
    target = definition_layout(context)
    language = work_language(context)
    blockers, warnings = [], []
    if inspection['import_required']:
        blockers.append(tr('planning.target_belongs_git_repository'))
    if inspection['foreign']:
        blockers.append(tr('definition.foreign_files', paths=', '.join(inspection['foreign'])
                           + (' …' if inspection.get('foreign_truncated') else '')))
    if inspection['invalid']:
        blockers.append(tr('definition.invalid_drafts', paths=', '.join(inspection['invalid'])))
    missing = [path for path in required_documents(target) if path not in texts and path not in default_documents(target)]
    if missing:
        blockers.append(tr('definition.required_missing', paths=', '.join(missing)))
    for path, limit in ((target.agents, MAX_AGENTS_LINES), (target.claude, MAX_WRAPPER_LINES),
                        (target.gemini, MAX_WRAPPER_LINES)):
        if path in texts and len(texts[path].splitlines()) > limit:
            blockers.append(tr('definition.contain_most_lines_d088', path=path, limit=limit))
    for path, text in sorted(texts.items()):
        try:
            names = set(blocks(text))
        except ValueError as exc:
            blockers.append(f'{path}: {exc}')
            continue
        if names - _block_names(target, path):
            blockers.append(tr('definition.contains_managed_blocks_belong', path=path))
    if target.decisions in texts:
        try:
            decision_index(texts[target.decisions])
        except ValueError as exc:
            blockers.append(f'DECISIONS: {exc}')
    entry, tasks = None, []
    if target.roadmap in texts:
        try:
            entries = parse_roadmap(texts[target.roadmap])
        except ValueError as exc:
            entries = []
            blockers.append(f'ROADMAP: {exc}')
        if not entries:
            blockers.append('ROADMAP needs at least one phase section «## PNNN — título»')
        elif entries[0]['code'] != 'P001':
            blockers.append(tr('definition.first_roadmap_phase_p001'))
        else:
            entry = entries[0]
            if not entry['objective'] or not entry['exit_criteria']:
                blockers.append(tr('definition.p001_needs_objective_least'))
                entry = None
    if target.next_steps in texts:
        try:
            tasks = plan_tasks(texts[target.next_steps], 'P001')
        except ValueError as exc:
            blockers.append(f'NEXT_STEPS: {exc}')
        else:
            if not tasks:
                blockers.append(tr('definition.next_steps_needs_least'))
    first_task = None
    if tasks:
        task_id = tasks[0][0]
        fields = _task_fields(texts[target.next_steps], task_id)
        if not fields['objective'] or not bullet_items(fields['acceptance_criteria']):
            blockers.append(tr('definition.needs_objective_acceptance_criteria', task_id=task_id))
        elif context.policy.planning_mode != 'agent':
            try:
                first_task = json.loads(deterministic_task(context, task_id, 'P001', texts[target.next_steps]))
            except (IncompleteContract, ContractError) as exc:
                if context.policy.planning_mode == 'deterministic':
                    blockers.append(tr('definition.does_not_satisfy_deterministic', task_id=task_id, exc=exc))
        if first_task is None:
            first_task = {'task_id': task_id, 'title': tasks[0][1], 'planner': 'agent'}
    open_blocking = [q for q in conversation['questions'] if q['blocking'] and not q.get('deferred')]
    if open_blocking:
        blockers.append(tr('definition.blocking_open', questions='; '.join(q['text'] for q in open_blocking)))
    paths = sorted({*texts, *fixed_drafts(target)} | {f'{target.archive("P000")}/{name}'
                                                      for name in ('BRIEF.md', 'DEFINITION.md')})
    protected = [path for path in paths if protected_write(context, path)]
    if protected:
        blockers.append(tr('definition.protected_paths', paths=', '.join(protected)))
    warnings += [tr('definition.pending', item=item) for item in conversation['pending']]
    base = {'template': template_identity(target, language), 'input': {'conversation_id': conversation['id']},
            'definition': {'conversation_id': conversation['id'], 'conversation_version': conversation['version'],
                           'brief_sha256': conversation['brief']['sha256'], 'turns': len(conversation['turns']),
                           'drafts': dict(sorted(inspection['drafts'].items())),
                           'questions': conversation['questions'], 'pending': conversation['pending'],
                           'allowed': allowed_drafts_view(target)},
            'context_sha256': hashlib.sha256(context_snapshot(context).encode()).hexdigest(),
            'preparation': [asdict(c) for c in context.profile.preparation],
            'validations': [asdict(c) for c in context.profile.validations],
            'policy': policy_payload(context.policy), 'profile': context.profile.name}
    if blockers or entry is None:
        return {**base, 'documents': [], 'phase': None, 'first_task': None, 'task_text': None,
                'blockers': blockers or [tr('definition.roadmap_missing')], 'warnings': warnings}
    definition = phase_definition(context, phase_data(target, entry, tasks))
    fresh = {'phase': {'code': 'P001', 'status': 'ACTIVE', 'objective': entry['objective']},
             'tasks': [{'task_id': task, 'status': None, 'planned': True} for task, _ in tasks],
             'open_questions': [], 'latest_check': None}
    rows = [{'code': item['code'], 'title': item['title'],
             **({'status': 'ACTIVE', 'tag': item['tag']} if item['code'] == 'P001' else {})}
            for item in parse_roadmap(texts[target.roadmap])]
    regenerated = {
        target.state: replace_block(texts[target.state], render_state(fresh, language)),
        target.next_steps: replace_block(texts[target.next_steps], render_next_steps(fresh, language)),
        target.roadmap: replace_block(texts[target.roadmap], render_roadmap(rows, language), 'roadmap'),
        target.decisions: replace_block(texts[target.decisions],
                                        render_decisions(decision_index(texts[target.decisions]), language),
                                        'decisions'),
    }
    # D088: AGENTS, CLAUDE, GEMINI and DDBB-DIAGRAM that were not drafted come from the template with the title and
    # commands of the frozen profile.
    template = skeleton(target, conversation['title'],
                        preparation=[command.argv for command in context.profile.preparation],
                        validations=[command.argv for command in context.profile.validations],
                        language=language)
    documents = []
    for path in sorted({*texts, *default_documents(target)}):
        if path in texts:
            content = regenerated.get(path, texts[path])
            origin = 'draft+blocks' if content != texts[path] else 'draft'
            before = inspection['drafts'][path]
        else:
            content, origin, before = template[path], 'template', None
        documents.append({'path': path, 'content': content, 'sha256': text_hash(content), 'before_sha256': before,
                          'origin': origin})
    archive = target.archive('P000')
    brief_doc = conversation['brief']['content']
    record = render_definition(conversation, documents, language)
    documents += [{'path': f'{archive}/BRIEF.md', 'content': brief_doc, 'sha256': text_hash(brief_doc),
                   'before_sha256': None, 'origin': 'archive'},
                  {'path': f'{archive}/DEFINITION.md', 'content': record, 'sha256': text_hash(record),
                   'before_sha256': None, 'origin': 'archive'}]
    documents.sort(key=lambda doc: doc['path'])
    for doc in documents:
        if len(doc['content'].encode('utf-8')) > MAX_DOCUMENT_BYTES:
            raise ValueError(tr('definition.would_exceed_512_kib', path=doc['path']))
        if doc['origin'] in ('template', 'archive') and ANY_MARKER.search(doc['content']) and doc['path'] != f'{archive}/BRIEF.md':
            raise ValueError(tr('definition.unexpectedly_contains_managed_markers', path=doc['path']))
    warnings += budget_warnings(target, {doc['path']: doc['content'] for doc in documents})
    return {**base, 'documents': documents, 'phase': definition, 'first_task': first_task,
            'task_text': regenerated[target.next_steps], 'blockers': [], 'warnings': warnings}
