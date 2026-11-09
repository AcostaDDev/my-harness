"""Owner-confirmed conversion of the installed documentary lane (P002-T026)."""
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from my_harness.core.engine import documents as legacy, knowledge as k, knowledge_documents as d
from my_harness.core.engine.phases import digest as definition_digest
from my_harness.core.engine.planning import FIELD_NAMES, TASK_RE, bullet_items
from my_harness.i18n import tr
from my_harness.services.knowledge_delivery import read
from my_harness.storage.models import (
    PhaseDefinitionRow, PhaseRow,
    ProjectBootstrapRow, ProjectImportRow,
)

FORMAT = 'harness-installed-knowledge-1'
RECEIPT = 'installed_conversion'
ROLES = (*k.DOCUMENTS, 'roadmap', 'plan', 'decisions')
DECISIONS = ('accepted', 'rejected', 'retired')
REQUIREMENT = re.compile(r'^##\s+(R\d{3,})\s+[—-]\s+(.+?)\s*$')


def refuse(code, **params):
    raise ValueError(tr(f'installed_knowledge.{code}', **params))


def _sources(session, root, selections, phases):
    """Bind each selected path to a persisted adoption and to the exact bytes available now."""
    inventories = {row.id: row.documents for row in phases}
    for row in session.scalars(select(PhaseDefinitionRow).join(PhaseRow).where(PhaseRow.root == root)):
        inventories[row.id] = row.documents
    for model in (ProjectBootstrapRow, ProjectImportRow):
        row = session.scalar(select(model).where(model.root == root, model.status == 'COMPLETED'))
        if row:
            inventories[row.id] = (row.result['documents'] if model is ProjectBootstrapRow
                                   else {doc['path']: doc['sha256'] for doc in row.preview['result_tree']})
    files, total = {}, 0
    for selection in selections:
        d.closed(selection, ('path', 'role', 'adoption_id'))
        path, role, adoption = (selection[key] for key in ('path', 'role', 'adoption_id'))
        if not all(isinstance(value, str) and value for value in (path, role, adoption)):
            refuse('plan')
        if role not in ROLES or path in files:
            refuse('plan')
        expected = inventories.get(adoption, {}).get(path)
        try:
            content = read(root, path) if expected else None
        except (OSError, ValueError):
            refuse('source', path=path, adoption=adoption)
        if content is None or d.sha(content) != expected:
            refuse('source', path=path, adoption=adoption)
        total += len(content.encode('utf-8'))
        if total > d.MAX_TOTAL:
            refuse('plan')
        files[path] = {**selection, 'sha256': expected, 'content': content}
    return files


def _definitions(session, phases):
    result = {}
    for phase in phases:
        row = session.scalar(select(PhaseDefinitionRow).where(PhaseDefinitionRow.phase_id == phase.id,
                                                             PhaseDefinitionRow.number == phase.definition_number))
        sha = definition_digest(phase.definition)
        if row is None or phase.definition_sha256 != sha or row.definition_sha256 != sha or row.definition != phase.definition:
            refuse('definition', phase=phase.id)
        result[phase.id] = {'definition_id': row.id, 'number': row.number, 'sha256': sha,
                            'definition': row.definition, 'adopted_documents': phase.documents}
    return result


