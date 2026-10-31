"""D294: deterministic knowledge views and untrusted, explicit document parsing. No IO."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import re

from my_harness.core.engine import knowledge as k
from my_harness.core.engine.contracts import freeze

FORMAT = 'harness-documents-1'
RENDERER = 'harness-knowledge-markdown-1'
OWNERSHIP = 'harness-ownership-1'
PORTABLE = 'harness-project-1'
META = 'docs/.harness/knowledge.json'
MAX_FILE = 512 * 1024
MAX_TOTAL = 4 * 1024 * 1024
PATHS = {'specification': 'docs/SPECIFICATION.md', 'architecture': 'docs/ARCHITECTURE.md',
         'data_model': 'docs/DDBB-DIAGRAM.md', 'flows': 'docs/flows/knowledge.md',
         'requirement': 'docs/SPECIFICATION.md', 'criterion': 'docs/SPECIFICATION.md',
         'phase': 'docs/ROADMAP.md', 'task': 'docs/NEXT_STEPS.md', 'decision': 'docs/DECISIONS.md'}
INSTRUCTIONS = {'agents': 'AGENTS.md', 'claude': 'CLAUDE.md', 'gemini': 'GEMINI.md'}
LANGUAGES = ('en', 'es')


def titles_for(language):
    from my_harness.i18n import message
    keys = ('specification', 'architecture', 'data_model', 'flows', 'requirement', 'phase', 'task', 'decision', 'state')
    return {key: message('documents.heading.' + key, language) for key in keys}


class DocumentError(ValueError):
    def __init__(self, code, **location):
        super().__init__(code)
        self.code, self.location = code, location


def fail(code, **location):
    raise DocumentError(code, **location)


def sha(data):
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def loads(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('duplicate_json_key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: fail('invalid_json_number'))


def closed(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        fail('unsupported_fields')


def snapshot(revision):
    return {'source_project_id': revision.project_id,
            'revision': {'id': revision.id, 'number': revision.number, 'sha256': revision.revision_sha256},
            'members': [asdict(m) for m in sorted(revision.members.values(), key=lambda m: m.item_id)],
            'links': [asdict(l) for l in sorted(revision.links, key=k.Link.key)]}


def ownership(project, language, wrappers=()):
    if language not in LANGUAGES or len(set(wrappers)) != len(wrappers) or set(wrappers) - {'claude', 'gemini'}:
        fail('invalid_manifest')
    paths = set(PATHS.values()) | {META, 'docs/STATE.md', 'AGENTS.md'} | {INSTRUCTIONS[w] for w in wrappers}
    return {'format': OWNERSHIP, 'renderer': RENDERER, 'destination': project, 'work_language': language,
            'targets': [{'path': p, 'role': next(('instructions:' + key for key, path in INSTRUCTIONS.items() if path == p),
                next((key for key, path in PATHS.items() if path == p), 'metadata' if p == META else 'state')),
                'required': True} for p in sorted(paths)]}


def validate_snapshot(data):
    closed(data, ('source_project_id', 'revision', 'members', 'links'))
    closed(data['revision'], ('id', 'number', 'sha256'))
    if not isinstance(data['source_project_id'], str) or not data['source_project_id']:
        fail('invalid_source_project')
    members = {}
    for m in data['members']:
        closed(m, ('item_id', 'kind', 'document', 'code', 'version', 'content_sha256', 'content', 'provenance',
                   'source', 'root_position'))
        if not isinstance(m['item_id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', m['item_id']):
            fail('invalid_identity')
        if m['item_id'] in members or type(m['version']) is not int or m['version'] < 1:
            fail('duplicate_identity')
        k.validate_item(m['kind'], m['code'], m['document'])
        k.validate_content(m['kind'], m['document'], m['content'])
        k.validate_source(m['provenance'], m['source'])
        members[m['item_id']] = k.Member(**m)
    links = []
    for link in data['links']:
        closed(link, ('kind', 'source', 'target', 'position', 'qualifier'))
        links.append(k.Link(**link))
    k.validate_revision(members, links, None, adoption=False)
    return members, links


def _ordered(data):
    members = {m['item_id']: m for m in data['members']}
    parents = {l['source']: l['target'] for l in data['links'] if l['kind'] == 'part_of'}
    positions = {l['source']: l['position'] for l in data['links'] if l['kind'] == 'part_of'}
    def key(m):
        ident = m['item_id']
        if ident in parents:
            return key(members[parents[ident]]) + (positions[ident],)
        return (m['root_position'] if m['root_position'] is not None else 0,)
    return sorted(data['members'], key=lambda m: (m['document'] or m['kind'], key(m), m['code']))


def _path(m, members, links):
    if m['document'] == 'instructions':
        return INSTRUCTIONS[m['content']['target']]
    if m['kind'] == 'criterion':
        owner = next(l['target'] for l in links if l['kind'] == 'criterion_of' and l['source'] == m['item_id'])
        return PATHS[members[owner]['kind']]
    return PATHS[m['document'] or m['kind']]


def render(data, manifest):
    validate_snapshot(data)
    expected = ownership(manifest['destination'], manifest['work_language'],
                         [w for w in ('claude', 'gemini') if INSTRUCTIONS[w] in {t['path'] for t in manifest['targets']}])
    if expected != manifest or manifest['renderer'] != RENDERER:
        fail('invalid_manifest')
    language = manifest['work_language']
    titles = titles_for(language)
    files = {p: '# ' + titles[key] + '\n' for key, p in PATHS.items() if key != 'criterion'}
    files['docs/STATE.md'] = _state(data, language)
    for target, path in INSTRUCTIONS.items():
        if path in {t['path'] for t in manifest['targets']}:
            files[path] = '' if target == 'agents' else '@AGENTS.md\n'
    metadata = deepcopy(data)
    metadata['members'] = deepcopy(_ordered(data))
    metadata.update(format=FORMAT, renderer=RENDERER, work_language=language, ownership_sha256=k.digest(manifest))
    by_id = {m['item_id']: m for m in data['members']}
    exported = {m['item_id']: m for m in metadata['members']}
    for m in _ordered(data):
        path = _path(m, by_id, data['links'])
        if path not in files:
            fail('unselected_instruction_wrapper')
        item = exported[m['item_id']]
        fields = {}
        if m['document'] == 'instructions':
            depth, parent = 1, m['item_id']
            while (link := next((l for l in data['links'] if l['kind'] == 'part_of' and l['source'] == parent), None)):
                depth += 1
                parent = link['target']
            title = m['content']['title']
            prefix = '#' * depth + ' ' + title + '\n' if title else ''
            start = len(files[path])
            files[path] += prefix + m['content']['body'] + '\n'
            fields['body'] = {'path': path, 'instruction': True, 'depth': depth,
                              'start': start, 'length': len(prefix + m['content']['body'] + '\n')}
            del item['content']['body']
        else:
            files[path] += '\n## ' + m['code'] + (' — ' + m['content'].get('title', '') if m['content'].get('title') else '') + '\n'
            for name, value in sorted(m['content'].items()):
                if not isinstance(value, str) or name in ('title', 'status', 'target', 'format', 'tag', 'historical_status'):
                    continue
                display = value
                fence = None
                if name == 'body' and m['content'].get('format') == 'mermaid':
                    longest = max((len(run) for run in re.findall(r'`+', value)), default=0)
                    fence = '`' * max(3, longest + 1)
                    display = fence + 'mermaid\n' + value + '\n' + fence
                token, i = 'f0', 0
                while token in display:
                    i += 1
                    token = f'f{i}'
                files[path] += (f'<!-- harness:field {m["item_id"]} {name} {token} -->\n' + display
                                + f'\n<!-- harness:end {m["item_id"]} {name} {token} -->\n')
                fields[name] = {'path': path, 'token': token}
                if fence:
                    fields[name]['fence'] = fence
                del item['content'][name]
        item['fields'] = fields
    metadata['decoration'] = {p: sha(_strip_fields(text)) for p, text in files.items() if p not in INSTRUCTIONS.values()}
    files[META] = freeze(metadata)
    for p, text in files.items():
        if len(text.encode('utf-8')) > (65536 if p in INSTRUCTIONS.values() else MAX_FILE):
            fail('document_size')
        if p in INSTRUCTIONS.values() and len(text.splitlines()) > (60 if p == 'AGENTS.md' else 15):
            fail('instruction_budget')
    if sum(len(t.encode('utf-8')) for t in files.values()) > MAX_TOTAL:
        fail('document_total_size')
    return dict(sorted(files.items()))


FIELD = re.compile(r'<!-- harness:field ([a-zA-Z0-9_-]+) ([a-z_]+) (f\d+) -->\n(.*?)\n<!-- harness:end \1 \2 \3 -->\n', re.S)


def _strip_fields(text):
    return FIELD.sub(lambda m: m[0][:m.start(4) - m.start()] + m[0][m.end(4) - m.start():], text)


def _parse(files):
    """Returns proposed selected members and located diagnostics; absent inputs never imply removal."""
    if not isinstance(files, dict):
        fail('metadata_required')
    if META not in files:
        return _instruction_import(files)
    for p, value in files.items():
        if p not in set(PATHS.values()) | set(INSTRUCTIONS.values()) | {META, 'docs/STATE.md'}:
            fail('unsupported_path')
        if not isinstance(value, str) or len(value.encode('utf-8')) > MAX_FILE:
            fail('document_size', path=p)
    if sum(len(v.encode('utf-8')) for v in files.values()) > MAX_TOTAL:
        fail('document_total_size')
    meta = loads(files[META])
    closed(meta, ('format', 'renderer', 'source_project_id', 'revision', 'members', 'links', 'work_language',
                  'ownership_sha256', 'decoration'))
    if meta['format'] != FORMAT or meta['renderer'] != RENDERER or meta['work_language'] not in LANGUAGES:
        fail('unsupported_format')
    report, selected = [], []
    expected_decoration = _decoration(meta)
    matches = {}
    for p, text in files.items():
        if p == META or p in INSTRUCTIONS.values():
            continue
        found = list(FIELD.finditer(text))
        for match in found:
            key = (match[1], match[2])
            if key in matches:
                fail('duplicate_field')
            matches[key] = (p, match[3], match[4])
        if _strip_fields(text) != expected_decoration.get(p):
            report.append({'code': 'uncontained_or_changed_decoration', 'path': p, 'blocking': True})
    spans = _instruction_spans(meta, files)
    instruction_parts = {p: k._split(text.removeprefix('@AGENTS.md\n') if p != 'AGENTS.md' else text)
                         for p, text in files.items() if p in INSTRUCTIONS.values() and p not in spans}
    for p in instruction_parts:
        instruction_parts[p] = [part for part in instruction_parts[p] if part[0] or part[3]]
    for p in files:
        if p in INSTRUCTIONS.values() and p != 'AGENTS.md':
            report.append({'code': 'import_directive', 'path': p, 'blocking': False})
    used = set()
    identities = set()
    for original in meta['members']:
        closed(original, ('item_id', 'kind', 'document', 'code', 'version', 'content_sha256', 'content',
                          'provenance', 'source', 'root_position', 'fields'))
        if original['item_id'] in identities:
            fail('duplicate_identity')
        identities.add(original['item_id'])
        m = deepcopy(original)
        fields = m.pop('fields')
        present = []
        for name, loc in fields.items():
            if loc.get('instruction'):
                closed(loc, ('path', 'instruction', 'depth', 'start', 'length'))
                if m['document'] != 'instructions' or name != 'body':
                    fail('invalid_instruction_field')
            else:
                closed(loc, ('path', 'token', 'fence') if 'fence' in loc else ('path', 'token'))
            p = loc['path']
            if p not in files:
                present.append(False)
                continue
            present.append(True)
            if loc.get('instruction'):
                parts = spans[p] if p in spans else instruction_parts[p]
                if not parts:
                    fail('instruction_identity_choice_required')
                depth, title, _heading, body = parts.pop(0)
                if depth != (loc['depth'] if m['content']['title'] else 0):
                    fail('instruction_identity_choice_required')
                if not body.endswith('\n'):
                    fail('instruction_framing')
                m['content']['title'], m['content'][name] = title, body[:-1]
            else:
                key = (m['item_id'], name)
                if key not in matches or matches[key][:2] != (p, loc['token']):
                    fail('missing_field', path=p, item=m['item_id'], field=name)
                body = matches[key][2]
                if loc.get('fence'):
                    prefix, suffix = loc['fence'] + 'mermaid\n', '\n' + loc['fence']
                    if not body.startswith(prefix) or not body.endswith(suffix):
                        fail('missing_mermaid_fence')
                    body = body[len(prefix):-len(suffix)]
                m['content'][name] = body
                used.add(key)
        if any(present) and not all(present):
            fail('missing_field')
        if not present or all(present):
            selected.append(m)
        else:
            report.append({'code': 'retained_unselected', 'item': m['item_id'], 'blocking': False})
    if set(matches) != used or any(instruction_parts.values()) or any(spans.values()):
        fail('unknown_field_or_instruction')
    links = set()
    for link in meta['links']:
        closed(link, ('kind', 'source', 'target', 'position', 'qualifier'))
        marker = (link['kind'], link['source'], link['target'])
        if marker in links:
            fail('duplicate_link')
        links.add(marker)
    # Outgoing relationships belong to selected entities; omitted sources confer no import consent.
    selected_ids = {m['item_id'] for m in selected}
    return {'source_project_id': meta['source_project_id'], 'revision': meta['revision'],
            'members': selected, 'links': [l for l in meta['links'] if l['source'] in selected_ids]}, report, meta['work_language']


def portable(data, language):
    validate_snapshot(data)
    value = deepcopy(data)
    for m in value['members']:
        source = m['source']
        if source and source.get('path') and (source['path'].startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', source['path']) or '..' in source['path'].split('/')):
            fail('portable_absolute_source')
    payload = {'knowledge': value, 'work_language': language}
    return freeze({'format': PORTABLE, 'payload': payload, 'sha256': k.digest(payload)})


def _parse_portable(text):
    if len(text.encode('utf-8')) > MAX_TOTAL:
        fail('document_total_size')
    value = loads(text)
    closed(value, ('format', 'payload', 'sha256'))
    closed(value['payload'], ('knowledge', 'work_language'))
    if value['format'] != PORTABLE or k.digest(value['payload']) != value['sha256']:
        fail('portable_integrity')
    data, language = value['payload']['knowledge'], value['payload']['work_language']
    if language not in LANGUAGES:
        fail('invalid_language')
    validate_snapshot(data)
    for member in data['members']:
        if member['content_sha256'] != k.content_sha256(member['kind'], member['document'], member['code'],
                member['content'], member['provenance'], member['source']):
            fail('portable_content_integrity')
    if portable(data, language) != freeze(value):
        fail('portable_integrity')
    return data, [], language


def parse(files):
    try:
        return _parse(files)
    except (KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
        raise ValueError('invalid_document_shape') from exc


def parse_portable(text):
    try:
        return _parse_portable(text)
    except (KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
        raise ValueError('invalid_portable_shape') from exc


def _decoration(meta):
    """Recompute decoration from proposed scalars; an untrusted digest cannot authorize dropping prose."""
    titles = titles_for(meta['work_language'])
    files = {p: '# ' + titles[key] + '\n' for key, p in PATHS.items() if key != 'criterion'}
    files['docs/STATE.md'] = _state(meta, meta['work_language'])
    members = {m['item_id']: m for m in meta['members']}
    for m in _ordered(meta):
        if m['document'] == 'instructions':
            continue
        path = _path(m, members, meta['links'])
        files[path] += '\n## ' + m['code'] + (' — ' + m['content'].get('title', '') if m['content'].get('title') else '') + '\n'
        for name, loc in sorted(m['fields'].items()):
            token = loc['token']
            if loc['path'] != path:
                fail('field_path_mismatch')
            files[path] += f'<!-- harness:field {m["item_id"]} {name} {token} -->\n\n<!-- harness:end {m["item_id"]} {name} {token} -->\n'
    return files


def _instruction_import(files):
    if not files or set(files) - set(INSTRUCTIONS.values()):
        fail('metadata_required')
    if any(not isinstance(value, str) or len(value.encode('utf-8')) > MAX_FILE for value in files.values()):
        fail('document_size')
    staged = k.stage_instructions(files.get('AGENTS.md', ''),
        {target: files[path] for target, path in INSTRUCTIONS.items() if target != 'agents' and path in files})
    members, links = [], []
    identifiers = {s['code']: 'i-' + sha(s['code'])[:32] for s in staged['sections']}
    for section in staged['sections']:
        content = {'title': section['title'], 'body': section['body'], 'format': 'markdown',
                   'target': section['target'], 'status': 'active'}
        source = {'kind': 'legacy_document', 'path': INSTRUCTIONS[section['target']],
                  'heading': section['title'] or 'preamble', 'sha256': sha(files[INSTRUCTIONS[section['target']]])}
        members.append({'item_id': identifiers[section['code']], 'kind': 'section', 'document': 'instructions',
            'code': section['code'], 'version': 1, 'content_sha256': k.content_sha256('section', 'instructions',
                section['code'], content, 'known', source), 'content': content, 'provenance': 'known', 'source': source,
            'root_position': section['position'] if section['parent'] is None else None})
        if section['parent']:
            links.append({'kind': 'part_of', 'source': identifiers[section['code']],
                'target': identifiers[section['parent']], 'position': section['position'], 'qualifier': None})
    report = [{'code': r['kind'], 'path': INSTRUCTIONS[r['target']], 'blocking': False} for r in staged['report']]
    report.append({'code': 'instruction_identity_mapping', 'blocking': False})
    return {'source_project_id': 'instructions-' + k.digest(files),
            'revision': {'id': 'selected-instructions', 'number': 1, 'sha256': k.digest(files)},
            'members': members, 'links': links}, report, None


def _instruction_spans(meta, files):
    """Exact span framing retains rich bodies containing headings. Edited ambiguous structure needs mapping."""
    result = {}
    for path in INSTRUCTIONS.values():
        if path not in files:
            continue
        value = files[path]
        cursor = 0 if path == 'AGENTS.md' else len('@AGENTS.md\n')
        if cursor and not value.startswith('@AGENTS.md\n'):
            continue
        parts = []
        for m in meta['members']:
            loc = m['fields'].get('body', {})
            if not loc.get('instruction') or loc.get('path') != path:
                continue
            if type(loc.get('start')) is not int or type(loc.get('length')) is not int:
                break
            if loc['start'] != cursor or loc['length'] < 1:
                break
            chunk = value[cursor:cursor + loc['length']]
            title, depth = m['content']['title'], loc['depth']
            prefix = '#' * depth + ' ' + title + '\n' if title else ''
            if not chunk.startswith(prefix) or not chunk.endswith('\n'):
                break
            parts.append((depth if title else 0, title, prefix, chunk[len(prefix):]))
            cursor += loc['length']
        else:
            if cursor == len(value):
                result[path] = parts
    return result


def _state(data, language):
    text = '# ' + titles_for(language)['state'] + '\n\n' + data['revision']['sha256'] + '\n'
    for member in sorted(data['members'], key=lambda m: (m['document'] or m['kind'], m['code'])):
        if member['content'].get('title'):
            code = (member['document'] + '/' if member['document'] else '') + member['code']
            text += '\n- ' + code + ' — ' + member['content']['title']
    return text + '\n'
