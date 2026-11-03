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



def phase_plan_schema():
    """Closed native contract for the structured planning template only."""
    task_fields = {key: {'type': 'string', 'minLength': int(required), 'maxLength': knowledge.MAX_TEXT}
                   for key, (required, _) in knowledge.FIELDS['task'].items()}
    task_fields.update(status={'enum': list(knowledge.STATUSES['task'])},
                       subtasks={'type': 'array', 'items': {'type': 'string', 'minLength': 1}})
    source_fields = {key: {'type': 'string', 'minLength': 1}
                     for key in ('path', 'heading', 'reference')}
    source_fields.update(kind={'type': 'string', 'enum': list(knowledge.SOURCE_KINDS)},
                         sha256={'type': 'string', 'pattern': '^[0-9a-f]{64}$'})
    source = _object(source_fields, ('kind',))
    task_item = _object({**PUT['properties'], 'kind': {'type': 'string', 'const': 'task'},
                         'content': _object(task_fields, task_fields),
                         'source': source},
                        (*PUT['required'], 'source'))
    criterion_item = _object({**PUT['properties'], 'kind': {'type': 'string', 'const': 'criterion'},
                              'content': _object({'statement': {'type': 'string', 'minLength': 1},
                                                  'status': {'enum': list(knowledge.STATUSES['criterion'])}},
                                                 ('statement', 'status')),
                              'source': source},
                             (*PUT['required'], 'source'))
    knowledge_schema = _object({**SCHEMA['properties'], 'items': {
        **SCHEMA['properties']['items'], 'items': {'oneOf': [task_item, criterion_item]}}}, ('items', 'links'))
    fields = {
        'answer': {'type': 'string', 'minLength': 1},
        'questions': {'type': 'array', 'items': _object({
            'text': {'type': 'string', 'minLength': 1}, 'blocking': {'type': 'boolean'}}, ('text', 'blocking'))},
        'pending': {'type': 'array', 'maxItems': MAX_PENDING, 'items': {'type': 'string', 'minLength': 1}},
        'plan': {'type': 'null'},
        'knowledge': knowledge_schema,
        'coverage': {'type': 'object', 'additionalProperties': {
            'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'minLength': 1}}},
    }
    return _object(fields, fields)


def validate_phase_plan(data):
    schema = phase_plan_schema()
    validate(schema, data)
    coverage = data['coverage']
    for tasks in coverage.values():
        validate(schema['properties']['coverage']['additionalProperties'], tasks)
    return {**validate_result({key: data[key] for key in ('answer', 'questions', 'pending', 'knowledge')}),
            'coverage': coverage}
