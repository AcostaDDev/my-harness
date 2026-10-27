"""D072/H6.3 and D088: per-phase document contract (unified layout v2). Standard library, no effects.

SQLite governs operational state and Markdown governs intent. Managed blocks are
deterministic projections of SQLite or files: they are regenerated and compared byte for byte,
never read back as a source. Free values are escaped as inline text, so they
cannot open headings, fences, HTML or markers.
"""

from dataclasses import dataclass
import hashlib
import os
import re
from pathlib import PurePosixPath
import shlex
import stat

from my_harness.core.engine.contracts import RECONCILE_TASK, ContractError
from my_harness.core.engine.document_text import AGENTS, HISTORICAL, SKELETON, STATUS_LABELS, words
from my_harness.core.engine.planning import FIELD_RE, TASK_RE, backticked, bullet_items, collapse
from my_harness.i18n import tr

MAX_DOCUMENT_BYTES = 512 * 1024
# P008-T020: A/B writer with local objects and no lazy fetch; earlier jobs are quarantined.
DOCUMENT_LAYOUT = 'd088-12'
# Same as the default `project_doc_max_bytes` of the pinned Codex; AGENTS.md has at most 60 lines.
MAX_INSTRUCTIONS_BYTES = 32 * 1024
LEGACY_INSTRUCTIONS = 'No project instructions: this frozen context predates the unified document contract (D088).'
BLOCK_REASON = 'Managed documentation blocks (D072)'
BLOCK_NAMES = ('state', 'roadmap', 'decisions')
PHASE_CODE = re.compile(r'P\d{3}')
PHASE_RE = re.compile(r'^##\s+(P\d{3})\s+[—-]\s+(.+?)\s*$', re.MULTILINE)
# D088: the DECISIONS index comes from its own headings and the first «Estado:»/«Status:» line of each one.
DECISION_HEADING = re.compile(r'^##\s+D(\d{3,})\s+[—-]\s+(.+?)\s*$', re.MULTILINE)
DECISION_STATUS = re.compile(r'^(?:\*\*)?(?:Estado|Status)(?::\*\*|\*\*:|:)[ \t]*(.*)$', re.IGNORECASE)
BASE_HEADING = re.compile(r'^##\s+(?:Base acumulada|Accumulated baseline)\s*$', re.MULTILINE)
LEVEL_TWO = re.compile(r'^##\s', re.MULTILINE)
ANY_MARKER = re.compile(r'<!--\s*harness-local:managed-')
# Warnings, never truncation: a document exceeding them asks for compaction during reconciliation.
BUDGETS = {'state': 24 * 1024, 'base': 12 * 1024, 'next_steps': 48 * 1024}
SUMMARY_LIMIT = 600
ROADMAP_FIELDS = {'objective': ('objetivo', 'objective'), 'exit_criteria': ('criterios de salida', 'exit criteria'),
                  'dependencies': ('dependencias', 'dependencies'), 'out_of_scope': ('fuera de alcance', 'out of scope'),
                  'tag': ('tag',)}
# Limits of the instructions template (D088 point 1), checked by tests.
MAX_AGENTS_LINES = 60
MAX_WRAPPER_LINES = 15
MAX_TEMPLATE_COMMANDS = 12


