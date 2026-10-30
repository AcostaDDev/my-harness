"""P002-T005 (D286): versioned logical catalogue of typed domain operations (D275). Pure, standard library.

Every entry has an id and version, a kind (query, propose, adopt, effect), the principals and agent roles that may
attempt it, closed input and output schemas, and capability requirements; all of them are covered by the entry's
schema digest. A call presents (id, version, digest); a mismatch is refused without falling back to another version.
No entry reads or writes files, runs code or accepts SQL. The schema subset is validated here, not by a dependency,
so a digest never changes with a library version.
"""
from dataclasses import dataclass, field, replace
import hashlib
import re
from typing import Mapping

from my_harness.core.engine import knowledge
from my_harness.core.engine.contracts import freeze
from my_harness.i18n import tr

FORMAT = 'domain-catalogue-1'
KINDS = ('query', 'propose', 'adopt', 'effect')
PRINCIPALS = ('owner', 'harness', 'agent')
ROLES = ('reviewer', 'executor', 'judge')
# Caller identity is bound by trusted infrastructure, never chosen through arguments (INV-11, TM04).
RESERVED = frozenset({'project', 'project_id', 'role', 'caller', 'principal', 'invocation_id', 'attempt_id',
                      'origin', 'actor', 'authorization_id'})
MAX_ARGUMENTS = 2 * 1024 * 1024  # canonical JSON bytes of one call's arguments
_TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}


class SchemaError(ValueError):
    def __init__(self, path: str, reason: str):
        super().__init__(f'{path}: {reason}')
        self.path, self.reason = path, reason


