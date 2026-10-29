"""P002-T004 (D284, D285): structured project knowledge, pure and standard-library only.

Content schemas per kind and logical document, relationship and ordering rules of a complete revision, change
summaries, canonical hashes, the historical decision-status mapping and the verbatim staging of instruction files.
Storage and adoption live in `my_harness.storage.knowledge`; nothing here reads files or the database.
"""
from dataclasses import dataclass
import hashlib
import re

from my_harness.core.engine.contracts import ContractError, freeze
from my_harness.i18n import tr

CONTENT_FORMAT = 'knowledge-content-1'
REVISION_FORMAT = 'knowledge-revision-1'
KINDS = ('requirement', 'criterion', 'phase', 'task', 'decision', 'section')
DOCUMENTS = ('specification', 'architecture', 'data_model', 'flows', 'instructions')
PROVENANCES = ('known', 'inferred', 'unknown')
SOURCE_KINDS = ('legacy_document', 'legacy_record', 'observation')
ORIGINS = ('owner_confirmed', 'owner_delegated', 'harness_deterministic')
LINK_KINDS = ('part_of', 'criterion_of', 'depends_on', 'addresses', 'supersedes')
ORDERED_LINKS = ('part_of', 'criterion_of')
QUALIFIERS = ('full', 'partial')
TARGETS = ('agents', 'claude', 'gemini')
DECISION_STATUSES = ('proposed', 'accepted', 'rejected', 'retired')
LEGACY_KINDS = ('managed_phase', 'phase_task', 'decision_heading', 'document_section')
MAX_TEXT = 65536

CODES = {
    'requirement': re.compile(r'R\d{3,}'),
    'criterion': re.compile(r'C\d{3,}'),
    'phase': re.compile(r'P\d{3}'),
    'task': re.compile(r'P\d{3}-T\d{3}'),
    'decision': re.compile(r'D\d{3,}'),
    'section': re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*'),
}
STATUSES = {
    'requirement': ('active', 'retired'),
    'criterion': ('active', 'retired'),
    'phase': ('planned', 'withdrawn'),
    'task': ('planned', 'withdrawn'),
    'decision': DECISION_STATUSES,
    'section': ('active', 'retired'),
}
# Field → (required non-empty, nullable). Every other key is refused; the order of keys is irrelevant to hashes.
FIELDS = {
    'requirement': {'title': (True, False), 'statement': (True, False)},
    'criterion': {'statement': (True, False)},
    'phase': {'title': (True, False), 'objective': (True, False), 'tag': (True, True)},
    'task': {'title': (True, False), 'problem': (True, False), 'expected_result': (True, False),
             'evidence': (False, False)},
    'decision': {'title': (True, False), 'context': (False, False), 'decision': (True, False),
                 'alternatives': (False, False), 'consequences': (False, False), 'historical_status': (True, True)},
    'section': {'title': (False, False), 'format': (True, False), 'body': (False, False), 'target': (True, False)},
}
# (link kind) → allowed (source kind, target kind) pairs.
ENDPOINTS = {
    'part_of': {('task', 'phase'), ('section', 'section')},
    'criterion_of': {('criterion', 'requirement'), ('criterion', 'phase'), ('criterion', 'task')},
    'depends_on': {('task', 'task')},
    'addresses': {('phase', 'requirement'), ('task', 'requirement')},
    'supersedes': {('decision', 'decision')},
}


def digest(value) -> str:
    return hashlib.sha256(freeze(value).encode('utf-8')).hexdigest()


def _fail(key: str, **values):
    raise ContractError(tr(f'knowledge.{key}', **values))


def _text(value, name: str, required: bool, nullable: bool):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT or (required and not value.strip()):
        _fail('field', name=name)
    return value


def validate_item(kind: str, code: str, document: str | None) -> None:
    if kind not in KINDS:
        _fail('kind', kind=kind)
    if (kind == 'section') != (document is not None) or document is not None and document not in DOCUMENTS:
        _fail('document', kind=kind, document=document)
    if not isinstance(code, str) or len(code) > 120 or not CODES[kind].fullmatch(code):
        _fail('code', kind=kind, code=code)


