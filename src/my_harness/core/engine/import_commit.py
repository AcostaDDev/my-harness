"""Confirmed onboarding document tree and reconcilable commit intent."""
from dataclasses import replace
from hashlib import sha256
import re

from my_harness.core.engine.definition import definition_layout, _block_names
from my_harness.core.engine.document_ops import _sealed_preview
from my_harness.core.engine.document_text import work_language
from my_harness.core.engine.documents import (blocks, decision_index, parse_roadmap, phase_data, plan_tasks, render_decisions, render_next_steps, render_roadmap, render_state, replace_block)
from my_harness.core.engine.phases import phase_definition
from my_harness.core.engine.planning import TASK_RE
from my_harness.core.engine.commit import CommitIntent, CommitPlan, MechanicalUpdate, git_provenance
from my_harness.i18n import tr

STATE_HEADING = re.compile(r"^##\s+(?:Fase activa|Active phase)\s*[—–:-]\s*(P\d{3})\b", re.MULTILINE)
NEXT_STEPS_TITLE = re.compile(r"^#\s+(P\d{3})\b", re.MULTILINE)
FRONTMATTER_PHASE = re.compile(r"^phase:\s*[\"']?(?:P)?(\d{1,3})[\"']?\s*$", re.MULTILINE)

def code(number):
    return f'P{int(number):03d}'

def _state(text: str) -> list[dict]:
    found = []
    if text.startswith('---\n'):
        end = text.find('\n---', 4)
        if end != -1 and (phase := FRONTMATTER_PHASE.search(text[4:end])):
            found.append({'code': code(phase[1]), 'source': 'frontmatter'})
    found.extend({'code': match[1], 'source': 'heading'} for match in STATE_HEADING.finditer(text))
    return found


def _next_steps(text: str) -> dict:
    tasks = [match[1] for match in TASK_RE.finditer(text)]
    title = NEXT_STEPS_TITLE.search(text)
    return {'title_code': title[1] if title else None, 'tasks': len(tasks),
            'task_phases': sorted({task.split('-')[0] for task in tasks})}


def adopt_documents(context, tree):
    """Validates the declared phase and regenerates its blocks over the proposed document tree."""
    target = definition_layout(context)
    language = work_language(context)
    texts = {path: tree[path].decode('utf-8') for path in target.phase_documents}
    for path, text in texts.items():
        if set(blocks(text)) - _block_names(target, path):
            raise ValueError(tr('onboarding.contains_managed_blocks_another', path=path))
    state_codes = {item['code'] for item in _state(texts[target.state])}
    plan = _next_steps(texts[target.next_steps])
    plan_codes = set(plan['task_phases']) | ({plan['title_code']} if plan['title_code'] else set())
    if len(state_codes) != 1 or len(plan_codes) != 1 or state_codes != plan_codes:
        raise ValueError(tr('onboarding.state_next_steps_explicitly'))
    active = next(iter(state_codes))
    entries = parse_roadmap(texts[target.roadmap])
    entry = next((item for item in entries if item['code'] == active), None)
    if entry is None or not entry['objective'] or not entry['exit_criteria']:
        raise ValueError(tr('onboarding.roadmap_needs_objective_exit', active=active))
    tasks = plan_tasks(texts[target.next_steps], active)
    definition = phase_definition(context, phase_data(target, entry, tasks))
    fresh = {'phase': {'code': active, 'status': 'ACTIVE', 'objective': entry['objective']},
             'tasks': [{'task_id': task, 'status': None, 'planned': True} for task, _ in tasks],
             'open_questions': [], 'latest_check': None}
    generated = {
        target.state: replace_block(texts[target.state], render_state(fresh, language)),
        target.next_steps: replace_block(texts[target.next_steps], render_next_steps(fresh, language)),
        target.roadmap: replace_block(texts[target.roadmap], render_roadmap([
            {**item, **({'status': 'ACTIVE'} if item['code'] == active else {})} for item in entries], language),
            'roadmap'),
        target.decisions: replace_block(texts[target.decisions],
            render_decisions(decision_index(texts[target.decisions]), language), 'decisions'),
    }
    tree.update({path: text.encode() for path, text in generated.items()})
    return definition


