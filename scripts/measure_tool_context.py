"""T008 reproducible synthetic catalogue serialization. Offline; no provider, tokens or inference."""
import json

from my_harness.core.engine.domain_catalogue import CATALOGUE, Entry
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.tool_bridge import measure


def measurements():
    def row(entries, selected):
        return {**measure(entries, selected), 'loaded_schema_count': len(selected),
                'describe_responses_bytes': len(freeze([
                    {**e.document(), 'schema_sha256': e.schema_sha256} for e in selected]).encode('utf-8')),
                'exchanges_loading_all_selected_then_one_invoke': len(selected) + 2}
    rows = []
    for count in (40, 200, 1000):
        entries = [Entry(f'synthetic.tool.{i:04}', 1, 'query', ('agent',), ('reviewer',),
                         {'type': 'object', 'additionalProperties': False, 'properties': {
                             'query': {'type': 'string', 'maxLength': 200,
                                       'description': 'Synthetic bounded search field. ' * 20},
                             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}},
                         {'type': 'object', 'additionalProperties': True},
                         summary='Synthetic project-scoped knowledge query. ' * 5) for i in range(count)]
        rows.append(row(entries, entries[:5]))
    return {'format': 'tool-context-measurement-1', 'synthetic': rows,
            'product_catalogue': row(list(CATALOGUE), [CATALOGUE.current(n) for n in
                                                          ('knowledge.lookup', 'knowledge.search')])}


if __name__ == '__main__':
    print(json.dumps(measurements(), indent=2, sort_keys=True))