def _is(value, name: str) -> bool:
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(schema: Mapping, value, path: str = '$') -> None:
    """The subset used by the catalogue: type, const, enum, string/integer/array bounds, pattern, closed objects
    with required properties, and oneOf with exactly one match."""
    if 'oneOf' in schema:
        matches = 0
        for option in schema['oneOf']:
            try:
                validate(option, value, path)
            except SchemaError:
                continue
            matches += 1
        if matches != 1:
            raise SchemaError(path, 'one_of')
        return
    types = schema.get('type')
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_is(value, name) for name in types):
            raise SchemaError(path, 'type')
    if 'const' in schema and value != schema['const']:
        raise SchemaError(path, 'const')
    if 'enum' in schema and value not in schema['enum']:
        raise SchemaError(path, 'enum')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', len(value)):
            raise SchemaError(path, 'length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise SchemaError(path, 'pattern')
    elif _is(value, 'integer'):
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise SchemaError(path, 'range')
    elif isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', len(value)):
            raise SchemaError(path, 'items')
        for index, item in enumerate(value):
            validate(schema.get('items', {}), item, f'{path}[{index}]')
    elif isinstance(value, dict):
        properties = schema.get('properties', {})
        for name in schema.get('required', ()):
            if name not in value:
                raise SchemaError(f'{path}.{name}', 'required')
        for name, item in value.items():
            if name in properties:
                validate(properties[name], item, f'{path}.{name}')
            elif schema.get('additionalProperties', True) is False:
                raise SchemaError(f'{path}.{name}', 'unexpected')


def lint(schema: Mapping, path: str = '$') -> list[str]:
    """Problems of a catalogue schema: reserved caller names anywhere, or an object without explicit closure."""
    problems = []
    for option in schema.get('oneOf', ()):
        problems += lint(option, path)
    types = schema.get('type')
    if types == 'object' or isinstance(types, list) and 'object' in types:
        if 'additionalProperties' not in schema:
            problems.append(f'{path}: closure')
        for name, item in schema.get('properties', {}).items():
            if name in RESERVED:
                problems.append(f'{path}.{name}: reserved')
            problems += lint(item, f'{path}.{name}')
    if 'items' in schema:
        problems += lint(schema['items'], f'{path}[]')
    return problems


def digest(value) -> str:
    return hashlib.sha256(freeze(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True, eq=False)
class Entry:
    id: str
    version: int
    kind: str
    principals: tuple[str, ...]
    roles: tuple[str, ...]
    input: Mapping
    output: Mapping
    # Additional `product` targets computed per call: 'propose' (groups touched) or 'adopt' (classes adopted).
    product: str | None = None
    summary: str = ''
    schema_sha256: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'schema_sha256', digest(self.document()))

    def document(self) -> dict:
        return {'format': FORMAT, 'id': self.id, 'version': self.version, 'kind': self.kind,
                'principals': list(self.principals), 'roles': list(self.roles), 'input': self.input,
                'output': self.output, 'capabilities': {'tools': self.tool_target, 'product': self.product},
                'summary': self.summary}

    @property
    def ref(self) -> tuple[str, int, str]:
        return self.id, self.version, self.schema_sha256

    @property
    def tool_target(self) -> str:
        return f'domain:{self.id}@{self.version}'

    @property
    def mutates(self) -> bool:
        return self.kind != 'query'


class Catalogue:
    def __init__(self, entries, retired=()):
        self._entries = {(entry.id, entry.version): entry for entry in entries}
        if len(self._entries) != len(entries):
            raise ValueError(tr('domain.catalogue_duplicate'))
        self.retired = frozenset(retired)
        for entry in entries:
            problems = lint(entry.input) + lint(entry.output)
            if entry.kind not in KINDS or not set(entry.principals) <= set(PRINCIPALS) or problems or (
                    not set(entry.roles) <= set(ROLES)) or bool(entry.roles) != ('agent' in entry.principals):
                raise ValueError(tr('domain.catalogue_entry', operation=entry.id, problems='; '.join(problems)))
        self.sha256 = digest({'format': FORMAT, 'entries': sorted(
            [e.id, e.version, e.schema_sha256, (e.id, e.version) in self.retired] for e in entries)})

    def __iter__(self):
        return iter(self._entries.values())

    def get(self, operation_id: str, version: int) -> Entry | None:
        return self._entries.get((operation_id, version))

    def current(self, operation_id: str) -> Entry:
        return max((e for e in self._entries.values() if e.id == operation_id
                    and (e.id, e.version) not in self.retired), key=lambda e: e.version)

    def scoped(self, principal: str, role: str | None = None, tool_policy=frozenset()) -> list[Entry]:
        """Entries this caller may attempt; nothing outside the scope is disclosed (D275)."""
        return [e for e in self._entries.values() if (e.id, e.version) not in self.retired
                and principal in e.principals and (principal != 'agent' or role in e.roles and e.ref in tool_policy)]


def _object(properties: dict, required=(), *, closed=True) -> dict:
    return {'type': 'object', 'properties': properties, 'required': sorted(required),
            'additionalProperties': not closed}


ID = {'type': 'string', 'minLength': 1, 'maxLength': 64}
SHA = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
NUMBER = {'type': 'integer', 'minimum': 1, 'maximum': 2 ** 31}
POSITION = {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 2 ** 31}
OFFSET = {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 31}
LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 100}
KIND = {'type': 'string', 'enum': list(knowledge.KINDS)}
DOCUMENT = {'type': ['string', 'null'], 'enum': [*knowledge.DOCUMENTS, None]}
OPEN = {'type': 'object', 'additionalProperties': True}
LINK_KIND = {'type': 'string', 'enum': list(knowledge.LINK_KINDS)}
PUT = _object({'op': {'const': 'put'}, 'kind': KIND, 'code': {'type': 'string', 'minLength': 1, 'maxLength': 120},
               'document': DOCUMENT, 'content': OPEN,
               'provenance': {'type': 'string', 'enum': list(knowledge.PROVENANCES)},
               'source': {'type': ['object', 'null'], 'additionalProperties': True}, 'root_position': POSITION},
              ('op', 'kind', 'code', 'content', 'provenance'))
REMOVE = _object({'op': {'const': 'remove'}, 'item_id': ID}, ('op', 'item_id'))
LINK = _object({'op': {'const': 'link'}, 'kind': LINK_KIND, 'source_item_id': ID, 'target_item_id': ID,
                'position': POSITION, 'qualifier': {'type': ['string', 'null'], 'enum': ['full', 'partial', None]}},
               ('op', 'kind', 'source_item_id', 'target_item_id'))
