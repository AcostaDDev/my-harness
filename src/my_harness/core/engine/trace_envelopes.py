"""P002-T006 (D277, FL08, FL09): bounded event envelopes that T007 and T008 will emit. Validation only, no I/O.

`knowledge-delivery-1` records one delivery of project knowledge to an invocation: channel, entity, stable ID,
revision, sections, exposure, digest, truncation/pagination and failure. Delivery shows availability, never
comprehension, so the schema is closed and has no field for use or understanding. `tool-discovery-1` records a
catalogue search or a schema description, separately from knowledge reads and from tool invocation (which is a
domain command with its own outcome). Queries are kept as digests and lengths, never as text. Correlation (thread,
operation, event order) belongs to the event that carries the envelope, not to the envelope.
"""
import re

KNOWLEDGE_DELIVERY = 'knowledge-delivery-1'
TOOL_DISCOVERY = 'tool-discovery-1'
CHANNELS = ('initial_context', 'query_result', 'tool_result')
ENTITY_TYPES = ('requirement', 'criterion', 'phase', 'task', 'decision', 'section')  # D284 kinds
EXPOSURES = ('metadata', 'excerpt', 'full')
DELIVERY_FAILURES = ('entity_missing', 'revision_unavailable', 'over_limit', 'receipt_unrecorded')
DISCOVERY_ACTIONS = ('search', 'describe')
DESCRIBE_OUTCOMES = ('delivered', 'unknown', 'retired', 'out_of_scope')
MAX_SECTIONS = 50
MAX_DESCRIPTORS = 50
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}')
_SHA256 = re.compile(r'[0-9a-f]{64}')


class EnvelopeError(ValueError):
    def __init__(self, code: str, where: str):
        super().__init__(f'{code} at {where}')
        self.code, self.where = code, where


def _closed(value, where, required, optional=()):
    if not isinstance(value, dict):
        raise EnvelopeError('not_object', where)
    extra = set(value) - set(required) - set(optional)
    if extra:
        raise EnvelopeError('unknown_field', f'{where}.{sorted(extra)[0]}')
    missing = set(required) - set(value)
    if missing:
        raise EnvelopeError('missing_field', f'{where}.{sorted(missing)[0]}')


def _identifier(value, where, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EnvelopeError('invalid_identifier', where)


def _sha256(value, where):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise EnvelopeError('invalid_digest', where)


def _choice(value, choices, where, *, nullable=False):
    if value is None and nullable:
        return
    if value not in choices:
        raise EnvelopeError('invalid_value', where)


def _count(value, where, *, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not int or value < 0:
        raise EnvelopeError('invalid_count', where)


def _page(value, where):
    _closed(value, where, ('truncated',), ('page', 'next_cursor', 'total'))
    if type(value['truncated']) is not bool:
        raise EnvelopeError('invalid_value', f'{where}.truncated')
    _count(value.get('page'), f'{where}.page', nullable=True)
    _count(value.get('total'), f'{where}.total', nullable=True)
    _identifier(value.get('next_cursor'), f'{where}.next_cursor', nullable=True)


def knowledge_delivery(value) -> dict:
    """Validates a `knowledge-delivery-1` envelope and returns it unchanged."""
    _closed(value, '$', ('format', 'invocation_id', 'channel', 'entity_type', 'stable_id', 'revision_id',
                         'exposure', 'page', 'failure'), ('sections', 'digest'))
    if value['format'] != KNOWLEDGE_DELIVERY:
        raise EnvelopeError('invalid_value', '$.format')
    _identifier(value['invocation_id'], '$.invocation_id')
    _choice(value['channel'], CHANNELS, '$.channel')
    _choice(value['entity_type'], ENTITY_TYPES, '$.entity_type')
    _identifier(value['stable_id'], '$.stable_id')
    _identifier(value['revision_id'], '$.revision_id')
    _choice(value['exposure'], EXPOSURES, '$.exposure')
    _choice(value['failure'], DELIVERY_FAILURES, '$.failure', nullable=True)
    sections = value.get('sections', [])
    if not isinstance(sections, list) or len(sections) > MAX_SECTIONS:
        raise EnvelopeError('invalid_sections', '$.sections')
    for index, section in enumerate(sections):
        _identifier(section, f'$.sections[{index}]')
    _page(value['page'], '$.page')
    if value['failure'] is None:
        # Delivered content is bound to its exact bytes; a failed delivery delivered nothing to digest.
        _sha256(value.get('digest'), '$.digest')
    elif 'digest' in value:
        raise EnvelopeError('digest_without_delivery', '$.digest')
    return value


def tool_discovery(value) -> dict:
    """Validates a `tool-discovery-1` envelope (search results or one schema description)."""
    common = ('format', 'invocation_id', 'action', 'catalogue_sha256')
    if not isinstance(value, dict):
        raise EnvelopeError('not_object', '$')
    if value.get('action') == 'search':
        _closed(value, '$', (*common, 'query_sha256', 'query_length', 'results', 'page'))
        _sha256(value['query_sha256'], '$.query_sha256')
        _count(value['query_length'], '$.query_length')
        results = value['results']
        if not isinstance(results, list) or len(results) > MAX_DESCRIPTORS:
            raise EnvelopeError('invalid_results', '$.results')
        for index, item in enumerate(results):
            where = f'$.results[{index}]'
            _closed(item, where, ('id', 'version', 'schema_sha256'))
            _identifier(item['id'], f'{where}.id')
            _count(item['version'], f'{where}.version')
            _sha256(item['schema_sha256'], f'{where}.schema_sha256')
        _page(value['page'], '$.page')
    elif value.get('action') == 'describe':
        _closed(value, '$', (*common, 'id', 'version', 'outcome'), ('schema_sha256',))
        _identifier(value['id'], '$.id')
        _count(value['version'], '$.version')
        _choice(value['outcome'], DESCRIBE_OUTCOMES, '$.outcome')
        if value['outcome'] == 'delivered':
            _sha256(value.get('schema_sha256'), '$.schema_sha256')
        elif 'schema_sha256' in value:
            raise EnvelopeError('digest_without_delivery', '$.schema_sha256')
    else:
        raise EnvelopeError('invalid_value', '$.action')
    if value['format'] != TOOL_DISCOVERY:
        raise EnvelopeError('invalid_value', '$.format')
    _identifier(value['invocation_id'], '$.invocation_id')
    _sha256(value['catalogue_sha256'], '$.catalogue_sha256')
    return value