class Conversion:
    def __init__(self, root):
        self.root = root
        self.members = {}
        self.keys = {}
        self.links = []
        self.mappings = []
        self.report = []
        self.orders = defaultdict(int)

    def note(self, code, **detail):
        self.report.append({'code': code, **detail})

    def item(self, kind, code, content, source, *, document=None, root_position=None, provenance='known', mapping=None):
        k.validate_item(kind, code, document)
        content = k.validate_content(kind, document, content)
        k.validate_source(provenance, source)
        identity = str(uuid5(NAMESPACE_URL, f'{FORMAT}:{k.digest([self.root, kind, document, code])}'))
        if identity in self.members:
            refuse('duplicate', identity=code)
        sha = k.content_sha256(kind, document, code, content, provenance, source)
        self.members[identity] = k.Member(identity, kind, document, code, 1, sha, content, provenance, source, root_position)
        self.keys[(kind, document, code)] = identity
        if mapping:
            self.mappings.append({'legacy_kind': mapping[0], 'legacy_ref': mapping[1],
                                  'item_id': identity, 'legacy_sha256': source['sha256']})
        return identity

    def link(self, kind, source, target, qualifier=None):
        position = None
        if kind in k.ORDERED_LINKS:
            position = self.orders[kind, target]
            self.orders[kind, target] += 1
        self.links.append(k.Link(kind, source, target, position, qualifier))

    def section(self, code, title, body, source, *, document, target='agents', parent=None):
        position = None
        if parent is None:
            position = self.orders['root', document]
            self.orders['root', document] += 1
        ident = self.item('section', code, {'title': title, 'body': body, 'target': target, 'format': 'markdown',
                                           'status': 'active'}, source, document=document, root_position=position,
                          mapping=('document_section', f"{source['path']}#{code}"))
        if parent:
            self.link('part_of', ident, parent)
        return ident

    def criteria(self, texts, owner, source):
        for statement in texts:
            code = f'C{1 + self.orders["criteria", None]:03}'
            self.orders['criteria', None] += 1
            ident = self.item('criterion', code, {'statement': statement, 'status': 'active'}, source)
            self.link('criterion_of', ident, owner)

    def phase(self, code, title, objective, tag, criteria, source, *, mapping=None):
        if not objective:
            self.note('phase_objective_unknown', item=code)
        phase = self.item('phase', code,
                          {'title': title, 'objective': objective or '[unknown]', 'tag': tag, 'status': 'planned'},
                          source, provenance='known' if objective else 'unknown', mapping=mapping)
        self.criteria(criteria, phase, source)

    def task(self, code, owner, source, *, title=None, body=None, legacy_code):
        phase = self.keys.get(('phase', None, owner))
        if not phase:
            refuse('reference', identity=owner)
        raw = legacy._fields(body or '')
        fields = {name: legacy._first(raw, FIELD_NAMES[name])
                  for name in ('objective', 'deliverables', 'validation', 'acceptance_criteria')}
        problem = body if body and body.strip() else None
        result = fields['deliverables'] or fields['objective']
        unknown = [name for name, value in (('problem', problem), ('expected_result', result)) if not value]
        if unknown:
            self.note('task_fields_unknown', item=code, fields=unknown)
        ident = self.item('task', code, {
            'title': title or code, 'problem': problem or '[unknown]', 'expected_result': result or '[unknown]',
            'evidence': fields['validation'], 'subtasks': [], 'status': 'planned',
        }, source, provenance='unknown' if unknown else 'known', mapping=('phase_task', legacy_code))
        self.link('part_of', ident, phase)
        self.criteria(bullet_items(fields['acceptance_criteria']), ident, source)


def _document_source(file, heading=None):
    return {'kind': 'legacy_document', 'path': file['path'], 'sha256': file['sha256'],
            'reference': file['adoption_id'], **({'heading': heading} if heading else {})}


def _entries(text, pattern):
    # _split understands fences. Rejoin child headings and their bodies for each level-two entry.
    match, content = None, []
    for level, _, heading, body in k._split(legacy.without_blocks(text)):
        if level in (0, 1, 2):
            if match:
                yield match, ''.join(content)
            match, content = pattern.fullmatch(heading.rstrip('\r\n')), [body]
        elif match:
            content.extend((heading, body))
    if match:
        yield match, ''.join(content)


def _decisions(conversion, files, choices):
    entries, seen = {}, set()
    for file in files:
        for match, body in _entries(file['content'], legacy.DECISION_HEADING):
            code, number = 'D' + match[1], int(match[1])
            if number in seen:
                refuse('duplicate', identity=code)
            seen.add(number)
            status = next((line for line in body.splitlines() if legacy.DECISION_STATUS.match(line.strip())), None)
            entries[code] = (match[2], body, status, file)
    if set(choices) - set(entries):
        refuse('plan')
    proposals, pending_links = [], []
    for code, (title, body, status, file) in entries.items():
        source = _document_source(file, code)
        value = k.map_decision_status(legacy.DECISION_STATUS.match(status.strip())[1] if status else None, entries)
        choice = choices.get(code, {})
        if not isinstance(choice, dict) or set(choice) - {'status', 'extents'}:
            refuse('plan')
        for report in value['report']:
            conversion.note(report, item=code, path=file['path'])
        canonical = value['status']
        if canonical is None:
            canonical = choice.get('status')
            if canonical not in (*DECISIONS, 'proposed'):
                conversion.note('decision_status_choice_required', item=code, blocking=True)
                continue
        elif 'status' in choice:
            refuse('plan')
        extents = choice.get('extents', {})
        missing = {superseder for superseder, extent in value['supersedes'] if extent is None}
        if not isinstance(extents, dict) or set(extents) - missing or any(e not in k.QUALIFIERS for e in extents.values()):
            refuse('plan')
        for superseder, extent in value['supersedes']:
            extent = extent or extents.get(superseder)
            if extent:
                pending_links.append((superseder, code, extent))
            else:
                conversion.note('decision_extent_choice_required', item=code, superseder=superseder, blocking=True)
        content = {'title': title, 'context': '', 'decision': body if body.strip() else title,
                   'alternatives': '', 'consequences': '', 'historical_status': status, 'status': canonical}
        ident = conversion.item('decision', code, content, source, mapping=('decision_heading', code),
                                provenance='known' if value['status'] is not None else 'inferred')
        if canonical == 'proposed':
            proposals.append(ident)
    for superseder, code, extent in pending_links:
        source, target = [conversion.keys.get(('decision', None, c)) for c in (superseder, code)]
        if source and target:
            conversion.link('supersedes', source, target, extent)
        else:
            conversion.note('decision_reference_unresolved', item=code, superseder=superseder, blocking=True)
    return proposals


