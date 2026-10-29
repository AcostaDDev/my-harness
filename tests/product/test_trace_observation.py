"""P002-T006 independent work: `trace-observation-1`, bounded trace payloads and the T007/T008 envelopes.

Fake CLIs (`cli_process_probe.py`) through the real adapter and supervisor journal on temporary SQLite; no
installed agent, provider or network. Threats: TM14 (counters, sources, missing telemetry), TM15 (bounds), TM17
(sensitive content), TM12 support (cancellation classified from the supervisor record).
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
import signal
import sys

import pytest

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.adapters.streams import AgentStream
from my_harness.core.engine import observation, trace_envelopes as envelopes, trace_payload
from my_harness.core.engine.metrics import attempt_metrics
from test_cli_agents import PROBE, setup_invocation, wait_until
from test_managed import context, repository  # noqa: F401  (fixtures)


def probe_adapter(tmp_path, mode, *, usage=False, timeout=5):
    env = (('PROBE_EXPLICIT', 'selected'), ('PROBE_RECORD', str(tmp_path / 'launches.jsonl')),
           ('PROBE_CHILD', str(tmp_path / 'child.pid')), *((('PROBE_USAGE', '1'),) if usage else ()))
    configs = [CLIConfig(provider, (sys.executable, PROBE, provider, mode), version, env, timeout)
               for provider, version in (('codex', '0.163.0'), ('claude', '2.1.304'))]
    return CLIProcessAdapter(configs, tmp_path / 'captures')


def settled(repository, job):
    [process] = repository.processes(job.id)
    return process


def observe(process, **numbers):
    return observation.observe(spec=process['spec'], process_status=process['status'], capture=process['capture'],
                               identity_present=process['identity'] is not None, **numbers)


def run(tmp_path, repository, context, mode, role, *, usage=False):
    port = probe_adapter(tmp_path, mode, usage=usage)
    job, claim, request = setup_invocation(repository, context, port, role)
    port.invoke(context, request)
    repository.close_owner(claim)
    return settled(repository, job)


# --- trace-observation-1 --------------------------------------------------------------------------------------------

def test_claude_complete_counters_keep_their_meanings_and_sources(tmp_path, context, repository):
    process = run(tmp_path, repository, context, 'success', 'executor', usage=True)
    result = observe(process, attempt_number=1, revision_round=0)
    counters = result['counters']
    assert result['format'] == 'trace-observation-1' and result['provider'] == 'claude'
    assert result['launch'] == 'observed'
    assert result['termination']['class'] == 'completed' and result['termination']['writer'] == 'stopped'
    assert counters['harness_attempt'] == {'meaning': observation.MEANINGS['harness_attempt'], 'value': 1,
                                           'source': 'supplied', 'coverage': 'complete'}
    assert counters['revision_round']['value'] == 0 and counters['revision_round']['source'] == 'derived'
    # Two model requests inside one invocation are two native turns, not two attempts or rounds.
    assert counters['native_turns']['value'] == 2 and counters['native_turns']['source'] == 'reported'
    assert counters['tool_calls']['value'] == 1 and counters['tool_calls']['by_name'] == {'Read': 1}
    assert counters['tool_calls']['source'] == 'measured' and counters['tool_calls']['coverage'] == 'complete'
    assert counters['permission_denials']['value'] == 0 and counters['permission_denials']['source'] == 'reported'
    # Terminal total and per-message usage are alternative views; neither is added to the other.
    assert result['usage'] == {'view': 'terminal', 'source': 'reported', 'coverage': 'complete',
                               'alternatives': ['messages']}
    assert result['reported_model'] == {'value': ['claude-synthetic-a', 'claude-synthetic-b'], 'source': 'reported'}
    assert result['missing'] == []


def test_codex_complete_measures_one_turn_and_leaves_model_and_denials_absent(tmp_path, context, repository):
    process = run(tmp_path, repository, context, 'success', 'planner', usage=True)
    result = observe(process, attempt_number=1, revision_round=0)
    counters = result['counters']
    assert result['provider'] == 'codex' and result['termination']['class'] == 'completed'
    assert counters['native_turns'] == {'meaning': observation.MEANINGS['native_turns'], 'value': 1,
                                        'source': 'measured', 'coverage': 'complete'}
    assert counters['tool_calls']['by_name'] == {'command_execution': 1, 'file_change': 1}
    assert result['usage']['view'] == 'terminal'
    assert counters['permission_denials']['value'] is None
    assert counters['permission_denials']['reason'] == 'not_reported_by_client'
    assert result['reported_model'] == {'value': None, 'source': 'absent', 'reason': 'not_reported_by_client'}
    assert {item['signal'] for item in result['missing']} == {'permission_denials', 'reported_model'}
    # metrics-1 keeps its historical item-derived "turns"; trace-observation-1 does not reuse it.
    metrics = attempt_metrics(request={'role': 'planner', 'selection': {}},
                              result={'metadata_json': json.dumps(process['capture'])}, status='COMPLETED',
                              spec=process['spec'], executor_round=0)
    assert metrics['turns'] == 3 and metrics['provenance']['turns'] == 'derived'


def test_supervisor_cancellation_with_exit_zero_is_cancelled_and_its_signals_absent(tmp_path, context, repository):
    port = probe_adapter(tmp_path, 'term_exit0')
    job, claim, request = setup_invocation(repository, context, port, 'planner')
    with ThreadPoolExecutor() as pool:
        future = pool.submit(port.invoke, context, request)
        wait_until(lambda: any(e['kind'] == 'agent_event' and e['payload'].get('original', {}).get('type')
                               == 'item.started' for e in repository.events(job.run_id)))
        assert port.cancel(request.id).requested
        assert future.result(timeout=5).status == 'cancelled'
    repository.close_owner(claim)
    process = settled(repository, job)
    assert process['capture']['exit_code'] == 0  # the client reported success on SIGTERM (D281)
    result = observe(process, attempt_number=1, revision_round=0)
    assert result['termination'] == {'writer': 'stopped', 'exit_code': 0, 'class': 'cancelled',
                                     'source': 'supervisor'}
    assert result['counters']['native_turns']['value'] is None
    assert result['counters']['native_turns']['reason'] == 'no_terminal'
    assert result['counters']['tool_calls']['coverage'] == 'partial'
    assert result['usage']['view'] is None and result['usage']['reason'] == 'no_terminal'
    assert {item['signal'] for item in result['missing']} >= {'native_turns', 'usage', 'reported_model'}


def test_external_termination_with_exit_zero_is_not_classified_as_cancellation(tmp_path, context, repository):
    port = probe_adapter(tmp_path, 'term_exit0')
    job, claim, request = setup_invocation(repository, context, port, 'planner')
    with ThreadPoolExecutor() as pool:
        future = pool.submit(port.invoke, context, request)
        wait_until(lambda: any(e['kind'] == 'process_spawned' for e in repository.events(job.run_id)))
        wait_until(lambda: any(e['kind'] == 'agent_event' for e in repository.events(job.run_id)))
        pgid = next(e['payload']['pgid'] for e in repository.events(job.run_id) if e['kind'] == 'process_spawned')
        os.killpg(pgid, signal.SIGTERM)  # someone else stops the client; the supervisor never asked
        future.result(timeout=5)
    repository.close_owner(claim)
    result = observe(settled(repository, job))
    assert result['termination']['exit_code'] == 0
    assert result['termination']['class'] == 'partial' and result['termination']['source'] == 'measured'


def test_closing_owner_interruption_and_missing_evidence_stay_unknown():
    spec = {'provider': 'claude'}
    interrupted = observation.observe(spec=spec, process_status='UNCERTAIN', identity_present=True,
                                      capture={'status': 'interrupted', 'group_state': 'unknown',
                                               'settled_by': 'closing_owner'})
    assert interrupted['termination'] == {'writer': 'uncertain', 'exit_code': None, 'class': 'interrupted',
                                          'source': 'supervisor'}
    assert interrupted['launch'] == 'observed'
    pending = observation.observe(spec=spec, process_status='PENDING', capture=None)
    assert pending['launch'] == 'pending' and pending['termination']['class'] == 'pending'
    nothing = observation.observe(spec=None, process_status=None, capture=None)
    assert nothing['launch'] == 'unknown_execution' and nothing['termination']['class'] == 'unknown'
    assert nothing['counters']['harness_attempt']['reason'] == 'not_a_managed_attempt'
    for counter in nothing['counters'].values():
        assert counter['value'] is None and counter['source'] == 'absent'  # never zero (INV-09)


def test_a_complete_stream_with_a_live_group_is_not_completed():
    capture = {'status': 'complete', 'group_state': 'alive', 'exit_code': 0, 'observed': {'num_turns': 1}}
    result = observation.observe(spec={'provider': 'claude'}, process_status='UNCERTAIN', capture=capture,
                                 identity_present=True)
    assert result['termination']['class'] == 'failed' and result['termination']['writer'] == 'uncertain'


def test_claude_message_usage_without_terminal_is_a_partial_derived_view():
    capture = {'status': 'cancelled', 'group_state': 'dead', 'exit_code': 143, 'observed': {'message_models': ['m']},
               'stream_metrics': {'message_usage': {'input_tokens': 3}, 'tools': {}}}
    result = observation.observe(spec={'provider': 'claude'}, process_status='STOPPED', capture=capture,
                                 identity_present=True)
    assert result['termination']['class'] == 'cancelled'
    assert result['usage'] == {'view': 'messages', 'source': 'derived', 'coverage': 'partial', 'alternatives': []}
    assert result['reported_model'] == {'value': ['m'], 'source': 'reported'}
    assert result['counters']['tool_calls']['value'] == 0 and result['counters']['tool_calls']['coverage'] == 'partial'


def streamed(provider, events, exit_code=0):
    """The adapter's sealed metadata for a stream read by `AgentStream` (status, observed, stream metrics)."""
    parser = AgentStream(provider, lambda kind, data: None)
    for event in events:
        parser.feed((json.dumps(event) + '\n').encode())
    status, _payload = parser.finish(exit_code)
    return {'status': status, 'observed': parser.observed, 'stream_metrics': parser.metrics.summary(),
            'exit_code': exit_code, 'group_state': 'dead'}


