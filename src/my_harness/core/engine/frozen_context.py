"""P002-T007: deterministic, bounded context and knowledge exposures. No I/O.

Ranges index Unicode code points in canonical JSON (queries) or rendered section text (instructions).
Hashes always cover UTF-8 bytes of the actual exposure, independently of the source content hash.
"""
from hashlib import sha256
import json
import re

from my_harness.core.engine.contracts import freeze, context_snapshot
from my_harness.core.engine.trace_payload import SECRET_VALUES
from my_harness.i18n import tr

FORMAT = 'frozen-context-2'
LEGACY_FORMAT = 'frozen-context-1'  # immutable body-only snapshots remain readable, never upgraded in place
MAX_CONTEXT = 256 * 1024
MAX_SOURCES = 100
MAX_RESULT = 64 * 1024
MAX_PROMPT = 1024 * 1024
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}')


def digest(text):
    return sha256(text.encode('utf-8')).hexdigest()


def profile_capture(context):
    data = freeze(json.loads(context_snapshot(context))['profile'])
    return {'id': 'profile:' + digest(context.profile.name), 'version': digest(data), 'data': data,
            'sha256': digest(data), 'provenance': 'frozen_project_context'}


class ContextError(ValueError):
    def __init__(self, code):
        super().__init__(tr('context.invalid'))
        self.code = code


def fail(code='invalid'):
    raise ContextError(code)


def metadata(member):
    return {'item_id': member.item_id, 'kind': member.kind, 'document': member.document,
            'code': member.code, 'version': member.version, 'content_sha256': member.content_sha256,
            'title': (member.content.get('title') or '')[:200],
            'title_truncated': len(member.content.get('title') or '') > 200,
            'status': member.content['status']}


def exposure(member, *, level='metadata', start=0, length=2048, budget=8192):
    item = metadata(member)
    raw = freeze(item) if level == 'metadata' else freeze(member.content)
    if start > len(raw):
        fail()
    stop = len(raw) if level in ('full', 'metadata') else min(len(raw), start + length)
    part = raw[start:stop]
    while len(part.encode('utf-8')) > budget:
        part = part[:max(0, len(part) - max(1, (len(part.encode('utf-8')) - budget) // 4))]
    end = start + len(part)
    actual = 'metadata' if level == 'metadata' else 'full' if start == 0 and end == len(raw) else 'excerpt'
    return {'identity': item, 'exposure': actual, 'data': part, 'digest': digest(part),
            'range': {'unit': 'unicode_codepoint', 'start': start, 'end': end, 'total': len(raw)},
            'truncated': end < len(raw) or start > 0}


def assemble(revision, item_ids, *, client, profile, code, context_format=FORMAT):
    """Explicit relevance selection; all applicable accepted instructions are mandatory, in tree order.
    Profile/code inputs are content-bound captures supplied by trusted services, never canonical knowledge.
    """
    if (context_format not in (FORMAT, LEGACY_FORMAT) or client not in ('codex', 'claude', 'gemini')
            or len(item_ids) > 50 or len(set(item_ids)) != len(item_ids)
            or len(code) > 48):
        fail()
    ordered = []

    pending = list(reversed([(item_id, 1) for item_id in revision.roots('instructions')
                            if revision.members[item_id].content['target'] in ('agents', client)]))
    while pending:
        item_id, level = pending.pop()
        member = revision.members[item_id]
        if member.content['status'] == 'active':
            ordered.append((member, level))
        if len(ordered) > MAX_SOURCES:
            fail('over_limit')
        pending.extend((child, level + 1) for child in reversed(revision.children('part_of', item_id)))
    instructions = [(m, level) for target in ('agents', client) for m, level in ordered
                    if m.content['target'] == target and m.content['status'] == 'active']
    if not instructions or not any(m.content['target'] == 'agents' for m, _ in instructions):
        fail('entity_missing')
    entries = []
    for member, level in instructions:
        body = member.content['body']
        if context_format == FORMAT and member.content['title']:
            # Accepted tree depth supplies the heading level; preserve the full title and verbatim body.
            body = '#' * level + ' ' + member.content['title'] + '\n' + body
        entries.append({'authority': 'canonical', 'purpose': 'instructions', 'identity': metadata(member),
                        'provenance': member.provenance, 'source': member.source,
                        'data': body, 'digest': digest(body), 'exposure': 'full'})
    for item_id in sorted(item_ids):
        member = revision.members.get(item_id)
        if member is None:
            fail('entity_missing')
        if member.document == 'instructions':
            continue  # mandatory instruction selection above owns target filtering and order
        data = freeze({'content': member.content, 'provenance': member.provenance, 'source': member.source,
                       'links': [dict(kind=l.kind, source=l.source, target=l.target, position=l.position,
                                      qualifier=l.qualifier) for l in sorted(revision.links, key=lambda l: l.key())
                                 if item_id in (l.source, l.target)]})
        entries.append({'authority': 'canonical', 'purpose': 'knowledge', 'identity': metadata(member),
                        'data': data, 'digest': digest(data), 'exposure': 'full'})
    for purpose, values in (('profile', [profile]), ('code', code)):
        for value in values:
            if not isinstance(value, dict) or set(value) != {'id', 'version', 'data', 'sha256', 'provenance'}:
                fail()
            if (not all(isinstance(value[k], str) for k in value) or not IDENTIFIER.fullmatch(value['id']) or
                    not IDENTIFIER.fullmatch(value['version']) or digest(value['data']) != value['sha256']):
                fail()
            if any(pattern.search(value[k]) for k in ('id', 'version') for pattern in SECRET_VALUES):
                fail()
            entries.append({'authority': 'capture', 'purpose': purpose, 'identity': {
                'item_id': value['id'], 'version': value['version'], 'kind': purpose},
                'provenance': value['provenance'], 'data': value['data'], 'digest': value['sha256'], 'exposure': 'full'})
    result = {'format': context_format, 'project_id': revision.project_id, 'revision_id': revision.id,
              'revision_sha256': revision.revision_sha256, 'client': client, 'entries': entries,
              'instructions': '\n\n'.join(e['data'] for e in entries if e['purpose'] == 'instructions')}
    if len(entries) > MAX_SOURCES or len(freeze(result).encode('utf-8')) > MAX_CONTEXT:
        fail('over_limit')
    return result


def verify(payload, expected):
    if len(payload.encode('utf-8')) > MAX_CONTEXT or digest(payload) != expected:
        fail()
    result = json.loads(payload)
    if result['format'] not in (FORMAT, LEGACY_FORMAT) or len(result['entries']) > MAX_SOURCES:
        fail()
    if any(digest(e['data']) != e['digest'] for e in result['entries']):
        fail()
    return result


def prompt_tail(data):
    return '\nFrozen context (' + data['revision_id'] + '):\n' + '\n\n'.join(
        freeze({k: v for k, v in e.items() if k != 'data'}) + '\n' + e['data']
        for e in data['entries'] if e['purpose'] != 'instructions')