def check_destinations(tree):
    # Includes file/directory and case collisions, including destinations introduced by drafts.
    paths = {path.lower() for path in tree}
    if len(paths) != len(tree):
        raise ValueError(tr('onboarding.import_destinations_conflict_case'))
    for path in paths:
        if any('/'.join(path.split('/')[:n]) in paths for n in range(1, path.count('/') + 1)):
            raise ValueError(tr('onboarding.import_destinations_conflict_file', path=path))


def preview_tree(context, source, contents, tree, phase, writer, extra, message):
    evidence = writer.capture(context)
    provenance = git_provenance(evidence)
    if evidence.base_revision != source['inventory']['head'] or evidence.changed_paths:
        raise ValueError(tr('onboarding.checkout_changed_since_import'))
    if provenance.index_tree != provenance.base_tree:
        raise ValueError(tr('onboarding.import_requires_clean_index'))
    def content(data):
        if data is None or b'\0' in data:
            return data
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data
    changes = [(path, content(contents.get(path)), content(tree.get(path)))
               for path in sorted(set(contents) | set(tree))]
    shown = _sealed_preview(context, evidence, provenance, provenance.base_tree, changes, message, {
        **extra, 'operation': 'import_commit',
        'phase': phase, 'baseline': {path: sha256(tree[path]).hexdigest() for path in phase['documents']},
        'result_tree': [{'path': path, 'sha256': sha256(data).hexdigest(), 'size': len(data)}
                        for path, data in sorted(tree.items())],
        'author': {'name': writer.identity.name, 'email': writer.identity.email}, 'message': message})
    probe = CommitPlan(shown['head'], shown['tree'], tuple(MechanicalUpdate(**item) for item in shown['mechanical']),
                       message + '\n', writer.identity.name, writer.identity.email, 0)
    proposed_tree, _ = writer.seal(context, probe)
    writer.check_tree_diff(context, shown['tree'], proposed_tree)
    shown['proposed_tree'] = proposed_tree
    for document in shown['documents']:
        document['exact_path'] = True
    # Delete case aliases before creating their canonical spelling on case-insensitive filesystems.
    shown['mechanical'].sort(key=lambda item: (item['content'] is not None, item['path']))
    return shown


def seal(context, shown, writer, operation_id, run_id, timestamp):
    updates = tuple(MechanicalUpdate(**item) for item in shown['mechanical'])
    message = f'{shown["message"]}\n\nHarness-Operation: {operation_id}\nHarness-Preview: {shown["preview_sha256"]}\n'
    plan = CommitPlan(shown['head'], shown['tree'], updates, message, writer.identity.name,
                      writer.identity.email, timestamp)
    tree, commit = writer.seal(context, plan)
    if tree != shown['proposed_tree']:
        raise ValueError(tr('onboarding.git_attributes_checkout_changed'))
    return CommitIntent(operation_id, run_id, 'IMPORT', shown['head'], shown['fingerprint'], shown['tree'],
                        shown['index_tree'], (), updates, tree, commit, message, plan.author_name,
                        plan.author_email, timestamp)


def execute(context, history, saved, writer, journal):
    journal.checkpoint(history, 'import_commit')
    intent = CommitIntent.from_json(saved['intent'])
    outcome = writer.execute_documents(context, intent, saved['preview']['documents'])
    committed = outcome.status != 'invalidated'
    return replace(history, status='completed' if committed else 'stopped',
                   stop=None if committed else history.stop), {
        'status': 'COMMITTED' if committed else 'INVALIDATED', 'commit': outcome.commit, 'tree': outcome.tree,
        'diagnostic': outcome.diagnostic, 'reconciled': outcome.status == 'reconciled'}