def test_a_codex_turn_is_observed_from_its_terminal_whatever_the_payload_validity():
    """Review finding 6: a real `turn.completed` with terminal usage and an invalid structured answer."""
    usage = {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 2}
    capture = streamed('codex', [{'type': 'thread.started', 'thread_id': 'synthetic'},
                                 {'type': 'item.completed', 'item': {'id': 'i0', 'type': 'agent_message',
                                                                     'text': 'not a JSON object'}},
                                 {'type': 'turn.completed', 'usage': usage}])
    assert capture['status'] == 'invalid' and capture['stream_metrics']['terminals'] == {'turn.completed': 1}
    result = observation.observe(spec={'provider': 'codex'}, process_status='STOPPED', capture=capture,
                                 identity_present=True)
    assert result['termination']['class'] == 'invalid_stream'  # result quality stays a separate classification
    assert result['counters']['native_turns'] == {'meaning': observation.MEANINGS['native_turns'], 'value': 1,
                                                  'source': 'measured', 'coverage': 'complete'}
    assert result['usage']['view'] == 'terminal' and 'native_turns' not in {m['signal'] for m in result['missing']}
    failed = streamed('codex', [{'type': 'turn.started'}, {'type': 'turn.failed', 'error': {'message': 'quota'}}])
    failed_result = observation.observe(spec={'provider': 'codex'}, process_status='STOPPED', capture=failed,
                                        identity_present=True)
    assert failed_result['termination']['class'] == 'failed'
    assert failed_result['counters']['native_turns']['value'] == 1
    assert failed_result['usage']['reason'] == 'not_reported'  # a turn ended; it just reported no usage
    cancelled = streamed('codex', [{'type': 'turn.started'}, {'type': 'item.started', 'item': {'id': 'i1'}}])
    cancelled['status'] = 'cancelled'  # set by the supervisor before it stops the group
    cut = observation.observe(spec={'provider': 'codex'}, process_status='STOPPED', capture=cancelled,
                              identity_present=True)
    assert cut['counters']['native_turns']['value'] is None and cut['counters']['native_turns']['reason'] == 'no_terminal'
    # Captures sealed before the terminal counter keep the earlier conservative rule.
    legacy = {**capture, 'stream_metrics': {k: v for k, v in capture['stream_metrics'].items() if k != 'terminals'}}
    assert observation.observe(spec={'provider': 'codex'}, process_status='STOPPED', capture=legacy,
                               identity_present=True)['counters']['native_turns']['value'] is None
    # metrics-1 keeps its historical item-derived count, unchanged by the new counter.
    metrics = attempt_metrics(request={'role': 'planner', 'selection': {}},
                              result={'metadata_json': json.dumps(capture)}, status='INVALID',
                              spec={'provider': 'codex'}, executor_round=0)
    assert metrics['turns'] == 1 and metrics['provenance']['turns'] == 'derived'


