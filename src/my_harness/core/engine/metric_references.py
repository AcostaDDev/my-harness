"""Immutable, offline metrics-reference-1 documents (D255).

Only load_packaged_bundle performs I/O. Loading/importing validates bytes; selection never
refreshes a source. A reference ID is its canonical content digest, not a mutable model name.
The small declarative rate-case language cannot execute expressions or infer conditions.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from importlib.resources import files
import json
import re

FORMAT = 'metrics-reference-1'
CATEGORIES = ('uncached_input', 'cache_read', 'write_5m', 'write_1h', 'write_30m', 'write_12h', 'output')
SEMANTICS = ('claude-cli-1', 'codex-cli-1', 'responses-api-1')
DECIMAL = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class ReferenceError(ValueError):
    def __init__(self, reason, detail):
        super().__init__(f'{reason}: {detail}')
        self.reason = reason


def canonical(value):
    """Canonical UTF-8 JSON; decimal values must be strings, floats are forbidden."""
    def check(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ReferenceError('reference_conflict', 'non-string key')
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif item is not None and type(item) not in (str, int, bool):
            raise ReferenceError('reference_conflict', 'non-JSON or floating-point value')
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return sha256(canonical(value)).hexdigest()


def decimal_value(value, *, factor=False):
    limit, places, reason = (1000, 6, 'unsupported_modifier') if factor else (10**9, 12, 'invalid_rate')
    if (type(value) is not str or len(value) > 32 or not DECIMAL.fullmatch(value)
            or len(value.partition('.')[2]) > places):
        raise ReferenceError(reason, 'invalid decimal string')
    result = Decimal(value)
    if result > limit or (factor and result <= 0):
        raise ReferenceError(reason, 'decimal outside bounds')
    return result


def timestamp(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z', value):
        raise ReferenceError('reference_conflict', 'UTC timestamp required')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ReferenceError('reference_conflict', 'invalid timestamp') from exc


def _require(condition, detail, reason='reference_conflict'):
    if not condition:
        raise ReferenceError(reason, detail)


def _keys(value, required, optional=()):
    _require(type(value) is dict and set(required) <= value.keys()
             and value.keys() <= set(required) | set(optional), 'invalid object fields')


def _text(value):
    return type(value) is str and bool(value.strip())


def _sorted_unique(rows, key):
    _require(type(rows) is list and all(type(row) is dict and key in row for row in rows), 'invalid keyed array')
    keys = [row[key] for row in rows]
    _require(all(_text(k) for k in keys) and keys == sorted(set(keys)), f'array must be ordered/unique by {key}')


def _power_of_ten(value):
    return type(value) is int and 1 <= value <= 10**12 and re.fullmatch(r'10*', str(value)) is not None


def _validate(document):
    common = ('format', 'kind', 'provider', 'platform', 'product', 'model', 'sources', 'observed_at',
              'effective_from', 'effective_to', 'effective_period_unknown')
    kind = document.get('kind') if type(document) is dict else None
    specific = (('canonical_model', 'identity_rule') if kind == 'model_identity' else
                ('scheme', 'unit', 'bases', 'quantity_basis', 'semantics', 'required_conditions', 'cases', 'exclusions'))
    _keys(document, common + specific, ('supersedes',))
    _require(document['format'] == FORMAT and kind in ('model_identity', 'tariff'), 'unknown reference format/kind')
    _require(all(_text(document[k]) for k in ('provider', 'platform', 'product', 'model')), 'missing identity')
    timestamp(document['observed_at'])
    start, end = document['effective_from'], document['effective_to']
    _require(type(document['effective_period_unknown']) is bool, 'unknown-period flag required')
    if start is not None:
        timestamp(start)
    if end is not None:
        timestamp(end)
    _require(start is None or end is None or timestamp(start) < timestamp(end), 'empty effective interval')
    _require(document['effective_period_unknown'] or start is not None or end is not None, 'unbounded known interval')
    if 'supersedes' in document:
        _require(type(document['supersedes']) is str and DIGEST.fullmatch(document['supersedes']), 'bad supersedes digest')
    sources = document['sources']
    _sorted_unique(sources, 'url')
    _require(bool(sources), 'source required')
    for source in sources:
        _keys(source, ('url', 'locale', 'evidence_digest'))
        _require(source['url'].startswith('https://') and _text(source['locale'])
                 and type(source['evidence_digest']) is str and DIGEST.fullmatch(source['evidence_digest']), 'bad source')
    if kind == 'model_identity':
        _require(_text(document['canonical_model']) and document['identity_rule'] in ('exact', 'alias'), 'invalid identity rule')
        _require(document['identity_rule'] != 'exact' or document['model'] == document['canonical_model'], 'inexact exact ID')
        return
    _require(all(_text(document[k]) for k in ('scheme', 'unit')), 'missing scheme/unit')
    _require(type(document['bases']) is list and bool(document['bases'])
             and all(_text(k) for k in document['bases']) and document['bases'] == sorted(set(document['bases']))
             and set(document['bases']) <= {'api_usd', 'enterprise_usd', 'token_credit', 'subscription_equivalent'}, 'bad bases')
    _require(not (set(document['bases']) & {'api_usd', 'enterprise_usd'}) or document['unit'] == 'USD', 'USD basis requires USD unit')
    _require('token_credit' not in document['bases'] or document['unit'] != 'USD', 'credit basis requires a named credit unit')
    _require(document['quantity_basis'] in ('disjoint_tokens', 'charged_tool'), 'unsupported quantity basis')
    _require(type(document['semantics']) is list and document['semantics'] == sorted(set(document['semantics']))
             and set(document['semantics']) <= set(SEMANTICS), 'unsupported semantics')
    _require(document['quantity_basis'] != 'disjoint_tokens' or bool(document['semantics']), 'missing semantics')
    required = document['required_conditions']
    _require(type(required) is list and all(_text(k) for k in required) and required == sorted(set(required)), 'bad conditions')
    _require(type(document['exclusions']) is list and all(_text(k) for k in document['exclusions'])
             and document['exclusions'] == sorted(set(document['exclusions'])), 'bad exclusions')
    _sorted_unique(document['cases'], 'key')
    _require(bool(document['cases']), 'missing rate cases')
    seen = []
    for case in document['cases']:
        _keys(case, ('key', 'conditions', 'prompt_from', 'prompt_to', 'rates', 'factors', 'included_adjustments'))
        _require(type(case['conditions']) is dict and set(case['conditions']) == set(required)
                 and all(_text(v) for v in case['conditions'].values()), 'incomplete case conditions')
        low, high = case['prompt_from'], case['prompt_to']
        _require(type(low) is int and 0 <= low <= 2**63-1
                 and (high is None or type(high) is int and low <= high <= 2**63-1), 'invalid request tier')
        for other in seen:
            overlaps = max(low, other['prompt_from']) <= min(high if high is not None else 2**63-1,
                                                            other['prompt_to'] if other['prompt_to'] is not None else 2**63-1)
            _require(case['conditions'] != other['conditions'] or not overlaps, 'ambiguous overlapping rate cases')
        seen.append(case)
        rates = case['rates']
        _require(type(rates) is dict and bool(rates), 'missing rates')
        if document['quantity_basis'] == 'disjoint_tokens':
            _require(set(rates) <= set(CATEGORIES), 'unsupported token category')
        for rate in rates.values():
            _keys(rate, ('amount', 'quantity', 'unit'))
            if rate['amount'] is not None:
                decimal_value(rate['amount'])
            _require(_power_of_ten(rate['quantity']) and _text(rate['unit']), 'invalid rate denominator/unit', 'invalid_rate')
            if document['quantity_basis'] == 'disjoint_tokens':
                _require(rate['quantity'] == 1000000 and rate['unit'] == 'token', 'invalid token rate basis', 'invalid_rate')
        _require(type(case['included_adjustments']) is list and all(_text(k) for k in case['included_adjustments'])
                 and case['included_adjustments'] == sorted(set(case['included_adjustments'])), 'bad included adjustments')
        _sorted_unique(case['factors'], 'key')
        counts = dict.fromkeys(rates, 0)
        for factor in case['factors']:
            _keys(factor, ('key', 'value', 'categories', 'source'))
            decimal_value(factor['value'], factor=True)
            _require(_text(factor['source']) and type(factor['categories']) is list and bool(factor['categories'])
                     and all(_text(k) for k in factor['categories'])
                     and factor['categories'] == sorted(set(factor['categories']))
                     and set(factor['categories']) <= rates.keys(), 'invalid factor categories', 'unsupported_modifier')
            _require(factor['key'] not in case['included_adjustments'], 'adjustment already included', 'unsupported_modifier')
            for category in factor['categories']:
                counts[category] += 1
        _require(all(n <= 8 for n in counts.values()), 'too many factors', 'unsupported_modifier')


@dataclass(frozen=True)
class Reference:
    id: str
    content: bytes

    def document(self):
        """A fresh copy, so callers cannot mutate the pinned reference."""
        return json.loads(self.content)


def seal_reference(document):
    try:
        _validate(document)
        content = canonical(document)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ReferenceError('reference_conflict', 'malformed reference document') from exc
    return Reference(sha256(content).hexdigest(), content)


@dataclass(frozen=True)
class ReferenceBundle:
    references: tuple[Reference, ...]

    @property
    def id(self):
        return digest(self.envelope())

    def envelope(self):
        return {'format': FORMAT, 'references': [{'id': r.id, 'document': r.document()} for r in self.references]}

    def get(self, identifier):
        return next((r for r in self.references if r.id == identifier), None)


def make_bundle(references):
    """Validate pinned references, including objects supplied directly by Python callers."""
    checked = []
    for ref in references:
        _require(type(ref) is Reference and type(ref.content) is bytes, 'invalid reference object')
        actual = seal_reference(_loads(ref.content))
        _require(actual == ref, 'reference digest/content mismatch')
        checked.append(actual)
    _require(len({r.id for r in checked}) == len(checked), 'duplicate reference ID')
    # Exact same logical selection may have several versions only when periods are disjoint.
    for index, ref in enumerate(checked):
        a = ref.document()
        for other in checked[:index]:
            b = other.document()
            identity = ('kind', 'provider', 'platform', 'product', 'model', 'scheme', 'unit')
            if any(a.get(k) != b.get(k) for k in identity):
                continue
            separated = (a['effective_to'] is not None and b['effective_from'] is not None
                         and timestamp(a['effective_to']) <= timestamp(b['effective_from'])) or (
                         b['effective_to'] is not None and a['effective_from'] is not None
                         and timestamp(b['effective_to']) <= timestamp(a['effective_from']))
            _require(separated and not a['effective_period_unknown'] and not b['effective_period_unknown'],
                     'ambiguous reference versions; use separate pinned bundles')
    return ReferenceBundle(tuple(sorted(checked, key=lambda r: r.id)))


def _loads(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    def reject(value):
        raise ReferenceError('reference_conflict', f'non-integer JSON number: {value}')

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, ReferenceError):
            raise
        raise ReferenceError('reference_conflict', 'invalid JSON bytes') from exc


def load_bundle(raw):
    envelope = _loads(raw)
    _keys(envelope, ('format', 'references'))
    _require(envelope['format'] == FORMAT, 'unknown bundle format')
    _sorted_unique(envelope['references'], 'id')
    references = []
    for entry in envelope['references']:
        _keys(entry, ('id', 'document'))
        ref = seal_reference(entry['document'])
        _require(ref.id == entry['id'], 'reference digest mismatch')
        references.append(ref)
    return make_bundle(references)


def load_packaged_bundle():
    return load_bundle(files(__package__).joinpath('references', 'metrics-2026-10-27-v1.json').read_bytes())