@dataclass(frozen=True)
class Layout:
    """Paths of the unified layout v2 (D088): README and instruction files at the root; the rest under the
    STATE/NEXT_STEPS directory."""

    docs: str
    state: str
    next_steps: str
    readme: str = 'README.md'
    agents: str = 'AGENTS.md'
    claude: str = 'CLAUDE.md'
    gemini: str = 'GEMINI.md'

    def doc(self, name: str) -> str:
        return f'{self.docs}/{name}'

    @property
    def specification(self):
        return self.doc('SPECIFICATION.md')

    @property
    def architecture(self):
        return self.doc('ARCHITECTURE.md')

    @property
    def roadmap(self):
        return self.doc('ROADMAP.md')

    @property
    def decisions(self):
        return self.doc('DECISIONS.md')

    @property
    def ddbb_diagram(self):
        return self.doc('DDBB-DIAGRAM.md')

    @property
    def flows_dir(self):
        return self.doc('flows')

    @property
    def phase_dir(self):
        return self.doc('phase')

    @property
    def archive_dir(self):
        return self.doc('archive')

    def archive(self, code: str) -> str:
        if not PHASE_CODE.fullmatch(code):
            raise ValueError(tr('documents.layout_v2_phases_use'))
        return f'{self.archive_dir}/phase-{code[1:]}'

    @property
    def phase_documents(self) -> tuple[str, ...]:
        """Phase-bound documents (READY and adopted baseline): planning and tracking."""
        return (self.roadmap, self.decisions, self.state, self.next_steps)

    @property
    def product_documents(self) -> tuple[str, ...]:
        return (self.readme, self.specification, self.architecture, self.ddbb_diagram)

    @property
    def instructions(self) -> tuple[str, ...]:
        """Agent instruction files: canonical AGENTS and per-provider wrappers."""
        return (self.agents, self.claude, self.gemini)

    @property
    def harness_owned(self) -> tuple[str, ...]:
        """No normal executor edits them; reconciliation edits their prose except the index."""
        return (self.state, self.next_steps, self.roadmap, self.decisions)

    @property
    def folders(self) -> tuple[str, ...]:
        return (self.flows_dir, self.phase_dir)

    def archived(self, path: str) -> bool:
        return path == self.archive_dir or path.startswith(self.archive_dir + '/')

    def editable(self, path: str) -> bool:
        """Documents the user can edit through a confirmed edit: README, instruction files
        (D088 point 8, P008-T003) and documentation Markdown outside the archive."""
        pure = PurePosixPath(path)
        if path == self.readme or path in self.instructions:
            return True
        return (pure.suffix == '.md' and path.startswith(self.docs + '/') and not self.archived(path)
                and '..' not in pure.parts)


def layout(context) -> Layout | None:
    if getattr(context, 'documents', None) != 'v2':
        return None
    return Layout(str(PurePosixPath(context.state_file).parent), context.state_file, context.next_steps_file)


def protected_write(context, path: str) -> bool:
    """Does the profile reject the harness writing `path` in a confirmed document operation?

    D081: the profile's protected paths restrict the executor and the permissions granted to it. In v2, the
    document contract (README, root instruction files, documentation Markdown and the phase archive) is
    written only with a user confirmation of the exact content and has its own rules, such as the mechanical
    regeneration of blocks in each task commit. Outside that contract, and in v1, the profile protection
    still applies. D088 point 8: AGENTS, CLAUDE and GEMINI are editable and are written on creation,
    confirmed editing and import."""
    from my_harness.core.engine.evidence import matches
    target = layout(context)
    pure = PurePosixPath(path)
    if '..' in pure.parts:
        return True  # Never a contract path; previously only a profile protecting `docs/**` rejected it.
    if target is not None and (target.editable(path) or (target.archived(path) and pure.suffix == '.md')):
        return False
    return matches(path, context.profile.protected_paths)


def executor_protected(context, task_id: str, path: str) -> bool:
    """Does the profile protect `path` from the executor of task `task_id`?

    D088 point 6 (P008-T003): in v2, STATE, NEXT_STEPS, ROADMAP and DECISIONS are governed by the document
    contract (`harness_owned_paths`): no normal task edits them and phase reconciliation edits their prose even
    if the profile also protects them. For every other path, and in v1, the profile decides (D081)."""
    from my_harness.core.engine.evidence import matches
    target = layout(context)
    if target is not None and RECONCILE_TASK.fullmatch(task_id) and path in target.harness_owned:
        return False
    return matches(path, context.profile.protected_paths)


def require_layout(context) -> Layout:
    value = layout(context)
    if value is None:
        raise ValueError(tr('documents.operation_requires_d072_document'))
    return value