# --- trace-payload-1 ------------------------------------------------------------------------------------------------

SECRETS = ('sk-ant-' + 'A' * 30, 'ghp_' + 'b' * 36, 'AKIA' + 'C' * 16, 'xoxb-' + '1' * 20,
           'eyJ' + 'h' * 12 + '.' + 'p' * 12 + '.' + 's' * 12, 'Bearer ' + 'z' * 24,
           '-----BEGIN RSA PRIVATE KEY-----\nsynthetic\n-----END RSA PRIVATE KEY-----')


@pytest.mark.parametrize('secret', SECRETS)
def test_secret_values_are_masked_everywhere_without_a_digest(secret):
    payload = {'note': f'synthetic {secret} tail', 'nested': [{'value': secret}], secret: 'key'}
    original = copy.deepcopy(payload)
    bounded = trace_payload.bound(payload)
    text = json.dumps(bounded.payload)
    assert secret not in text and trace_payload.MASK in text and bounded.redactions >= 3
    assert payload == original  # the input is not modified
    assert no_digest(text, secret)


def no_digest(text, secret):
    import hashlib
    return hashlib.sha256(secret.encode()).hexdigest() not in text


def test_sensitive_keys_lose_their_values_and_ordinary_counters_stay():
    bounded = trace_payload.bound({'env': {'HOME': '/synthetic'}, 'argv': ['codex', '--secret'], 'prompt': 'text',
                                   'api_key': 'value', 'access_token': 'value', 'input_tokens': 12,
                                   'owner_token': 'fencing-id', 'job_id': 3})
    assert bounded.payload['env'] == bounded.payload['argv'] == {'redacted': 'sensitive_key'}
    assert bounded.payload['prompt'] == bounded.payload['api_key'] == {'redacted': 'sensitive_key'}
    assert bounded.payload['access_token'] == {'redacted': 'sensitive_key'}
    assert bounded.payload['input_tokens'] == 12 and bounded.payload['owner_token'] == 'fencing-id'
    assert bounded.redactions == 5 and not bounded.truncated