def _canonical_codes(conversion, kind, originals, choices):
    groups, resolved = defaultdict(list), {}
    for original in originals:
        code = choices.get(original, original)
        if not k.CODES[kind].fullmatch(code):
            conversion.note('canonical_code_required', kind=kind, item=original, blocking=True)
            resolved[original] = None
        else:
            groups[code].append(original)
            resolved[original] = code
    for code, sources in groups.items():
        if len(sources) > 1:
            conversion.note('canonical_code_collision', kind=kind, item=code, sources=sorted(sources), blocking=True)
            for original in sources:
                resolved[original] = None
    return resolved


def _convert(root, definitions, files, plan):
    conversion = Conversion(root)
    plan_tasks, roadmap, decision_files, instructions = {}, {}, [], {}
    for file in files.values():
        role, content = file['role'], file['content']
        source = _document_source(file)
        if role == 'roadmap':
            for match, body in _entries(content, legacy.PHASE_RE):
                code = match[1]
                if code in roadmap:
                    refuse('duplicate', identity=code)
                roadmap[code] = (legacy.roadmap_entry(code, match[2], body), _document_source(file, code))
            conversion.note('roadmap_prose_preserved_in_source', path=file['path'])
        elif role == 'plan':
            for match, body in _entries(content, TASK_RE):
                if match[1] in plan_tasks:
                    refuse('duplicate', identity=match[1])
                plan_tasks[match[1]] = (match[2], body, _document_source(file, match[1]))
            conversion.note('plan_prose_preserved_in_source', path=file['path'])
        elif role == 'decisions':
            decision_files.append(file)
            conversion.note('decision_prose_preserved_in_source', path=file['path'])
        elif role == 'instructions':
            target = Path(file['path']).stem.lower()
            if target not in k.TARGETS or target in instructions:
                refuse('plan')
            instructions[target] = file
        else:
            code = k.slug(file['path'])
            conversion.section(code, file['path'], content, source, document=role)
            if role == 'specification':
                for match, body in _entries(content, REQUIREMENT):
                    conversion.item('requirement', match[1],
                        {'title': match[2], 'statement': body, 'status': 'active'}, _document_source(file, match[1]))

    phase_records, task_owners = {}, {}
    for phase_id, record in definitions.items():
        value = record['definition']
        original = value['code']
        if original in phase_records:
            refuse('duplicate', identity=original)
        source = {'kind': 'legacy_record', 'reference': record['definition_id'], 'sha256': record['sha256']}
        phase_records[original] = (phase_id, value, source)
        for task in value['tasks']:
            if task in task_owners:
                refuse('duplicate', identity=task)
            task_owners[task] = (original, source)

    # A selected heading and a definition can describe the same original identity.
    # Resolve their shared code before combining content or creating links and mappings.
    phase_origins = dict.fromkeys((*phase_records, *roadmap))
    task_origins = dict.fromkeys((*task_owners, *plan_tasks))
    codes = plan.get('codes', {})
    if (set(codes) - (phase_origins.keys() | task_origins.keys())
            or not all(isinstance(value, str) for value in codes.values())):
        refuse('plan')
    phase_codes = _canonical_codes(conversion, 'phase', phase_origins, codes)
    task_codes = _canonical_codes(conversion, 'task', task_origins, codes)
    for original, code in phase_codes.items():
        if code is None:
            continue
        if original in phase_records:
            phase_id, value, source = phase_records[original]
            title = code
            if original in roadmap:
                entry, documentary = roadmap[original]
                title = entry['title']
                if any(entry[key] != value[key] for key in ('objective', 'tag', 'exit_criteria')):
                    conversion.note('phase_definition_precedence', item=code, path=documentary['path'])
            conversion.phase(code, title, value['objective'], value['tag'], value['exit_criteria'], source,
                             mapping=('managed_phase', phase_id))
        else:
            entry, source = roadmap[original]
            conversion.phase(code, entry['title'], entry['objective'], entry['tag'], entry['exit_criteria'], source)
    for original, code in task_codes.items():
        if code is None:
            continue
        owner, source = task_owners.get(original, (original.rsplit('-T', 1)[0], None))
        if owner not in phase_codes:
            refuse('reference', identity=owner)
        phase = phase_codes[owner]
        if phase is None:
            task_codes[original] = None
            continue
        title, body, source = plan_tasks.get(original, (None, None, source))
        conversion.task(code, phase, source, title=title, body=body, legacy_code=original)

    if instructions:
        staged = k.stage_instructions(instructions.get('agents', {}).get('content', ''),
            {target: file['content'] for target, file in instructions.items() if target != 'agents'})
        for report in staged['report']:
            conversion.note('instruction_structure', **report)
        for section in staged['sections']:
            target, parent = section['target'], section['parent']
            conversion.section(section['code'], section['title'], section['body'],
                _document_source(instructions[target], section['code']), document='instructions', target=target,
                parent=conversion.keys.get(('section', 'instructions', parent)))
    proposals = _decisions(conversion, decision_files, plan['decisions'])
    resolved_codes = {'phase': phase_codes, 'task': task_codes}
    blocked_targets = {(kind, None, codes.get(original, original)) for kind, resolved in resolved_codes.items()
                       for original, code in resolved.items() if code is None}
    for relation in plan['links']:
        d.closed(relation, ('kind', 'source', 'target'))
        if relation['kind'] not in ('depends_on', 'addresses'):
            refuse('plan')
        endpoints = []
        for endpoint in (relation['source'], relation['target']):
            if (not isinstance(endpoint, list) or len(endpoint) != 3
                    or any(part is not None and not isinstance(part, str) for part in endpoint)):
                refuse('plan')
            kind, document, original = endpoint
            code = resolved_codes.get(kind, {}).get(original, original) if document is None else original
            ident = conversion.keys.get((kind, document, code))
            if code is not None and ident is None and (kind, document, code) not in blocked_targets:
                refuse('reference', identity=endpoint)
            endpoints.append(ident)
        if None not in endpoints:
            conversion.link(relation['kind'], *endpoints)
    return conversion, proposals