def validate_source(provenance: str, source) -> dict | None:
    if provenance not in PROVENANCES:
        _fail('provenance', provenance=provenance)
    if source is None:
        return None
    if (not isinstance(source, dict) or source.get('kind') not in SOURCE_KINDS
            or not set(source) <= {'kind', 'path', 'heading', 'sha256', 'reference'}
            or not all(isinstance(value, str) and value for value in source.values())
            or 'sha256' in source and not re.fullmatch(r'[0-9a-f]{64}', source['sha256'])):
        _fail('source')
    return dict(source)


def validate_content(kind: str, document: str | None, content) -> dict:
    """Normalized copy of `content` (`knowledge-content-1`); text is kept byte for byte."""
    fields = FIELDS[kind]
    expected = set(fields) | {'status'} | ({'subtasks'} if kind == 'task' else set())
    if not isinstance(content, dict) or set(content) != expected:
        _fail('content', kind=kind, fields=', '.join(sorted(expected)))
    result = {name: _text(content[name], name, *rule) for name, rule in fields.items()}
    if content['status'] not in STATUSES[kind]:
        _fail('status', kind=kind, status=content['status'])
    result['status'] = content['status']
    if kind == 'task':
        subtasks = content['subtasks']
        if not isinstance(subtasks, list):
            _fail('field', name='subtasks')
        result['subtasks'] = [_text(item, 'subtasks', True, False) for item in subtasks]
    if kind == 'phase' and result['tag'] is not None and len(result['tag']) > 100:
        _fail('field', name='tag')
    if kind == 'section':
        if result['format'] not in ('markdown', 'mermaid'):
            _fail('field', name='format')
        if result['target'] not in TARGETS or result['target'] != 'agents' and document != 'instructions':
            _fail('target', target=result['target'], document=document)
    return result


def validate_version(kind: str, number: int, content: dict, provenance: str, source) -> None:
    """`retired` decisions exist only as the first version of an imported or migrated record (D284 §3.4)."""
    if kind == 'decision' and content['status'] == 'retired' and (
            number != 1 or source is None or source['kind'] not in ('legacy_document', 'legacy_record')):
        _fail('retired_decision')


def content_sha256(kind: str, document: str | None, code: str, content: dict, provenance: str, source) -> str:
    return digest({'format': CONTENT_FORMAT, 'kind': kind, 'document': document, 'code': code, 'content': content,
                   'provenance': provenance, 'source': source})


@dataclass(frozen=True)
class Member:
    item_id: str
    kind: str
    document: str | None
    code: str
    version: int
    content_sha256: str
    content: dict
    provenance: str
    source: dict | None
    root_position: int | None


@dataclass(frozen=True)
class Link:
    kind: str
    source: str
    target: str
    position: int | None
    qualifier: str | None

    def key(self):
        return (self.kind, self.target, self.position is not None, self.position or 0, self.source)


def knowledge_sha256(project_id: str, members, links) -> str:
    """The knowledge set: members with their exact versions and root order, and every typed, ordered link."""
    return digest({
        'format': REVISION_FORMAT, 'project': project_id,
        'members': [[m.item_id, m.kind, m.document, m.code, m.version, m.content_sha256, m.root_position]
                    for m in sorted(members, key=lambda m: m.item_id)],
        'links': [[l.kind, l.source, l.target, l.position, l.qualifier] for l in sorted(links, key=Link.key)],
    })


def revision_sha256(knowledge: str, project_id: str, number: int, base_sha256: str | None, origin: str, actor: dict,
                    reason: str | None, changes: dict) -> str:
    return digest({'format': REVISION_FORMAT, 'knowledge': knowledge, 'project': project_id, 'number': number,
                   'base': base_sha256, 'origin': origin, 'actor': actor, 'reason': reason, 'changes': changes})


def _dense(positions, what: str) -> None:
    if sorted(positions) != list(range(len(positions))):
        _fail('order', what=what)


def _acyclic(edges: dict[str, list[str]], what: str) -> None:
    state: dict[str, int] = {}
    for start in edges:
        if state.get(start):
            continue
        stack = [(start, iter(edges.get(start, ())))]
        state[start] = 1
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[node] = 2
                stack.pop()
            elif state.get(child) == 1:
                _fail('cycle', what=what)
            elif not state.get(child):
                state[child] = 1
                stack.append((child, iter(edges.get(child, ()))))