def test_large_strings_become_artifact_references_after_masking():
    secret = SECRETS[0]
    large = ('synthetic line\n' * 200) + secret
    bounded = trace_payload.bound({'output': large})
    reference = bounded.payload['output']['artifact']
    [(stored, data)] = bounded.artifacts
    assert stored == reference and reference['size'] == len(data) and secret.encode() not in data
    assert reference['media'].startswith('text/plain')


def test_collections_depth_and_total_size_are_bounded_with_markers():
    wide = trace_payload.bound({'items': list(range(150))})
    assert wide.truncated and wide.payload['items'][-1] == {'truncated': 'items', 'omitted': 50}
    deep = {}
    cursor = deep
    for _ in range(20):
        cursor['next'] = {}
        cursor = cursor['next']
    assert trace_payload.bound(deep).truncated
    big = trace_payload.bound({f'k{n:03}': 'x' * 900 for n in range(20)})
    assert big.payload['truncated'] == 'payload' and big.payload['artifact']['media'] == 'application/json'
    assert len(json.dumps(big.payload)) < trace_payload.MAX_PAYLOAD
    with pytest.raises(TypeError):
        trace_payload.bound(['not', 'a', 'mapping'])


# --- knowledge-delivery-1 and tool-discovery-1 ----------------------------------------------------------------------