def validate_plan(root, plan):
    if not isinstance(plan, dict) or set(plan) - {'format', 'files', 'decisions', 'links', 'codes'}:
        refuse('plan')
    if (plan.get('format') != FORMAT or not isinstance(plan.get('files'), list)
            or not isinstance(plan.get('decisions'), dict) or not isinstance(plan.get('links'), list)
            or not isinstance(plan.get('codes', {}), dict)):
        refuse('plan')
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        refuse('root')
    return str(root)


def preview(session, root, project, plan):
    phases = list(session.scalars(select(PhaseRow).where(PhaseRow.root == root).order_by(PhaseRow.code)))
    if not phases or any(row.definition.get('knowledge') for row in phases):
        refuse('no_source')
    definitions = _definitions(session, phases)
    files = _sources(session, root, plan['files'], phases)
    conversion, proposals = _convert(root, definitions, files, plan)
    omitted = sorted({path for row in definitions.values() for path in row['adopted_documents']} - set(files))
    if omitted:
        conversion.note('adopted_documents_not_selected', paths=omitted)
    accepted = {ident: item for ident, item in conversion.members.items() if ident not in proposals}
    links = [link for link in conversion.links if link.source in accepted and link.target in accepted]
    k.validate_revision(conversion.members, conversion.links, adoption=False)
    k.validate_revision(accepted, links, adoption=True)
    return {'format': FORMAT, 'root': root, 'destination_project': project, 'plan': plan,
            'definitions': definitions, 'files': files,
            'members': [asdict(item) for item in accepted.values()], 'links': [asdict(link) for link in links],
            'proposals': [asdict(conversion.members[ident]) for ident in proposals],
            'proposal_links': [asdict(link) for link in conversion.links if link not in links],
            'mapping': conversion.mappings, 'report': conversion.report}
