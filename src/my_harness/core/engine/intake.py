"""Structured intake response contract; no authority is derived from model output."""
from my_harness.core.engine import knowledge
from my_harness.core.engine.contracts import ContractError
from my_harness.core.engine.domain_catalogue import PUT, _object, validate, SchemaError
from my_harness.core.engine.definition import _questions, _text, _texts, MAX_PENDING
from my_harness.i18n import tr

LINK = _object({'kind': {'enum': list(knowledge.LINK_KINDS)},
                'source': {'type': 'string'}, 'target': {'type': 'string'},
                'position': {'type': ['integer', 'null'], 'minimum': 0},
                'qualifier': {'enum': ['full', 'partial', None]}}, ('kind', 'source', 'target'))
SCHEMA = _object({'items': {'type': 'array', 'maxItems': 200, 'items': PUT},
                  'links': {'type': 'array', 'maxItems': 400, 'items': LINK}}, ('items', 'links'))


def validate_result(data):
    required = {'answer', 'questions', 'knowledge', 'pending'}
    if (not isinstance(data, dict) or not required <= set(data)
            or set(data) - required - {'profile'}):
        raise ContractError(tr('intake.invalid'))
    try:
        validate(SCHEMA, data['knowledge'])
        seen = set()
        for item in data['knowledge']['items']:
            knowledge.validate_item(item['kind'], item['code'], item.get('document'))
            knowledge.validate_content(item['kind'], item.get('document'), item['content'])
            knowledge.validate_source(item['provenance'], item.get('source'))
            key = (item['kind'], item.get('document'), item['code'])
            if key in seen or not item.get('source'):
                raise ContractError(tr('intake.invalid'))
            seen.add(key)
    except SchemaError as exc:
        raise ContractError(tr('intake.invalid')) from exc
    return {'answer': _text(data['answer'], 'answer'), 'questions': _questions(data['questions']),
            'knowledge': data['knowledge'], 'pending': _texts(data['pending'], 'pending', limit=MAX_PENDING), 'drafts': []}