DIGEST = 'a' * 64


def delivery(**changes):
    value = {'format': 'knowledge-delivery-1', 'invocation_id': 'managed_attempt:synthetic-1',
             'channel': 'query_result', 'entity_type': 'task', 'stable_id': 'item-1', 'revision_id': 'rev-1',
             'sections': ['body'], 'exposure': 'excerpt', 'digest': DIGEST,
             'page': {'truncated': True, 'page': 1, 'next_cursor': 'c2'}, 'failure': None}
    value.update(changes)
    return {key: item for key, item in value.items() if item is not ...}


def test_knowledge_delivery_envelope_is_closed_and_never_claims_comprehension():
    assert envelopes.knowledge_delivery(delivery())['exposure'] == 'excerpt'
    failed = delivery(failure='entity_missing', digest=...)
    assert envelopes.knowledge_delivery(failed)['failure'] == 'entity_missing'
    for bad, code in ((delivery(understood=True), 'unknown_field'), (delivery(channel='memory'), 'invalid_value'),
                      (delivery(exposure='summary'), 'invalid_value'), (delivery(digest=...), 'invalid_digest'),
                      (delivery(failure='over_limit'), 'digest_without_delivery'),
                      (delivery(sections=['s'] * 51), 'invalid_sections'), (delivery(revision_id=...), 'missing_field'),
                      (delivery(page={'truncated': 'yes'}), 'invalid_value'),
                      (delivery(entity_type='file'), 'invalid_value')):
        with pytest.raises(envelopes.EnvelopeError) as caught:
            envelopes.knowledge_delivery(bad)
        assert caught.value.code == code


def test_tool_discovery_envelopes_keep_search_and_describe_apart_from_invocation():
    search = {'format': 'tool-discovery-1', 'invocation_id': 'managed_attempt:synthetic-1', 'action': 'search',
              'catalogue_sha256': DIGEST, 'query_sha256': 'b' * 64, 'query_length': 12,
              'results': [{'id': 'knowledge.get', 'version': 1, 'schema_sha256': 'c' * 64}], 'page': {'truncated': False}}
    describe = {'format': 'tool-discovery-1', 'invocation_id': 'managed_attempt:synthetic-1', 'action': 'describe',
                'catalogue_sha256': DIGEST, 'id': 'knowledge.get', 'version': 1, 'outcome': 'delivered',
                'schema_sha256': 'c' * 64}
    assert envelopes.tool_discovery(search) and envelopes.tool_discovery(describe)
    refused = {**describe, 'outcome': 'out_of_scope'}
    refused.pop('schema_sha256')
    assert envelopes.tool_discovery(refused)['outcome'] == 'out_of_scope'
    for bad, code in (({**search, 'query': 'raw text'}, 'unknown_field'),
                      ({**search, 'results': [{'id': 'x', 'version': 1, 'schema_sha256': 'c' * 64}] * 51},
                       'invalid_results'),
                      ({**describe, 'action': 'invoke'}, 'invalid_value'),
                      ({**refused, 'schema_sha256': 'c' * 64}, 'digest_without_delivery'),
                      ({**describe, 'schema_sha256': 'short'}, 'invalid_digest')):
        with pytest.raises(envelopes.EnvelopeError) as caught:
            envelopes.tool_discovery(bad)
        assert caught.value.code == code