UNLINK = _object({'op': {'const': 'unlink'}, 'kind': LINK_KIND, 'source_item_id': ID, 'target_item_id': ID},
                 ('op', 'kind', 'source_item_id', 'target_item_id'))
MUTATION = ('command_id', 'replayed')
_AGENTS = ('reviewer', 'executor')


def _result(*required) -> dict:
    return _object({}, required, closed=False)


CATALOGUE = Catalogue((
    Entry('knowledge.lookup', 1, 'query', ('owner', 'harness', 'agent'), _AGENTS,
          _object({'revision': NUMBER, 'item_id': ID,
                   'exposure': {'enum': ['metadata', 'excerpt', 'full']},
                   'start': OFFSET, 'length': {'type': 'integer', 'minimum': 1, 'maximum': 32768},
                   'max_bytes': {'type': 'integer', 'minimum': 1024, 'maximum': 32768}}, ('item_id',)),
          _result('revision', 'exposures', 'page'), summary='Bounded exposure of one frozen knowledge entity.'),
    Entry('knowledge.search', 1, 'query', ('owner', 'harness', 'agent'), _AGENTS,
          _object({'revision': NUMBER, 'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                   'kind': KIND, 'document': DOCUMENT, 'cursor': {'type': 'string', 'maxLength': 100},
                   'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                   'exposure': {'enum': ['metadata', 'excerpt', 'full']},
                   'max_bytes': {'type': 'integer', 'minimum': 1024, 'maximum': 32768}}, ('query',)),
          _result('revision', 'exposures', 'page'), summary='Literal casefolded search within an accepted revision.'),
    Entry('knowledge.projects', 1, 'query', ('owner',), (), _object({'offset': OFFSET, 'limit': LIMIT}),
          _result('items', 'total', 'offset', 'limit'), summary='Persisted knowledge projects and their heads.'),
    Entry('knowledge.head', 1, 'query', ('owner', 'harness', 'agent'), _AGENTS, _object({}),
          _result('knowledge_project_id', 'revision'),
          summary='The accepted head; for an agent, its frozen revision.'),
    Entry('knowledge.list', 1, 'query', ('owner', 'harness', 'agent'), _AGENTS,
          _object({'revision': NUMBER, 'kind': KIND, 'document': DOCUMENT, 'offset': OFFSET, 'limit': LIMIT}),
          _result('revision', 'items', 'total', 'offset', 'limit', 'delivery'),
          summary='Metadata of the members of one accepted revision.'),
    Entry('knowledge.get', 1, 'query', ('owner', 'harness', 'agent'), _AGENTS,
          _object({'revision': NUMBER, 'item_id': ID}, ('item_id',)), _result('revision', 'item', 'links', 'delivery'),
          summary='One member with its content and links at one accepted revision.'),
    Entry('knowledge.draft.get', 1, 'query', ('owner', 'harness', 'agent'), ('reviewer',),
          _object({'draft_id': ID}, ('draft_id',)),
          _result('draft_id', 'status', 'base_revision_id', 'draft_sha256', 'opener', 'members', 'links'),
          summary='A draft and its opener.'),
    Entry('knowledge.draft.open', 1, 'propose', ('owner', 'harness', 'agent'), ('reviewer',),
          _object({'expected_revision_id': {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 64}},
                  ('expected_revision_id',)),
          _result('knowledge_project_id', 'draft_id', 'base_revision_id', 'draft_sha256'),
          summary='Open a draft on the expected revision.'),
    Entry('knowledge.draft.apply', 1, 'propose', ('owner', 'harness', 'agent'), ('reviewer',),
          _object({'draft_id': ID, 'expected_draft_sha256': SHA,
                   'changes': {'type': 'array', 'minItems': 1, 'maxItems': 200,
                               'items': {'oneOf': [PUT, REMOVE, LINK, UNLINK]}}},
                  ('draft_id', 'expected_draft_sha256', 'changes')),
          _result('draft_id', 'draft_sha256', 'item_ids'), product='propose',
          summary="Apply typed changes to the caller's own draft."),
    Entry('knowledge.draft.discard', 1, 'propose', ('owner', 'harness', 'agent'), ('reviewer',),
          _object({'draft_id': ID}, ('draft_id',)), _result('draft_id', 'status'),
          summary='Discard a draft.'),
    Entry('knowledge.adoption.preview', 1, 'query', ('owner',), (), _object({'draft_id': ID}, ('draft_id',)),
          _result('draft_id', 'base_revision_id', 'base_revision_sha256', 'draft_sha256', 'changes',
                  'classification', 'reason_required', 'preview_sha256'),
          summary='Classified changes and the preview hash an adoption must confirm.'),
    Entry('knowledge.adopt', 1, 'adopt', ('owner', 'harness'), (),
          _object({'draft_id': ID, 'expected_revision_id': {'type': ['string', 'null'], 'minLength': 1,
                                                             'maxLength': 64},
                   'preview_sha256': SHA, 'reason': {'type': ['string', 'null'], 'maxLength': 2000}},
                  ('draft_id', 'expected_revision_id', 'preview_sha256')),
          _result('revision_id', 'number', 'revision_sha256', 'knowledge_sha256', 'origin', 'changes'),
          product='adopt', summary='Adopt a previewed draft as the next accepted revision.'),
))


