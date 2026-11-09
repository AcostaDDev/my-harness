"""P002-T025 matched context/catalogue workloads, offline and synthetic."""
import argparse
import json
import math
import platform
import statistics
import time

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.domain_catalogue import Entry, validate
from my_harness.core.engine.tool_bridge import TOOLS, descriptor

BROKER_INPUTS = {tool['name']: tool['inputSchema'] for tool in TOOLS}


FIXTURES = (
    (12_000, 40, 1),
    (64_000, 200, 2),
    (256_000, 1_000, 3),
)
TASKS = (
    ('stock', 'Inventory threshold', 'umbral', 12, 'boxes', 7),
    ('retry', 'Retry interval', 'reintento', 250, 'ms', 9),
    ('window', 'Delivery window', 'horario', 4, 'hours', 11),
)
# Golden answers include the stable identity, exact revision, value and unit.
EXPECTED = [
    {'id': 'stock', 'revision': 7, 'value': 12, 'unit': 'boxes'},
    {'id': 'retry', 'revision': 9, 'value': 250, 'unit': 'ms'},
    {'id': 'window', 'revision': 11, 'value': 4, 'unit': 'hours'},
]


def tool(name, topic):
    inputs = {'type': 'object', 'additionalProperties': False, 'required': ['id'],
              'properties': {'id': {'type': 'string', 'const': name}}}
    output = {'type': 'object', 'required': ['id', 'revision', 'value', 'unit'],
              'description': 'Returns immutable evidence with a verified revision. ' * 12}
    return Entry(name, 1, 'query', ('agent',), ('reviewer',), inputs, output,
                 summary=f'Bounded query for {topic}.')


def fixture(context_size, catalogue_size, selected):
    records = {name: {'id': name, 'revision': revision, 'value': value, 'unit': unit}
               for name, _, _, value, unit, revision in TASKS}
    entries = [tool(name, topic) for name, topic, *_ in TASKS]
    entries += [tool(f'unused-{i:04d}', f'fixture topic {i:04d}') for i in range(catalogue_size - len(entries))]
    # Put distractors first, so the selected descriptors are not an initial slice of the catalogue.
    entries.reverse()
    note = '%04d Nota sintética · observación de archivo sin efecto.\n'
    lines = context_size // len((note % 0).encode('utf-8'))
    task = [{'id': name, 'topic': topic, 'label': label} for name, topic, label, *_ in TASKS[:selected]]
    return task, records, entries, ''.join(note % i for i in range(lines))


class ExchangeLog:
    def __init__(self):
        self.counts = {}

    def send(self, stage, direction, payload):
        wire = freeze(payload).encode('utf-8')
        cell = self.counts.setdefault(stage, {'out_bytes': 0, 'in_bytes': 0, 'exchanges': 0})
        cell[f'{direction}_bytes'] += len(wire)
        return json.loads(wire)

    def call(self, stage, method, arguments, handler):
        request = self.send(stage, 'out', {'method': method, 'arguments': arguments})
        self.counts[stage]['exchanges'] += 1
        validate(BROKER_INPUTS[method], request['arguments'])
        return self.send(stage, 'in', handler(request['arguments']))['result']


def run(data, on_demand):
    task, records, entries, background = data
    wire = ExchangeLog()
    prompt = {'request': 'Return each requested value, unit and evidence revision.', 'criteria': task}
    if on_demand:
        shown = wire.send('initial', 'out', {'prompt': prompt, 'catalogue': TOOLS})
    else:
        shown = wire.send('initial', 'out', {'prompt': {**prompt, 'background': background, 'records': records},
                                             'catalogue': [entry.document() for entry in entries]})
    available = {entry['id']: entry for entry in shown['catalogue']} if not on_demand else {}

    def search(arguments):
        query = arguments['query'].casefold()
        matches = [entry for entry in entries if query in (entry.id + ' ' + entry.summary).casefold()]
        selected = matches[:arguments['limit']]
        # Fixture queries fit in one page.
        assert len(selected) == len(matches)
        return {'ok': True, 'result': {'items': [descriptor(entry) for entry in selected],
                                      'page': {'truncated': False, 'total': len(matches), 'next_cursor': None}}}

    def describe(arguments):
        entry = next(entry for entry in entries if (entry.id, entry.version) == (arguments['id'], arguments['version']))
        return {'ok': True, 'result': {**entry.document(), 'schema_sha256': entry.schema_sha256}}

    def retrieve(arguments):
        ref = (arguments['id'], arguments['version'], arguments['schema_sha256'])
        entry = next(entry for entry in entries if entry.ref == ref)
        validate(entry.input, arguments['arguments'])
        return {'ok': True, 'operation': entry.id, 'replayed': False, 'result': records[entry.id]}

    answer = []
    for criterion in shown['prompt']['criteria']:
        ident = criterion['id']
        arguments = {'id': ident}
        if on_demand:
            found = wire.call('search', 'search_tools',
                              {'query': criterion['topic'], 'limit': 5, 'key': f'search-{ident}'}, search)
            match = next(item for item in found['items'] if item['id'] == ident)
            ref = {'id': match['id'], 'version': match['version']}
            definition = wire.call('describe', 'describe_tool', {**ref, 'key': f'describe-{ident}'}, describe)
            validate(definition['input'], arguments)
            assert definition['schema_sha256'] == match['schema_sha256']
            value = wire.call('retrieve', 'invoke_tool', {**ref, 'schema_sha256': definition['schema_sha256'],
                              'arguments': arguments, 'key': f'retrieve-{ident}'}, retrieve)
        else:
            validate(available[ident]['input'], arguments)
            value = shown['prompt']['records'][ident]
        answer.append(value)
    result = wire.send('completion', 'in', answer)
    return wire.counts, result


def measure(data, on_demand, repeats):
    run(data, on_demand)  # warm both parser and serializer before recording
    durations = []
    selected = len(data[0])
    completed = 0
    for _ in range(repeats):
        start = time.perf_counter_ns()
        stages, result = run(data, on_demand)
        durations.append((time.perf_counter_ns() - start) / 1_000_000)
        completed += result == EXPECTED[:selected]
    if completed != repeats:
        raise AssertionError(f'completed {completed}/{repeats} simulated tasks')
    return {'stages': stages, 'total_bytes': sum(row['out_bytes'] + row['in_bytes'] for row in stages.values()),
            'tool_exchanges': sum(row['exchanges'] for row in stages.values()),
            'completed': completed, 'median_ms': round(statistics.median(durations), 3),
            'p95_ms': round(sorted(durations)[math.ceil(repeats * .95) - 1], 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=30)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    results = []
    for context_size, catalogue_size, selected in FIXTURES:
        data = fixture(context_size, catalogue_size, selected)
        results.append({'background_bytes': len(data[3].encode('utf-8')), 'catalogue_entries': catalogue_size,
                        'required_records': selected, 'full': measure(data, False, args.repeats),
                        'on_demand': measure(data, True, args.repeats)})
    print(json.dumps({'format': 'synthetic-context-efficiency-1', 'python': platform.python_version(),
                      'platform': platform.platform(), 'repeats': args.repeats, 'fixtures': results},
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