def _label(member: Member) -> str:
    return f'{member.kind}:{member.document + "/" if member.document else ""}{member.code}'


def validate_revision(members: dict[str, Member], links, previous: dict | None = None, *, adoption: bool) -> None:
    """Structural rules of a complete revision; `previous` is the base revision's (members, links) when adopting."""
    seen = set()
    by_kind: dict[str, list[Link]] = {kind: [] for kind in LINK_KINDS}
    for link in links:
        source, target = members.get(link.source), members.get(link.target)
        if source is None or target is None or link.source == link.target:
            _fail('link_endpoint', kind=link.kind)
        if link.kind not in LINK_KINDS or (source.kind, target.kind) not in ENDPOINTS[link.kind]:
            _fail('link_kind', kind=link.kind, source=_label(source), target=_label(target))
        if (link.kind, link.source, link.target) in seen:
            _fail('link_duplicate', kind=link.kind)
        seen.add((link.kind, link.source, link.target))
        if (link.position is None) == (link.kind in ORDERED_LINKS):
            _fail('order', what=link.kind)
        if (link.qualifier is None) == (link.kind == 'supersedes') or link.qualifier not in (None, *QUALIFIERS):
            _fail('qualifier', kind=link.kind)
        if link.kind == 'part_of' and source.kind == 'section' and (
                source.document != target.document or source.content['target'] != target.content['target']):
            _fail('section_document', source=_label(source), target=_label(target))
        by_kind[link.kind].append(link)
    for kind in ORDERED_LINKS:
        groups: dict[str, list[int]] = {}
        for link in by_kind[kind]:
            groups.setdefault(link.target, []).append(link.position)
        for target, positions in groups.items():
            _dense(positions, f'{kind} {_label(members[target])}')
    parents: dict[str, list[str]] = {}
    for link in by_kind['part_of'] + by_kind['criterion_of']:
        parents.setdefault(link.source, []).append(link.target)
    roots: dict[str, list[int]] = {}
    for member in members.values():
        owners = parents.get(member.item_id, [])
        if member.kind in ('task', 'criterion') and len(owners) != 1:
            _fail('owner', item=_label(member))
        if member.kind == 'section' and len(owners) > 1:
            _fail('owner', item=_label(member))
        is_root = member.kind == 'section' and not owners
        if is_root != (member.root_position is not None):
            _fail('root_order', item=_label(member))
        if is_root:
            roots.setdefault(member.document, []).append(member.root_position)
        if adoption and member.kind == 'decision' and member.content['status'] == 'proposed':
            _fail('proposed_decision', item=_label(member))
    for document, positions in roots.items():
        _dense(positions, f'roots of {document}')
    for kind in ('part_of', 'depends_on', 'supersedes'):
        edges: dict[str, list[str]] = {}
        for link in by_kind[kind]:
            edges.setdefault(link.source, []).append(link.target)
        _acyclic(edges, kind)
    full: dict[str, int] = {}
    for link in by_kind['supersedes']:
        if members[link.target].content['status'] != 'accepted' or members[link.source].content['status'] not in (
                'accepted', 'proposed'):
            _fail('supersedes_status', item=_label(members[link.target]))
        if link.qualifier == 'full':
            full[link.target] = full.get(link.target, 0) + 1
            if full[link.target] > 1:
                _fail('supersedes_full', item=_label(members[link.target]))
    if previous is None:
        return
    old_members, old_links = previous['members'], previous['links']
    for item_id, old in old_members.items():
        if old.kind == 'decision' and old.content['status'] != 'proposed':
            current = members.get(item_id)
            if current is None or current.version != old.version:
                _fail('decision_frozen', item=_label(old))
    current_links = {(l.kind, l.source, l.target, l.qualifier) for l in by_kind['supersedes']}
    for link in old_links:
        if link.kind == 'supersedes' and (link.kind, link.source, link.target, link.qualifier) not in current_links:
            _fail('decision_frozen', item=_label(old_members[link.target]))
    for link in by_kind['supersedes']:
        if (old_members.get(link.target) is None or old_members[link.target].content['status'] != 'accepted') and (
                link.kind, link.source, link.target, link.qualifier) not in {
                (l.kind, l.source, l.target, l.qualifier) for l in old_links}:
            _fail('supersedes_earlier', item=_label(members[link.target]))


