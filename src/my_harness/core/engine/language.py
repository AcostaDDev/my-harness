"""P011-T009 (D169): the engine's language directive, sealed outside the editable templates.

The pair comes only from the job's frozen `language-context-1` (D167); it is never read again from the mutable
preferences nor replaced by a template variable. `render_attempt` appends the directive next to the engine schema,
so both providers receive it in the stdin prompt they already use: no new flag, system prompt or permission.
Jobs admitted before D167 (no pair, or the visual-only `ui-language-1` of D166) are rendered as before.
"""

from my_harness.core.engine.contracts import ContractError

DIRECTIVE = 'language-directive-1'
FORMAT = 'language-context-1'
EARLIER_FORMATS = ('ui-language-1',)
NAMES = {'en': 'English', 'es': 'Spanish'}

# Field map of T001 §4 by role: V = visual language (to the user), W = work language (documents and code).
# Everything else in the schema is T: literal values, never translated.
FIELDS = {
    'judge': (('rationale',), ('proposal.text',)),
    'planner': (('executor_selection.reason',),
                ('title', 'objective', 'executor_prompt', 'acceptance_criteria[]')),
    'executor': (('result',),
                 ('decision_proposals[].title/decision/rationale', 'the files, code and comments you write')),
    'reviewer': (('findings[].problem', 'blocking_questions[]', 'executor_selection.reason'),
                 ('next_prompt', 'decision_proposals[].title/decision/rationale')),
    'phase': (('summary', 'required_actions[]', 'blocking_questions[]', 'exit_criteria_results[].evidence'), ()),
    'chat': (('answer', 'proposals[].rationale'),
             ('proposals[].title/objective/scope/acceptance_criteria[]',
              'prose instructions in proposals[].validation[]')),
    'definition': (('answer', 'questions[].text', 'drafts[].reason', 'pending[]'), ('drafts[].content',)),
    'planning': (('answer', 'questions[].text', 'plan.reason', 'pending[]'), ('plan.content',)),
}
TECHNICAL = {
    'judge': 'duty, outcome, evidence_ids, option_id, intent_id, requirement_ids, duration and alternative',
    'planner': 'task_id, phase_id, allowed_paths/forbidden_paths globs, validation_commands[] and the model/effort '
               'selection',
    'executor': 'paths, public identifiers, tool names and original outputs',
    'reviewer': 'verdict, task_id, findings[].severity/category/file and scope_grants',
    'phase': 'phase_id, verdict, passed and exit_criteria_results[].criterion, copied exactly from the frozen '
             'criterion',
    'chat': 'references[] and the literal commands inside proposals[].validation[]',
    'definition': 'drafts[].path and questions[].blocking',
    'planning': 'questions[].blocking, a null plan, paths and ids',
}
# D088 headings and field labels in each work language; the parsers read both (`planning.FIELD_NAMES`).
LABELS = {
    'en': ('"## PNNN — <title>" with "**Objective:**" and "**Exit criteria:**"; tasks "## PNNN-TNNN — <title>" with '
           '"**Objective:**", "**Allowed paths:**", "**Acceptance criteria:**", "**Validation commands:**" and '
           '"**Executor:**"; "## Shared constraints"; decisions "## DNNN — <title>" with a first "Status:" line; '
           'STATE "## Accumulated baseline" and "## Active phase — PNNN <title>"; "No persistence"'),
    'es': ('"## PNNN — <título>" con "**Objetivo:**" y "**Criterios de salida:**"; tareas "## PNNN-TNNN — <título>" '
           'con "**Objetivo:**", "**Rutas permitidas:**", "**Criterios de aceptación:**", "**Comandos de '
           'validación:**" y "**Ejecutor:**"; "## Restricciones compartidas"; decisiones "## DNNN — <título>" con una '
           'primera línea "Estado:"; STATE "## Base acumulada" y "## Fase activa — PNNN <título>"; "Sin persistencia"'),
}


def frozen_pair(language: dict | None, context) -> tuple[str, str] | None:
    """(visual, work) of the job, or None for a job admitted before the pair existed. An unknown format, an
    invalid value or a work language other than the frozen context's blocks the attempt before invoking."""
    if language is None or (isinstance(language, dict) and language.get('format') in EARLIER_FORMATS):
        return None
    if not isinstance(language, dict) or language.get('format') != FORMAT:
        raise ContractError('Unknown frozen language context; the attempt is not rendered')
    ui, work = language.get('ui_language'), language.get('work_language')
    if ui not in NAMES or work not in NAMES:
        raise ContractError('Invalid frozen language pair; the attempt is not rendered')
    if getattr(context, 'work_language', None) not in (None, work):
        raise ContractError('The frozen work language differs from the project context')
    return ui, work


def directive(role: str, ui: str, work: str) -> str:
    if role not in FIELDS:
        raise ContractError('No language field map for role')
    visual, documents = FIELDS[role]
    ui_name, work_name = NAMES[ui], NAMES[work]
    written = (f'- In {work_name}: ' + ', '.join(documents) + ', and any document or code you write.'
               if documents else '- This answer writes no document; quote frozen criteria and sources unchanged.')
    return '\n'.join([
        f'Language directive ({DIRECTIVE}). My Harness sets it from the languages frozen for this job; it '
        'prevails over any other language instruction in this prompt, its templates or the project files.',
        f'Respond to the user in {ui_name}. Write project documentation and code in {work_name}.',
        f'- In {ui_name}: ' + ', '.join(visual) + '.',
        written,
        f'- Literal, never translated: {TECHNICAL[role]}; JSON keys, enum values, paths, commands, identifiers, '
        'managed markers and codes.',
        '- Existing files, logs and quotes in another language are read and cited as they are; never translate or '
        'rename existing files, identifiers or interfaces.',
        f'- Document headings and field labels in {work_name}: {LABELS[work]}.',
    ]) + '\n'