def project_instructions(context) -> tuple[str, dict]:
    """D088 point 8 (P008-T007): `AGENTS.md` from the attempt's checkout, complete and with its hash.

    The CLIs do not load it by themselves with their frozen flags, so it enters each role's prompt. It is read
    on every attempt: a change only affects later attempts. Absent, a symlink, not regular, empty, not UTF-8
    or larger than 32 KiB stops the attempt before invoking; it is never truncated. Without a layout (frozen
    contexts predating D088) there is no instruction file to read."""
    target = layout(context)
    if target is None:
        return LEGACY_INSTRUCTIONS, {'path': None, 'sha256': None, 'bytes': 0}
    missing = tr('documents.instructions_required', path=target.agents)
    try:
        path = context.path(target.agents)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise ContractError(missing) from None
    except (OSError, ValueError) as exc:
        raise ContractError(tr('documents.cannot_read_regular_file', agents=target.agents, exc=exc)) from None
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ContractError(tr('documents.regular_file_3', agents=target.agents))
    with os.fdopen(descriptor, 'rb') as file:
        data = file.read(MAX_INSTRUCTIONS_BYTES + 1)
    if len(data) > MAX_INSTRUCTIONS_BYTES:
        raise ContractError(tr('documents.exceeds_bytes_keep_within', agents=target.agents,
                               max_instructions_bytes=MAX_INSTRUCTIONS_BYTES))
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise ContractError(tr('documents.utf_8_text', agents=target.agents)) from None
    if not text.strip() or '\0' in text:
        raise ContractError(tr('documents.contain_nul_free_project', agents=target.agents))
    return text, {'path': target.agents, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


# --- managed blocks ----------------------------------------------------------------------------


def markers(name: str) -> tuple[str, str]:
    return f'<!-- harness-local:managed-{name}:start -->', f'<!-- harness-local:managed-{name}:end -->'


def _span(text: str, name: str):
    begin, end = markers(name)
    if begin not in text and end not in text:
        return None
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(tr('documents.mechanical_markers_occur_exactly'))
    start, stop = text.index(begin), text.index(end)
    if stop < start or (start and text[start - 1] != '\n') or (
            stop + len(end) < len(text) and text[stop + len(end)] not in '\r\n'):
        raise ValueError(tr('documents.mechanical_markers_ordered_occupy'))
    if not text[start + len(begin):].startswith(('\r\n', '\n')) or (stop and text[stop - 1] != '\n'):
        raise ValueError(tr('documents.mechanical_markers_occupy_own'))
    suffix = text[stop + len(end):]
    if suffix and not suffix.startswith(('\r\n', '\n')):
        raise ValueError(tr('documents.mechanical_markers_occupy_own'))
    return start, stop + len(end)


def replace_block(text: str, body: str, name: str = 'state') -> str:
    """Does not normalize or interpret the surrounding prose, including its line endings."""
    begin, end = markers(name)
    block = begin + '\n' + body + end
    span = _span(text, name)
    if span is None:
        return text + ('\n' if text and not text.endswith('\n') else '') + block + '\n'
    return text[:span[0]] + block + text[span[1]:]


def blocks(text: str) -> dict[str, str]:
    """Present blocks, validated; any other managed marker is an error."""
    found = {}
    for name in BLOCK_NAMES:
        span = _span(text, name)
        if span is not None:
            found[name] = text[span[0]:span[1]]
    if len(ANY_MARKER.findall(text)) != 2 * len(found):
        raise ValueError(tr('documents.unknown_partial_my_harness'))
    return found


def without_blocks(text: str) -> str:
    for name in BLOCK_NAMES:
        span = _span(text, name)
        if span is not None:
            text = text[:span[0]] + markers(name)[0] + text[span[1]:]
    return text


# --- escaping and rendering --------------------------------------------------------------------


def inline(value, limit: int | None = None, language: str = HISTORICAL) -> str:
    """Single-line text: no interpretable line breaks, HTML, fences, tables or emphasis."""
    if value is None:
        return '—'
    text = ' '.join(str(value).split())
    if not text:
        return '—'
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + words(language)['truncated']
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_\[\]|#~])', r'\\\1', text)


def _code(value) -> str:
    return '—' if not value else f'`{value[:12]}`'


def validation_counts(report) -> dict | None:
    """OK/KO of a validation: commands and, when there are readable JUnit reports, cases by outcome."""
    if report is None:
        return None
    passed = sum(1 for entry in report.entries if entry.result.passed)
    counts = {'commands_passed': passed, 'commands_failed': len(report.entries) - passed}
    cases = None
    for entry in report.entries:
        for item in entry.reports:
            if item.status not in ('complete', 'partial'):
                continue
            cases = cases or {'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0}
            for case in item.cases:
                cases[case.result if case.result in cases else 'error'] += 1
    return {**counts, 'cases': cases}


def tests_label(tests, language: str = HISTORICAL) -> str:
    if not tests:
        return '—'
    w = words(language)
    parts = []
    cases = tests.get('cases')
    if cases:
        parts.append(f"{cases.get('passed', 0)} OK · {cases.get('failed', 0) + cases.get('error', 0)} KO"
                     + (w['skipped'].format(count=cases['skipped']) if cases.get('skipped') else ''))
    total = tests.get('commands_passed', 0) + tests.get('commands_failed', 0)
    if total:
        parts.append(w['commands'].format(passed=tests.get('commands_passed', 0), total=total))
    return ' · '.join(parts) or '—'


def _questions(snapshot, language) -> list[str]:
    items = snapshot.get('open_questions') or []
    w = words(language)
    return [w['open_questions']] + ([f'- {inline(item)}' for item in items] or [w['none_f']])


def _phase_line(phase, language) -> list[str]:
    w = words(language)
    if phase is None:
        return [w['no_active_phase']]
    lines = [w['phase_line'].format(code=inline(phase['code']), status=inline(phase['status']))]
    if phase.get('objective'):
        lines.append(f"{w['objective']} {inline(phase['objective'])}")
    return lines


def render_state(snapshot: dict, language: str = HISTORICAL) -> str:
    w = words(language)
    lines = [w['state_header'], '']
    lines += _phase_line(snapshot['phase'], language)
    lines += ['', w['state_table'], '|---|---|---|---|---|']
    tasks = snapshot['tasks']
    for task in tasks:
        commit = w['this_commit'] if task.get('committing') else _code(task.get('commit'))
        lines.append(f"| {inline(task['task_id'])} | {inline(task.get('status'))} | {inline(task.get('verdict'))} "
                     f"| {commit} | {inline(tests_label(task.get('tests'), language))} |")
    if not tasks:
        lines.append(f"| — | {w['no_tasks']} | — | — | — |")
    summaries = [task for task in tasks if task.get('summary')]
    if summaries:
        lines += ['', w['executor_summaries']]
        lines += [f"- {inline(task['task_id'])}: {inline(task['summary'], SUMMARY_LIMIT, language)}"
                  for task in summaries]
    lines += [''] + _questions(snapshot, language)
    check = snapshot.get('latest_check')
    if check:
        reasons = '; '.join(check.get('reasons') or []) or w['no_reasons']
        lines += ['', f"{w['latest_check']} {inline(check['status'])} — {inline(reasons, SUMMARY_LIMIT, language)}"]
    return '\n'.join(lines) + '\n'


def render_next_steps(snapshot: dict, language: str = HISTORICAL) -> str:
    w = words(language)
    lines = [w['plan_header'], '']
    lines += _phase_line(snapshot['phase'], language)
    planned = [task for task in snapshot['tasks'] if task.get('planned', True)]
    pending = next((task['task_id'] for task in planned if not task.get('commit') and not task.get('committing')), None)
    if snapshot['phase'] is not None:
        lines.append(w['next_task'] + (inline(pending) if pending else w['no_next_task']))
    lines += ['', w['plan_table'], '|---|---|---|']
    for task in planned:
        commit = w['this_commit'] if task.get('committing') else _code(task.get('commit'))
        lines.append(f"| {inline(task['task_id'])} | {inline(task.get('status') or w['pending'])} | {commit} |")
    if not planned:
        lines.append(f"| — | {w['no_tasks']} | — |")
    extra = [task for task in snapshot['tasks'] if not task.get('planned', True)]
    if extra:
        lines += ['', w['extra_tasks']]
        lines += [f"- {inline(task['task_id'])}: {inline(task.get('status'))}" for task in extra]
    lines += [''] + _questions(snapshot, language)
    return '\n'.join(lines) + '\n'


def render_roadmap(phases: list[dict], language: str = HISTORICAL) -> str:
    w, labels = words(language), STATUS_LABELS[language]
    archived = any(phase.get('archive') for phase in phases)
    lines = [w['roadmap_header'], '', w['roadmap_table'] + (w['archive_column'] if archived else ''),
             '|---|---|---|---|' + ('---|' if archived else '')]
    for phase in phases:
        label = (w['completed'] if archived and phase.get('status') == 'CLOSED'
                 else labels.get(phase.get('status'), phase.get('status')))
        tag = f"`{phase['tag']}`" if phase.get('tag') and phase.get('status') == 'CLOSED' else '—'
        archive = phase.get('archive')
        link = f"[{w['archive_link']}]({archive})" if archive else '—'
        lines.append(f"| {inline(phase['code'])} | {inline(phase['title'])} | {inline(label)} | {tag} |"
                     + (f' {link} |' if archived else ''))
    if not phases:
        lines.append(f"| — | {w['no_phases']} | — | — |")
    return '\n'.join(lines) + '\n'


def render_decisions(entries: list[dict], language: str = HISTORICAL) -> str:
    w = words(language)
    lines = [w['decisions_header'], '', w['decisions_table'], '|---|---|---|']
    for entry in entries:
        lines.append(f"| {inline(entry['id'])} | {inline(entry['title'])} "
                     f"| {inline(entry['status'], SUMMARY_LIMIT, language)} |")
    if not entries:
        lines.append(f"| — | {w['no_decisions']} | — |")
    return '\n'.join(lines) + '\n'


# --- structural reading of intent --------------------------------------------------------------


def _fields(body: str) -> dict[str, str]:
    raw: dict[str, str] = {}
    current = None
    for line in body.splitlines():
        match = FIELD_RE.match(line.strip())
        if match:
            current = match.group(1).strip().rstrip(':').lower()
            raw[current] = match.group(2).strip()
        elif current is not None:
            raw[current] += '\n' + line
    return raw


def _first(raw: dict, names) -> str:
    return next((raw[name].strip() for name in names if raw.get(name, '').strip()), '')


def _section_after(text: str, start: int) -> str:
    following = LEVEL_TWO.search(text, start)
    return text[start:following.start() if following else len(text)]


def parse_roadmap(text: str) -> list[dict]:
    """Phases `## PNNN — title` in document order, with fields in Spanish or English."""
    entries, seen = [], set()
    for match in PHASE_RE.finditer(text):
        code = match.group(1)
        if code in seen:
            raise ValueError(tr('documents.duplicate_roadmap_phase', code=code))
        seen.add(code)
        raw = _fields(_section_after(text, match.end()))
        criteria = bullet_items(_first(raw, ROADMAP_FIELDS['exit_criteria']))
        tag = _first(raw, ROADMAP_FIELDS['tag']).split('\n', 1)[0]
        entries.append({'code': code, 'title': collapse(match.group(2)),
                        'objective': collapse(_first(raw, ROADMAP_FIELDS['objective'])),
                        'exit_criteria': [collapse(item) for item in criteria],
                        'dependencies': collapse(_first(raw, ROADMAP_FIELDS['dependencies'])) or None,
                        'out_of_scope': collapse(_first(raw, ROADMAP_FIELDS['out_of_scope'])) or None,
                        'tag': (backticked(tag) or [collapse(tag)])[0] if tag else None})
    return entries


def plan_tasks(text: str, code: str | None = None) -> list[tuple[str, str]]:
    tasks = [(match.group(1), collapse(match.group(2))) for match in TASK_RE.finditer(text)]
    ids = [task for task, _ in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError(tr('documents.duplicate_task_headings_next'))
    if code is not None and any(not task.startswith(code + '-T') for task in ids):
        raise ValueError(tr('documents.every_next_steps_task', code=code))
    return tasks


def decision_index(text: str | None) -> list[dict]:
    """D088: `## DNNN — title` decisions of DECISIONS.md, with the status from the first `Estado:`/`Status:` line
    of their section (only that line). The managed block is not read. A repeated number, also with different
    zero padding (D7 and D007), is rejected: the index does not choose between two decisions."""
    source = without_blocks(text or '')
    entries, seen = [], {}
    for match in DECISION_HEADING.finditer(source):
        number = int(match.group(1))
        identity = 'D' + match.group(1)
        if number in seen:
            raise ValueError(tr('documents.duplicate_decision_number_decisions', seen=seen[number], identity=identity))
        seen[number] = identity
        status = None
        for line in _section_after(source, match.end()).splitlines():
            found = DECISION_STATUS.match(line.strip())
            if found:
                status = collapse(found.group(1)) or None
                break
        entries.append({'id': identity, 'title': collapse(match.group(2)), 'status': status})
    return sorted(entries, key=lambda item: int(item['id'][1:]))


def base_section(text: str) -> str | None:
    """Literal «Base acumulada»/«Accumulated baseline» section, without any managed block that might follow it."""
    match = BASE_HEADING.search(text)
    if match is None:
        return None
    body = _section_after(text, match.end())
    end = match.end() + len(body)
    marker = ANY_MARKER.search(text, match.start(), end)
    return text[match.start():marker.start() if marker else end]


def phase_data(target: Layout, entry: dict, tasks: list[tuple[str, str]]) -> dict:
    """`PhaseCreate` data derived from ROADMAP §PNNN and NEXT_STEPS; validated by `phase_definition`."""
    return {'code': entry['code'], 'objective': entry['objective'], 'exit_criteria': entry['exit_criteria'],
            'tasks': [task for task, _ in tasks], 'documents': list(target.phase_documents), 'tag': entry['tag']}


def managed_bodies(target: Layout, snapshot: dict, phases: dict,
                   texts: dict[str, str | None], language: str = HISTORICAL) -> dict[str, tuple[str, str]]:
    """Body of each managed block: STATE/NEXT_STEPS from SQLite; ROADMAP and the index also from disk."""
    bodies = {target.state: ('state', render_state(snapshot, language)),
              target.next_steps: ('state', render_next_steps(snapshot, language))}
    if texts.get(target.roadmap) is not None:
        rows = [{'code': entry['code'], 'title': entry['title'], **phases.get(entry['code'], {})}
                for entry in parse_roadmap(texts[target.roadmap])]
        bodies[target.roadmap] = ('roadmap', render_roadmap(rows, language))
    if texts.get(target.decisions) is not None:
        bodies[target.decisions] = ('decisions', render_decisions(decision_index(texts[target.decisions]), language))
    return bodies


def budget_warnings(target: Layout, texts: dict[str, str]) -> list[str]:
    warnings = []
    # D088: DECISIONS is a single register without a budget; agents read only the cited decisions.
    limits = ((target.state, 'state', 'STATE'), (target.next_steps, 'next_steps', 'NEXT_STEPS'))
    for path, key, label in limits:
        text = texts.get(path)
        if text is not None and len(text.encode('utf-8')) > BUDGETS[key]:
            warnings.append(tr('documents.budget', document=label, size=len(text.encode('utf-8')),
                               budget=BUDGETS[key]))
    base = base_section(texts.get(target.state) or '')
    if base is not None and len(base.encode('utf-8')) > BUDGETS['base']:
        warnings.append(tr('documents.base_budget', size=len(base.encode('utf-8')), budget=BUDGETS['base']))
    return warnings


# --- phase archive -----------------------------------------------------------------------------


def render_review(code: str, check: dict | None, status: str, language: str = HISTORICAL) -> str:
    w = words(language)
    lines = [w['review_title'].format(code=code), '', w['review_note'], '']
    if status != 'CLOSED' or not check:
        lines.append(w['review_without_ready'].format(status=inline(status)))
        if check:
            lines.append(w['review_latest'].format(status=inline(check.get('status'))))
        return '\n'.join(lines) + '\n'
    result = check.get('result') or {}
    binding = (check.get('binding') or {})
    lines += [w['review_verdict'].format(status=inline(check.get('status')), head=_code(binding.get('head')),
                                         binding=_code(check.get('binding_sha256'))),
              w['review_summary'].format(summary=inline(result.get('summary'))), '',
              w['exit_criteria_heading'], '', w['criteria_table'], '|---|---|---|']
    for item in result.get('exit_criteria_results') or []:
        lines.append(f"| {inline(item.get('criterion'))} | {w['yes'] if item.get('passed') else w['no']} "
                     f"| {inline(item.get('evidence'))} |")
    validation = check.get('validation')
    if validation is not None:
        entries = validation.get('entries') or []
        passed = sum(1 for entry in entries if (entry.get('result') or {}).get('exit_code') == 0)
        lines += ['', w['baseline_validation'].format(passed=passed, total=len(entries))]
    return '\n'.join(lines) + '\n'


def render_summary(summary: dict, language: str = HISTORICAL) -> str:
    w = words(language)
    phase = summary['phase']
    lines = [w['summary_title'].format(code=phase['code']), '', w['summary_note'], '',
             w['title'].format(title=inline(phase.get('title'))),
             w['final_status'].format(status=inline(phase['status']))
             + (f"`{phase['tag']}`" if phase.get('tag') and phase['status'] == 'CLOSED' else '—')
             + w['definition_version'].format(number=phase['definition_number']),
             f"{w['objective']} {inline(phase['objective'])}", '', w['exit_criteria']]
    lines += [f'- {inline(item)}' for item in phase['exit_criteria']]
    # H6.4: phases archived after 0014 add tokens and turns; earlier ones keep their shape.
    consumption = summary.get('consumption')
    usage = (consumption or {}).get('by_task') or {}
    lines += ['', w['tasks_heading'], '',
              w['summary_table'] + (w['consumption_columns'] if consumption is not None else ''),
              '|---|---|---|---|---|---|---|' + ('---|---|' if consumption is not None else '')]
    for task in summary['tasks']:
        attempts = ', '.join(f'{role} {count}' for role, count in sorted((task.get('attempts') or {}).items())) or '—'
        lines.append(f"| {inline(task['task_id'])} | {inline(task.get('status') or w['no_run'])} "
                     f"| {inline(task.get('verdict'))} "
                     f"| {inline(attempts)} | {inline(task.get('revisions'))} | {_code(task.get('commit'))} "
                     f"| {inline(tests_label(task.get('tests'), language))} |"
                     + (f" {inline(tokens_label(usage.get(task['task_id']), language))} "
                        f"| {inline(turns_label(usage.get(task['task_id']), language))} |"
                        if consumption is not None else ''))
    if not summary['tasks']:
        lines.append(f"| — | {w['no_tasks']} | — | — | — | — | — |" + (' — | — |' if consumption is not None else ''))
    extra = summary.get('extra_tasks') or []
    if extra:
        lines += ['', w['extra_heading'], '']
        lines += [w['extra_item'].format(task=inline(task['task_id']), status=inline(task.get('status')),
                                         commit=_code(task.get('commit'))) for task in extra]
    lines += ['', w['questions_heading'], '']
    questions = summary.get('questions') or []
    lines += [f"- {inline(q['text'])} — {inline(q['status'])}" + (f": {inline(q['answer'])}" if q.get('answer') else '')
              for q in questions] or [w['none_f']]
    lines += ['', w['definitions_heading'], '']
    lines += [w['definition_item'].format(number=item['number'], origin=inline(item['origin']))
              + (f": {inline(item['reason'])}" if item.get('reason') else '')
              for item in summary.get('definitions') or []]
    if consumption is not None:
        lines += ['', w['consumption_heading'], '', w['consumption_note'], '',
                  w['consumption_table'], '|---|---|---|---|---|---|---|---|---|']
        rows = sorted((consumption.get('by_role') or {}).items()) + [('total', consumption['total'])]
        for role, entry in rows:
            cost = entry['cost_usd']['sum']
            lines.append(f"| {inline(role)} | {entry['attempts']} "
                         + ''.join(f"| {_measure(entry[name], entry['attempts'])} " for name in (
                             'uncached_input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens',
                             'total_tokens'))
                         + f"| {inline(turns_label(entry, language))} | {'—' if cost is None else f'{cost:.4f}'} |")
    lines += ['', w['review_link']]
    return '\n'.join(lines) + '\n'


def _measure(value, attempts) -> str:
    """Sum with its coverage: «—» if no attempt provides it (absence, not zero); «n (k/m)» if only some do."""
    if not value or value['sum'] is None:
        return '—'
    return f"{value['sum']}" + (f" ({value['attempts']}/{attempts})" if value['attempts'] != attempts else '')


def tokens_label(entry, language: str = HISTORICAL) -> str:
    if not entry or entry['total_tokens']['sum'] is None:
        return '—'
    covered, attempts = entry['total_tokens']['attempts'], entry['attempts']
    return f"{entry['total_tokens']['sum']}" + (words(language)['attempts_coverage'].format(
        covered=covered, attempts=attempts) if covered != attempts else '')


def turns_label(entry, language: str = HISTORICAL) -> str:
    if not entry:
        return '—'
    w = words(language)
    parts = [f"{entry[key]['sum']} {w[label]}" for key, label in (('turns_reported', 'reported'),
                                                                 ('turns_derived', 'derived'))
             if entry[key]['sum'] is not None]
    return ' · '.join(parts) or '—'


# --- unified v2 document template (D088) ----------------------------------------------------------


def _command_lines(commands, language) -> list[str]:
    """One line per argv, without breaks; an argv that could close the code block is not transcribed."""
    w = words(language)
    lines = []
    for argv in list(commands)[:MAX_TEMPLATE_COMMANDS]:
        line = ' '.join(shlex.join(list(argv)).split())
        lines.append(w['command_omitted'] if '```' in line else line)
    if len(commands) > MAX_TEMPLATE_COMMANDS:
        lines.append(w['more_commands'].format(count=len(commands) - MAX_TEMPLATE_COMMANDS))
    return lines


def _paths(target: Layout) -> dict[str, str]:
    return {'state': target.state, 'next_steps': target.next_steps, 'roadmap': target.roadmap,
            'specification': target.specification, 'architecture': target.architecture,
            'decisions': target.decisions, 'ddbb_diagram': target.ddbb_diagram, 'flows_dir': target.flows_dir,
            'archive_dir': target.archive_dir, 'phase_dir': target.phase_dir, 'readme': target.readme,
            'agents': target.agents, 'claude': target.claude, 'gemini': target.gemini}


def render_agents(target: Layout, name: str, preparation=(), validations=(), language: str = HISTORICAL) -> str:
    """Canonical AGENTS.md (≤60 lines): discovery, unbreakable rules and profile commands."""
    text, paths = AGENTS[language], _paths(target)
    lines = [text['title'].format(name=name), '', text['intro'].format(**paths), '', text['discovery'], '',
             *(step.format(**paths) for step in text['steps']), '', text['rules'], '',
             *(rule.format(**paths) for rule in text['rule_lines']), '', text['commands'], '']
    preparation, validations = _command_lines(preparation, language), _command_lines(validations, language)
    if not preparation and not validations:
        lines.append(text['no_commands'])
    for label, items in ((text['preparation'], preparation), (text['validation'], validations)):
        if items:
            lines += [f'{label}:', '', '```sh', *items, '```', '']
    return '\n'.join(lines).rstrip('\n') + '\n'


def render_wrapper(target: Layout, provider: str, language: str = HISTORICAL) -> str:
    """Provider wrapper (≤15 lines) that imports AGENTS.md."""
    return AGENTS[language]['wrapper'].format(provider=provider, agents=target.agents)


def skeleton(target: Layout, title: str, phase_title: str | None = None, *, preparation=(),
             validations=(), language: str = HISTORICAL) -> dict[str, str]:
    """D088 base documents with empty blocks in place; creation (H6.5) sets the real content.

    `preparation` and `validations`: profile argv for the AGENTS commands section. `flows/` and `phase/`
    have no template file. `language`: the project's work language (D169)."""
    name = inline(title)
    first = inline(words(language)['first_phase'] if phase_title is None else phase_title)
    state_begin, state_end = markers('state')
    road_begin, road_end = markers('roadmap')
    dec_begin, dec_end = markers('decisions')
    values = {**_paths(target), 'name': name, 'first': first, 'state_begin': state_begin, 'state_end': state_end,
              'road_begin': road_begin, 'road_end': road_end, 'dec_begin': dec_begin, 'dec_end': dec_end}
    text = SKELETON[language]
    return {
        target.agents: render_agents(target, name, preparation, validations, language),
        target.claude: render_wrapper(target, 'Claude Code', language),
        target.gemini: render_wrapper(target, 'Gemini CLI', language),
        target.readme: text['readme'].format(**values),
        target.specification: text['specification'].format(**values),
        target.architecture: text['architecture'].format(**values),
        target.roadmap: text['roadmap'].format(**values),
        target.decisions: text['decisions'].format(**values),
        target.ddbb_diagram: text['ddbb_diagram'].format(**values),
        target.state: text['state'].format(**values),
        target.next_steps: text['next_steps'].format(**values),
    }