def _group(member: Member) -> str:
    return f'section:{member.document}' if member.kind == 'section' else member.kind


def change_summary(members: dict[str, Member], links, previous: dict | None) -> dict:
    """Added/changed/removed items per kind (sections per logical document), structural change and the sensitive
    entries (requirements, criteria and instructions) that T005 enforcement reads (TM05)."""
    old_members = previous['members'] if previous else {}
    old_links = previous['links'] if previous else ()
    groups: dict[str, dict[str, list[str]]] = {}

    def note(member: Member, change: str):
        groups.setdefault(_group(member), {'added': [], 'changed': [], 'removed': []})[change].append(member.code)
    for item_id, member in members.items():
        old = old_members.get(item_id)
        if old is None:
            note(member, 'added')
        elif old.version != member.version:
            note(member, 'changed')
    for item_id, old in old_members.items():
        if item_id not in members:
            note(old, 'removed')
    for entry in groups.values():
        for codes in entry.values():
            codes.sort()
    def roots(source):
        return {i: m.root_position for i, m in source.items() if m.root_position is not None}
    structure = sorted(links, key=Link.key) != sorted(old_links, key=Link.key) or roots(members) != roots(old_members)
    sensitive = sorted(f'{group}:{code}' for group, entry in groups.items()
                       if group in ('requirement', 'criterion', 'section:instructions')
                       for codes in entry.values() for code in codes)
    return {'items': dict(sorted(groups.items())), 'structure_changed': structure, 'sensitive': sensitive}


# Historical decision statuses (D284 §3.4). English and Spanish status lines are recognized, as by the parsers.
_STATUS_LINE = re.compile(r'^\s*(?:Status|Estado)\s*:\s*(.*)$', re.I)
_LEADING = (
    ('superseded', re.compile(r'(?:(?:partially|parcialmente)\s+)?(?:superseded|sustituid[ao]s?|reemplazad[ao]s?)\b', re.I)),
    ('rejected', re.compile(r'(?:rejected|discarded|withdrawn|rechazad[ao]s?|descartad[ao]s?|retirad[ao]s?)\b', re.I)),
    ('accepted', re.compile(r'(?:accepted|aceptad[ao]s?)\b', re.I)),
    ('proposed', re.compile(r'(?:proposed|pending|draft|propuest[ao]s?|pendientes?|borrador)\b', re.I)),
)
_SUPERSEDED_BY = re.compile(
    r'(?:superseded|sustituid[ao]s?|reemplazad[ao]s?)\s+(?:by|por)\s+([^;.]*)', re.I)
_PARTIAL = re.compile(r'\b(?:partially|partial|in part|parcialmente|parcial|en parte)\b', re.I)
_DECISION_CODE = re.compile(r'\bD(\d{3,})(?:\s*[–-]\s*D(\d{3,}))?')


def _codes(text: str) -> list[str]:
    codes = []
    for first, last in _DECISION_CODE.findall(text):
        width = len(first)
        for number in range(int(first), int(last or first) + 1):
            codes.append(f'D{number:0{width}d}')
    return codes


def map_decision_status(status_line: str | None, known_codes=()) -> dict:
    """Canonical result for a historical status line; never defaults an unknown status to `accepted` (INV-09).

    `status` is `accepted`, `rejected`, `retired`, `proposed` (draft-only) or None (owner choice required);
    `supersedes` lists `(code, qualifier)` links *into* this decision from identifiable decisions of the same set,
    with qualifier None when the extent needs the owner's choice; `report` lists what the preview must show.
    """
    known = set(known_codes)
    line = (status_line or '').strip()
    found = _STATUS_LINE.match(line)
    text = (found.group(1) if found else line).strip()
    leading = next((name for name, pattern in _LEADING if pattern.match(text)), None)
    result = {'status': None, 'historical_status': line or None, 'supersedes': [], 'report': []}
    if leading is None:
        result['report'].append('unrecognized_status')
        return result
    clauses = _SUPERSEDED_BY.findall(text)
    superseders = [code for clause in clauses for code in _codes(clause)]
    linked = [code for code in dict.fromkeys(superseders) if code in known]
    if superseders and len(linked) < len(set(superseders)):
        result['report'].append('superseder_not_in_set')
    if leading == 'superseded':
        partial = bool(_PARTIAL.search(text))
        if not linked:
            result['status'] = 'retired'
            result['report'].append('retired_without_superseder')
        else:
            result['status'] = 'accepted'
            qualifier = 'partial' if partial else 'full' if len(linked) == 1 else None
            result['supersedes'] = [(code, qualifier) for code in linked]
            if qualifier is None:
                result['report'].append('supersession_extent_required')
    elif leading == 'accepted':
        result['status'] = 'accepted'
        # An accepted decision with a "superseded by" clause is superseded in part only.
        result['supersedes'] = [(code, 'partial') for code in linked]
    elif leading == 'rejected':
        result['status'] = 'rejected'
    else:
        result['status'] = 'proposed'
        result['report'].append('proposed_stays_draft')
    return result