# Additive entries: historical knowledge schemas/digests are untouched (D290).
CATALOGUE = Catalogue((*CATALOGUE, *(replace(CATALOGUE.current(n), version=2, roles=(*_AGENTS, 'judge'))
    for n in ('knowledge.lookup', 'knowledge.search')), *(
    Entry(f'judge.{duty}.submit', 1, 'propose', ('agent',), ('judge',),
          _object({'candidate': {'type': 'object', 'additionalProperties': True}}, ('candidate',)),
          _result('request_id', 'ruling_id', 'status', 'continuation'),
          summary=f'Submit a {duty} candidate for deterministic validation; never grants or adopts.')
    for duty in ('permission', 'planning_choice', 'spec_gap', 'blocked_check'))))

CATALOGUE = Catalogue((*CATALOGUE, Entry('judge.decision.link', 1, 'propose', ('owner',), (),
    _object({'ruling_id': ID, 'decision_id': ID, 'revision': NUMBER}, ('ruling_id', 'decision_id', 'revision')),
    _result('link_id'), summary='Link a ruling to a real canonical decision; never creates or adopts knowledge.')))


# D291: additive permission controls; historical entry digests stay unchanged.
_PERMISSION_RESPONSE = {'type': 'object', 'additionalProperties': True}
CATALOGUE = Catalogue((*CATALOGUE,
    Entry('permissions.inspect', 1, 'query', ('owner',), (), _object({}),
          _result('revision', 'items'), summary='Inspect persisted permission authority and provenance.'),
    Entry('permissions.request', 1, 'propose', ('owner', 'harness', 'agent'), _AGENTS,
          _object({'request': _PERMISSION_RESPONSE}, ('request',)),
          _result('request_id', 'replayed', 'state'), summary='Record an exact permission request; never grants authority.'),
    Entry('permissions.preview', 1, 'query', ('owner',), (),
          _object({'action': {'enum': ['grant', 'deny', 'escalate', 'revoke', 'end']},
                   'response': _PERMISSION_RESPONSE, 'expected_revision': OFFSET},
                  ('action', 'response', 'expected_revision')),
          _result('revision', 'preview_sha256', 'action', 'response'), summary='Preview an exact owner permission response.'),
    Entry('permissions.respond', 1, 'propose', ('owner',), (),
          _object({'action': {'enum': ['grant', 'deny', 'escalate', 'revoke', 'end']},
                   'response': _PERMISSION_RESPONSE, 'expected_revision': OFFSET, 'preview_sha256': SHA,
                   'confirmed': {'const': True}}, ('action', 'response', 'expected_revision', 'preview_sha256', 'confirmed')),
          _result('record_id', 'state'), summary='Confirm a fresh permission response or revoke authority.'),
))