# Verbatim staging of instruction files into `instructions` sections (D285).
_HEADING = re.compile(r'^(#{1,6})[ \t]+(.*?)[ \t]*$')
_FENCE = re.compile(r'^\s{0,3}(```|~~~)')
_IMPORT = re.compile(r'^@AGENTS\.md[ \t]*$')


def slug(text: str) -> str:
    return '-'.join(re.findall(r'[a-z0-9]+', text.lower())) or 'section'


def _split(text: str):
    """(level, title, heading line, body) per heading-delimited part; the part before the first heading has
    level 0. Headings inside fenced code are body text."""
    lines = text.splitlines(keepends=True)
    parts = [[0, '', '', []]]
    fence = None
    for line in lines:
        bare = line.rstrip('\r\n')
        marker = _FENCE.match(bare)
        if fence is not None:
            if marker and marker.group(1) == fence:
                fence = None
        elif marker:
            fence = marker.group(1)
        elif (heading := _HEADING.match(bare)):
            parts.append([len(heading.group(1)), heading.group(2), line, []])
            continue
        parts[-1][3].append(line)
    return [(level, title, heading, ''.join(body)) for level, title, heading, body in parts]


def stage_instructions(agents_text: str, wrappers: dict[str, str] | None = None) -> dict:
    """Draft sections for the `instructions` document, kept verbatim, with explicit root order and loss report.

    Each section is `{code, title, body, target, parent, position}`; `parent` is a code or None and `position` is the
    order among the parent's children or, for a root, among the roots of its target. Nothing is adopted here.
    """
    sections: list[dict] = []
    report: list[dict] = []
    used: set[str] = set()
    counts: dict[str | None, int] = {}  # roots share one order per document, across targets

    def unique(code: str) -> str:
        candidate, n = code, 2
        while candidate in used:
            candidate, n = f'{code}-{n}', n + 1
        used.add(candidate)
        return candidate

    def stage(text: str, target: str, prefix: str):
        stack: list[tuple[int, str]] = []
        for level, title, heading, body in _split(text):
            if level == 0:
                if not body:
                    continue
                code, parent = unique(f'{prefix}preamble'), None
            else:
                expected = '#' * level + ' ' + title
                if heading.rstrip('\r\n') != expected:
                    report.append({'kind': 'heading_normalized', 'target': target, 'heading': title})
                while stack and stack[-1][0] >= level:
                    stack.pop()
                if stack and level != stack[-1][0] + 1 or not stack and level != 1:
                    report.append({'kind': 'heading_level', 'target': target, 'heading': title})
                parent = stack[-1][1] if stack else None
                code = unique(prefix + slug(title))
                stack.append((level, code))
            position = counts.get(parent, 0)
            counts[parent] = position + 1
            sections.append({'code': code, 'title': title, 'body': body, 'target': target, 'parent': parent,
                             'position': position})
    stage(agents_text, 'agents', '')
    for target, text in sorted((wrappers or {}).items()):
        if target not in TARGETS or target == 'agents':
            _fail('target', target=target, document='instructions')
        kept = ''.join(line for line in text.splitlines(keepends=True) if not _IMPORT.match(line.rstrip('\r\n')))
        if kept != text:
            report.append({'kind': 'import_directive', 'target': target})
        if kept.strip():
            stage(kept, target, f'{target}-')
    return {'sections': sections, 'report': report}
