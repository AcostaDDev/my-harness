"""P001-T003: usage capture, invocation ledger, billing binding, cohorts and archive parity.

Synthetic streams, temporary Git/SQLite, the local CLI probe and the packaged pinned references only; no provider.
"""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from alembic import command
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.streams import AgentStream
from my_harness.core.engine.metric_references import digest, load_packaged_bundle
from my_harness.core.engine.usage_capture import build, components, evidence
from my_harness.core.engine.valuation import calculate
from my_harness.services.configuration import parse, runtime
from my_harness.services.configuration_editing import technical
from my_harness.storage import accounting, accounting_operations as operations
from my_harness.storage.backup import BackupError, create_backup, restore_backup, upgrade_bundle, verify_bundle
from my_harness.storage.billing import resolve
from my_harness.storage.database import make_engine
from my_harness.storage.models import (
    ManagedAttemptRow, ManagedRunRow, UsageCaptureRow, UsageComponentRow, UsageInvocationRow,
    UsageValuationLineRow, UsageValuationRow, ValuationCohortMemberRow, ValuationCohortRow,
)
from my_harness.storage.retention import apply_retention, preview_retention
from test_backup import db_path, dump_rows, reseal_database
from test_configuration import activate, active_global, change, dumps, project_data, register, save, setup  # noqa: F401
from test_managed import context, edit, repository, review, submit, worker  # noqa: F401
from conftest import clear_accounting
from test_metrics import CLAUDE_RESULT, CLAUDE_STREAM, flow, sealed

PACKAGED = load_packaged_bundle().id
SPEC = {'provider': 'claude', 'adapter_version': 'cli-14', 'cli_version': '2.1.304', 'argv': ['secret-argument'],
        'prompt_path': '/private/synthetic/prompt.txt', 'environment_keys': ['SYNTHETIC_SECRET'],
        'cwd': '/private/synthetic/checkout', 'artifacts': '/private/synthetic'}
CLAUDE_API = {'provider': 'claude', 'platform': 'anthropic_first_party', 'product': 'claude_api',
              'scheme': 'anthropic_api_usd', 'unit': 'USD', 'basis': 'api_usd', 'references': PACKAGED,
              'conditions': {'speed': {'value': 'standard', 'source': 'synthetic operator assertion'},
                             'geography': {'value': 'global', 'source': 'synthetic operator assertion'}}}
CODEX_CREDITS = {'provider': 'codex', 'platform': 'openai_first_party', 'product': 'work_codex',
                 'scheme': 'chatgpt_work_codex_credit', 'unit': 'chatgpt_work_codex_credit', 'basis': 'token_credit',
                 'references': PACKAGED,
                 'conditions': {'speed': {'value': 'standard', 'source': 'synthetic assertion'},
                                'geography': {'value': 'global', 'source': 'synthetic assertion'},
                                'eligibility': {'value': 'scheme_eligible', 'source': 'synthetic assertion'}}}


def usage(input_tokens, read, write_5m, output, write_1h=0):
    return {'input_tokens': input_tokens, 'cache_read_input_tokens': read,
            'cache_creation_input_tokens': write_5m + write_1h, 'output_tokens': output,
            'cache_creation': {'ephemeral_5m_input_tokens': write_5m, 'ephemeral_1h_input_tokens': write_1h}}


def message(ident, model, start, final_output):
    return [{'type': 'stream_event', 'event': {'type': 'message_start', 'message': {
                'id': ident, 'model': model, 'usage': start}}},
            {'type': 'stream_event', 'event': {'type': 'message_delta', 'usage': {'output_tokens': final_output}}}]


# C1 split into two complete requests (T001 A01: USD 0.44 at the pinned Sonnet Standard rates).
C1_REQUESTS = (message('msg_1', 'claude-sonnet-5-5', usage(60000, 400000, 20000, 1), 4000)
               + message('msg_1', 'claude-sonnet-5-5', usage(60000, 400000, 20000, 1), 4000)  # replayed snapshot
               + message('msg_2', 'claude-sonnet-5-5', usage(40000, 500000, 0, 1), 6000))
C1_TOTAL = usage(100000, 900000, 20000, 10000)
EXACT_COST = '0.4400000000000000000001'


def terminal(total=C1_TOTAL, cost=EXACT_COST):
    line = json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 2, 'usage': total,
                       'total_cost_usd': '__COST__', 'structured_output': {'result': 'synthetic'}})
    # The literal keeps more digits than a binary float can hold: only the lexeme preserves it.
    return line.replace('"__COST__"', cost)


def metadata(provider, events, *, final=None):
    parser = AgentStream(provider, lambda *_: None)
    for event in events:
        parser.feed(((event if isinstance(event, str) else json.dumps(event)) + '\n').encode())
    status, _ = parser.finish(0)
    return {'status': status, 'observed': parser.observed, 'stream_metrics': parser.metrics.summary(),
            'final_usage_observed': len(parser.terminals) == 1 if final is None else final,
            'wall_duration_seconds': 2.5, 'exit_code': 0, 'group_state': 'dead', 'normalization': 'terminal-2',
            'started_at': '2026-10-28T10:00:00+00:00',
            'artifacts': {'stdout': {'path': '/private/synthetic/stdout.bin', 'size': 10, 'sha256': 'a' * 64}}}


def captured(provider, events, **changes):
    return build(spec={**SPEC, 'provider': provider}, status='STOPPED', identity_present=True,
                 capture={**metadata(provider, events), **changes},
                 selection={'model': 'requested-model', 'effort': 'high'})


def scenario(profile, *, retrospective=True):
    asserted = {**{k: profile[k] for k in ('provider', 'platform', 'product', 'scheme', 'unit', 'basis', 'references')},
                'conditions': {k: {**v, 'provenance': 'asserted'} for k, v in profile['conditions'].items()}}
    return accounting.scenario_for(asserted, accounting.utc('2026-10-28T10:00:00+00:00'), retrospective=retrospective)


# --- pure capture and reconciliation ------------------------------------------------------------


def test_a15_terminal_counts_once_requests_replace_cumulative_snapshots_and_exact_lexeme_is_kept():
    capture = captured('claude', C1_REQUESTS + [terminal()])
    assert capture['launch'] == 'observed' and capture['final_usage_observed'] is True
    assert capture['reported_amounts']['total_cost_usd'] == {'value': EXACT_COST, 'representation': 'lexeme'}
    requests = [c for c in components(capture) if c['grain'] == 'request']
    assert [(c['key'], c['input_tokens'], c['output_tokens'], c['write_5m']) for c in requests] == [
        ('request:msg_1', 60000, 4000, 20000), ('request:msg_2', 40000, 6000, 0)]  # delta replaced, replay ignored
    selected = evidence(capture)
    assert selected['coverage'] == 'complete' and selected['partition'] == 'disjoint' and selected['reasons'] == []
    assert {c['grain'] for c in selected['components']} == {'request'}
    result = calculate(selected, scenario(CLAUDE_API), load_packaged_bundle())
    assert (result['status'], result['amount']) == ('complete', '0.440000000000')
    assert result['warnings'] == ['effective_period_unknown']  # retrospective scenario, not historical validity
    # metrics-1 keeps its terminal semantics: the new retention changes none of its values.
    from my_harness.core.engine.metrics import attempt_metrics
    row = attempt_metrics(request={'role': 'executor', 'selection': {'model': 'requested-model', 'effort': 'high'}},
                          result={'metadata_json': json.dumps(metadata('claude', C1_REQUESTS + [terminal()]))},
                          status='COMPLETED', spec=SPEC, executor_round=1)
    assert (row['accounting'], row['output_tokens'], row['cost_usd']) == ('terminal', 10000, 0.44)


def test_a15_conflicting_duplicate_request_id_invalidates_only_that_partition():
    events = (message('msg_1', 'claude-sonnet-5-5', usage(60000, 400000, 20000, 1), 4000)
              + message('msg_1', 'claude-sonnet-5-5', usage(1, 400000, 20000, 1), 4000)
              + message('msg_2', 'claude-sonnet-5-5', usage(40000, 500000, 0, 1), 6000) + [terminal()])
    capture = captured('claude', events)
    selected = evidence(capture)
    assert selected['components'][0]['grain'] == 'invocation_total'
    assert {'model_partition_conflict', 'model_unreported'} <= set(selected['reasons'])
    assert calculate(selected, scenario(CLAUDE_API), load_packaged_bundle())['amount'] is None


def test_missing_terminal_keeps_a_partial_subtotal_never_final_usage():
    capture = captured('claude', C1_REQUESTS)
    selected = evidence(capture)
    assert (selected['coverage'], selected['reasons']) == ('partial', ['terminal_missing'])
    result = calculate(selected, scenario(CLAUDE_API), load_packaged_bundle())
    assert result['status'] == 'incomplete' and result['amount'] is None
    assert result['known_subtotal'] == '0.440000000000' and 'partial_capture' in result['reasons']
    anonymous = [{'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'usage': usage(1, 1, 0, 1)}}}]
    absent = evidence(captured('claude', C1_REQUESTS + anonymous))
    assert (absent['coverage'], absent['components']) == ('absent', [])
    assert {'terminal_missing', 'usage_missing'} <= set(absent['reasons'])


def test_a16_model_partition_is_priced_once_or_reported_as_conflict():
    meta = json.loads(sealed('claude', CLAUDE_STREAM + [CLAUDE_RESULT])['metadata_json'])
    base = {**meta, 'status': 'complete', 'final_usage_observed': True, 'exit_code': 0, 'group_state': 'dead'}
    capture = build(spec=SPEC, status='STOPPED', identity_present=True, capture=base, selection={})
    selected = evidence(capture)
    assert selected['partition'] == 'disjoint' and [c['key'] for c in selected['components']] == ['model:m-a', 'model:m-b']
    # The single cache writer's lifetime would come from the terminal; here none is reported, so it stays unknown.
    assert selected['components'][0]['write_5m'] is None and selected['components'][1]['write_5m'] == 0
    broken = copy.deepcopy(base)
    broken['observed']['modelUsage']['m-b']['outputTokens'] = 11
    conflict = evidence(build(spec=SPEC, status='STOPPED', identity_present=True, capture=broken, selection={}))
    assert conflict['components'][0]['key'] == 'invocation' and 'model_partition_conflict' in conflict['reasons']


def test_codex_requested_model_never_becomes_the_reported_model():
    events = [{'type': 'thread.started', 'thread_id': 'synthetic'},
              {'type': 'item.completed', 'item': {'id': 'i1', 'type': 'agent_message', 'text': '{"result": "x"}'}},
              {'type': 'turn.completed', 'usage': {'input_tokens': 1000000, 'cached_input_tokens': 900000,
                                                    'cache_write_input_tokens': 0, 'output_tokens': 10000}}]
    capture = captured('codex', events)
    selected = evidence(capture)
    assert selected['components'][0]['reported_model'] is None and 'model_unreported' in selected['reasons']
    assert capture['requested']['model'] == 'requested-model'
    result = calculate(selected, scenario(CODEX_CREDITS), load_packaged_bundle())
    assert result['amount'] is None and 'model_unreported' in result['reasons']


@pytest.mark.parametrize('spec, status, identity, capture, expected', [
    (None, None, False, None, 'unknown_execution'),
    ({**SPEC, 'launch_permitted': False}, 'STOPPED', False, {'status': 'refused', 'group_state': 'dead'}, 'not_invoked'),
    (SPEC, 'STOPPED', True, {'status': 'refused', 'diagnostic_code': 'identity_changed'}, 'not_invoked'),
    (SPEC, 'PENDING', False, None, 'pending'),
    (SPEC, 'RUNNING', True, None, 'unknown_execution'),
    (SPEC, 'STOPPED', True, {'status': 'interrupted', 'settled_by': 'closing_owner'}, 'observed'),
])
def test_launch_gate_needs_positive_evidence(spec, status, identity, capture, expected):
    document = build(spec=spec, status=status, identity_present=identity, capture=capture, selection={})
    assert document['launch'] == expected
    if expected == 'not_invoked':
        assert evidence(document) is None  # excluded from spend denominators, never zero consumption
    if capture and capture.get('settled_by'):
        assert evidence(document)['coverage'] == 'absent' and 'partial_capture' in evidence(document)['reasons']


def test_capture_is_allowlisted_and_activity_is_not_billable_evidence():
    events = [{'type': 'assistant', 'message': {'id': 'm', 'model': 'claude-sonnet-5-5', 'content': [
        {'type': 'tool_use', 'id': 't1', 'name': 'Task'}, {'type': 'tool_use', 'id': 't2', 'name': 'WebSearch'}]}}]
    capture = captured('claude', events + C1_REQUESTS + [terminal()])
    text = json.dumps(capture)
    assert not any(secret in text for secret in ('secret-argument', '/private/', 'SYNTHETIC_SECRET', 'prompt'))
    assert capture['artifacts'] == {'stdout': {'sha256': 'a' * 64, 'size': 10}}
    selected = evidence(capture)
    assert (selected['delegation'], selected['charges_complete']) == ('unknown', False)
    result = calculate(selected, scenario(CLAUDE_API), load_packaged_bundle())
    assert {'delegation_boundary_unknown', 'tool_charge_unknown'} <= set(result['reasons'])
    assert result['known_subtotal'] == '0.440000000000' and result['amount'] is None


# --- billing formats and frozen binding ---------------------------------------------------------


def billing_data(data, defaults=None, profiles=None):
    value = copy.deepcopy(data)
    value['format'] = 'local-config-10'
    value['billing'] = {'profiles': copy.deepcopy(profiles or {'credits': CODEX_CREDITS}),
                        'defaults': defaults if defaults is not None else {'reviewer': 'credits', 'executor': 'credits'}}
    return value


def test_billing_metadata_requires_the_explicit_new_format_and_is_not_executable(setup):
    _, data, _ = setup
    with pytest.raises(ValueError, match='local-config-10'):
        parse(dumps({**data, 'billing': {'defaults': {}}}), 'global')
    parsed = parse(dumps(billing_data(data)), 'global')
    assert runtime(parsed).get('billing') is None and runtime(parsed)['format'] == 'local-config-9'
    with pytest.raises(ValueError, match='billing.defaults.executor'):
        parse(dumps(billing_data(data, profiles={'api': CLAUDE_API}, defaults={'executor': 'api'})), 'global')
    for field, value in (('basis', 'invoice'), ('references', 'latest'), ('api_key', 'x')):
        broken = billing_data(data)
        broken['billing']['profiles']['credits'][field] = value
        with pytest.raises(ValueError):
            parse(dumps(broken), 'global')
    assert parse(dumps(data), 'global')['format'] == 'local-config-9'  # v9 bytes keep their meaning


def test_binding_dereferences_only_frozen_revisions_and_billing_edits_keep_technical_identity(setup):
    repo, data, _ = setup
    active_global(repo, billing_data(data))
    first = repo.read('global')['active']
    later = billing_data(data, defaults={'reviewer': 'credits'})
    save(repo, [change(repo, dumps(later))], key='billing-only')
    activate(repo, key='billing-only-activation')
    with Session(repo.managed.engine) as session:
        frozen = resolve(session, 'executor', global_reference=first)
        assert frozen['profile_name'] == 'credits' and frozen['profile']['conditions']['speed']['provenance'] == 'asserted'
        current = resolve(session, 'executor', global_reference=repo.read('global')['saved'])
        assert (current['profile'], current['reason']) == (None, 'billing_profile_unknown')
        # A project-config-2 selection of a profile whose provider differs from its agent stays unknown.
        project = {'format': 'project-config-2', 'global': first, 'billing': {'executor': 'credits'},
                   'agents': {'executor': {'provider': 'claude'}}}
        assert resolve(session, 'executor', project=project)['reason'] == 'billing_profile_unknown'
        assert resolve(session, 'executor', project={'format': 'project-config-1', 'global': first}) == frozen
    assert technical(billing_data(data)) == technical(data)  # billing never invalidates a technical receipt


def test_managed_binding_follows_the_job_sealed_project_revision_not_later_selections(setup, tmp_path):
    repo, data, _ = setup
    data['agents']['executor']['provider'] = 'codex'
    active_global(repo, billing_data(data, defaults={}))
    register(repo, tmp_path / 'one', 'one')
    project = {**project_data(data, repo, tmp_path / 'one', 'one'), 'format': 'project-config-2',
               'billing': {'executor': 'credits'}}
    save(repo, [change(repo, dumps(project), 'project:one')], key='project-v2')
    sealed_revision = repo.read('project:one')['saved']
    project['billing'] = {}
    save(repo, [change(repo, dumps(project), 'project:one')], key='project-v2-later')
    versions = {'project_registry_id': 'one', 'project_configuration_revision': str(sealed_revision['revision']),
                'project_configuration_sha256': sealed_revision['sha256']}
    with Session(repo.managed.engine) as session:
        from my_harness.storage.billing import for_versions
        binding = for_versions(session, versions, 'executor')
        assert binding['profile_name'] == 'credits' and binding['configuration']['project']['scope'] == 'project:one'
        assert for_versions(session, {'project_configuration_revision': None}, 'executor') is None  # old job: unknown
        tampered = for_versions(session, {**versions, 'project_configuration_sha256': '0' * 64}, 'executor')
        assert (tampered['profile'], tampered['reason']) == (None, 'configuration_unavailable')


# --- native sources -----------------------------------------------------------------------------


def rows(engine, model, **where):
    with Session(engine) as session:
        query = select(model)
        for key, value in where.items():
            query = query.where(getattr(model, key) == value)
        return [{c.name: getattr(row, c.name) for c in model.__table__.columns} for row in session.scalars(query)]


def test_managed_attempts_record_one_invocation_each_in_the_native_transaction(tmp_path, context, repository):
    port, job, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    invocations = rows(repository.engine, UsageInvocationRow)
    attempts = rows(repository.engine, ManagedAttemptRow)
    assert sorted(i['source_id'] for i in invocations) == sorted(a['id'] for a in attempts)
    assert {(i['source_kind'], i['launch'], i['binding']) for i in invocations} == {('managed_attempt', 'observed', None)}
    assert [i['role'] for i in sorted(invocations, key=lambda i: i['started_at'])] == ['planner', 'executor', 'reviewer']
    captures = rows(repository.engine, UsageCaptureRow)
    assert len(captures) == 3 and all(c['digest'] == digest(c['document']) for c in captures)
    assert rows(repository.engine, UsageValuationRow) == []  # no frozen billing profile: unpriced, never zero
    executor = next(c for c in captures if c['document']['client']['provider'] == 'claude')
    assert executor['document']['reported_amounts']['total_cost_usd'] == {'value': '0.0125', 'representation': 'lexeme'}
    before = (rows(repository.engine, UsageCaptureRow), rows(repository.engine, UsageComponentRow))
    with repository._write() as session:
        for attempt in session.scalars(select(ManagedAttemptRow)).all():
            accounting.settle_attempt(session, session.get(ManagedRunRow, attempt.run_id), attempt)
    assert (rows(repository.engine, UsageCaptureRow), rows(repository.engine, UsageComponentRow)) == before


def test_a17_equal_bytes_in_two_invocations_are_two_captures(tmp_path, context, repository):
    flow(tmp_path, context, repository)[2].run_once()
    document = captured('claude', C1_REQUESTS + [terminal()])
    with repository._write() as session:
        invocations = session.scalars(select(UsageInvocationRow).order_by(UsageInvocationRow.id)).all()[:2]
        first = [accounting.append_capture(session, i, document, source='capture', now='2026-10-28T10:00:00+00:00').id
                 for i in invocations]
        again = [accounting.append_capture(session, i, document, source='capture', now='2026-10-28T10:00:01+00:00').id
                 for i in invocations]
    assert first == again and first[0] != first[1]


def test_scripted_ports_without_process_rows_stay_unknown_execution(repository, context):
    submit(repository, context)
    worker(repository, context, [edit(), review()])[0].run_once()
    invocations = rows(repository.engine, UsageInvocationRow)
    assert invocations and {i['launch'] for i in invocations} == {'unknown_execution'}
    assert rows(repository.engine, UsageCaptureRow) == []  # no manufactured capture, the gap stays visible


def test_assistance_freezes_its_profile_and_records_an_admission_valuation(setup, tmp_path):
    from test_cli_agents import adapter
    from test_configuration_api import app_for
    from test_configuration_editing import assistance_body, confirm_assistance
    from session_client import TestClient
    from dataclasses import asdict
    repo, data, _ = setup
    port = adapter(tmp_path)
    config = port.agents['reviewer']
    fields = asdict(config)
    fields.update(environment={**data['agents']['reviewer']['environment'], **dict(config.environment)},
                  timeout_seconds=10, executable=list(config.executable))
    fields = {key: fields[key] for key in ('provider', 'executable', 'cli_version', 'environment', 'timeout_seconds')}
    data['agents'] = {'reviewer': {**fields, 'model': 'synthetic-reviewer', 'effort': 'medium'}, 'executor': fields}
    data['git']['executable'] = shutil.which('git')
    active_global(repo, billing_data(data))
    with TestClient(app_for(repo)) as http:
        http.headers['X-My-Harness'] = '1'
        body = assistance_body(http, 'reviewer')
        _, result = confirm_assistance(http, body)
    [invocation] = rows(repo.managed.engine, UsageInvocationRow)
    assert (invocation['source_kind'], invocation['operation_id'], invocation['project_id']) == (
        'configuration_assistance', result['id'], None)
    assert invocation['binding']['profile_name'] == 'credits' and invocation['launch'] == 'observed'
    assert invocation['role'] == 'configuration' and invocation['agent'] == 'reviewer'
    [valuation] = rows(repo.managed.engine, UsageValuationRow)
    assert valuation['origin'] == 'admission' and valuation['amount'] is None
    assert valuation['basis'] == 'token_credit' and valuation['status'] in ('incomplete', 'unsupported')
    assert rows(repo.managed.engine, ManagedAttemptRow) == []  # no fictitious managed attempt


# --- explicit operations ------------------------------------------------------------------------


def test_reference_import_is_previewed_idempotent_and_rejects_conflicts(repository, tmp_path):
    raw = (Path(accounting.__file__).parents[1] / 'core/engine/references/metrics-2026-10-27-v1.json').read_bytes()
    preview = operations.reference_preview(repository.engine, raw)
    assert preview['bundle'] == PACKAGED and preview['conflicts'] == [] and preview['new_rows'] == 39
    with pytest.raises(operations.OperationRefused, match='stale_accounting_preview'):
        operations.reference_import(repository.engine, raw, preview_sha256='0' * 64)
    assert operations.reference_import(repository.engine, raw, preview_sha256=preview['sha256'])['inserted_rows'] == 39
    again = operations.reference_preview(repository.engine, raw)
    assert again['sha256'] == preview['sha256'] and (again['new_rows'], again['existing_rows']) == (0, 39)
    assert operations.reference_import(repository.engine, raw, preview_sha256=preview['sha256'])['inserted_rows'] == 0
    with pytest.raises(operations.OperationRefused, match='reference_bundle_invalid'):
        operations.reference_preview(repository.engine, raw.replace(b'"anthropic_api_usd"', b'"other_scheme"', 1))
    with pytest.raises(operations.OperationRefused, match='reference_bundle_size'):
        operations.reference_preview(repository.engine, b' ' * (operations.MAX_BUNDLE_BYTES + 1))


def test_a27_accounting_backfill_is_explicit_idempotent_and_never_rewrites_history(tmp_path, context, repository,
                                                                                    migrated_database):
    flow(tmp_path, context, repository)[2].run_once()
    path = db_path(migrated_database)
    clear_accounting(path)  # the same native history as a database upgraded before accounting existed
    before = dump_rows(path)
    preview = operations.backfill_preview(repository.engine, name='history-2026-10')
    assert preview['expected'] == 3
    with pytest.raises(operations.OperationRefused, match='stale_accounting_preview'):
        operations.backfill(repository.engine, name='history-2026-10', preview_sha256='0' * 64, key='b1')
    report = operations.backfill(repository.engine, name='history-2026-10', preview_sha256=preview['sha256'], key='b1')
    assert (report['status'], report['expected'], report['built']) == ('CLOSED', 3, 3)
    assert report['unpriced'] == {'billing_profile_unknown': 3} and report['valuations'] == {}
    assert {c['source'] for c in rows(repository.engine, UsageCaptureRow)} == {'backfill'}
    assert operations.backfill(repository.engine, name='history-2026-10', preview_sha256=preview['sha256'],
                               key='b1') == report
    assert operations.backfill_preview(repository.engine, name='later')['expected'] == 0
    after = dump_rows(path)
    for table in ('managed_attempts', 'attempt_metrics', 'attempt_model_metrics', 'managed_runs', 'run_projections'):
        assert after[table] == before[table]


def c1_capture(repository):
    """Append changed (synthetic) evidence to the Claude executor invocation; the original stays."""
    document = build(spec=SPEC, status='STOPPED', identity_present=True,
                     capture=metadata('claude', C1_REQUESTS + [terminal()]), selection={'model': 'requested-model'})
    with repository._write() as session:
        invocation = session.scalar(select(UsageInvocationRow).where(UsageInvocationRow.role == 'executor'))
        accounting.append_capture(session, invocation, document, source='capture', now='2026-10-28T10:00:00+00:00')
        return invocation.id


def test_repricing_cohorts_are_explicit_resumable_and_reuse_immutable_valuations(tmp_path, context, repository,
                                                                                migrated_database, monkeypatch):
    flow(tmp_path, context, repository)[2].run_once()
    executor = c1_capture(repository)
    path = db_path(migrated_database)
    before = dump_rows(path)
    kwargs = dict(profile=CLAUDE_API, retrospective=True, filters={'source_kinds': ['managed_attempt']})
    preview = operations.reprice_preview(repository.engine, name='api-equivalent', **kwargs)
    assert preview['expected'] == 1  # Codex planner/reviewer are excluded by the stated provider
    monkeypatch.setattr(operations, 'BATCH', 1)
    report = operations.reprice(repository.engine, name='api-equivalent', preview_sha256=preview['sha256'],
                                key='r1', **kwargs)
    assert report['status'] == 'CLOSED' and report['valuations'] == {'complete': 1}
    [valuation] = rows(repository.engine, UsageValuationRow, invocation_id=executor)
    assert (valuation['origin'], valuation['amount'], valuation['retrospective']) == ('repricing', '0.440000000000', True)
    assert valuation['warnings'] == ['effective_period_unknown']
    lines = rows(repository.engine, UsageValuationLineRow, valuation_id=valuation['id'])
    assert sum(line['quantity'] for line in lines) == 100000 + 900000 + 20000 + 10000
    # Another cohort over the same evidence/scenario reuses the immutable valuation through its own membership.
    again = operations.reprice_preview(repository.engine, name='same-scenario', **kwargs)
    operations.reprice(repository.engine, name='same-scenario', preview_sha256=again['sha256'], key='r2', **kwargs)
    assert len(rows(repository.engine, UsageValuationRow)) == 1
    assert len(rows(repository.engine, ValuationCohortMemberRow)) == 2
    # Contemporaneous use of an unknown-period tariff stays incomplete with its known subtotal.
    contemporaneous = dict(kwargs, retrospective=False)
    shown = operations.reprice_preview(repository.engine, name='contemporaneous', **contemporaneous)
    operations.reprice(repository.engine, name='contemporaneous', preview_sha256=shown['sha256'], key='r3',
                       **contemporaneous)
    current = next(v for v in rows(repository.engine, UsageValuationRow) if not v['retrospective'])
    assert (current['status'], current['amount'], current['known_subtotal']) == ('incomplete', None, '0.440000000000')
    assert 'effective_period_unknown' in current['reasons']
    after = dump_rows(path)
    for table in ('managed_attempts', 'attempt_metrics', 'usage_captures', 'usage_invocations'):
        assert after[table] == before[table]


def test_a27_interrupted_cohort_construction_stays_building_and_resumes(tmp_path, context, repository, monkeypatch):
    flow(tmp_path, context, repository)[2].run_once()
    kwargs = dict(profile=CODEX_CREDITS, retrospective=True, filters={})
    preview = operations.reprice_preview(repository.engine, name='credits', **kwargs)
    assert preview['expected'] == 2
    monkeypatch.setattr(operations, 'BATCH', 1)
    original, calls = operations._reprice_member, []

    def crash(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('synthetic interruption')
        return original(*args)
    monkeypatch.setattr(operations, '_reprice_member', crash)
    with pytest.raises(RuntimeError):
        operations.reprice(repository.engine, name='credits', preview_sha256=preview['sha256'], key='c1', **kwargs)
    [cohort] = rows(repository.engine, ValuationCohortRow)
    assert (cohort['status'], cohort['built'], cohort['expected']) == ('BUILDING', 1, 2)
    report = operations.reprice(repository.engine, name='credits', preview_sha256=preview['sha256'], key='c1', **kwargs)
    assert (report['status'], report['built']) == ('CLOSED', 2)
    assert sum(report['valuations'].values()) + sum(report['unpriced'].values()) == 2
    with pytest.raises(operations.OperationRefused, match='idempotency_key_reused'):
        other = operations.reprice_preview(repository.engine, name='credits-2', **kwargs)
        operations.reprice(repository.engine, name='credits-2', preview_sha256=other['sha256'], key='c1', **kwargs)


# --- retention and archives ---------------------------------------------------------------------


LEGACY_TABLES = ('managed_runs', 'managed_jobs', 'managed_attempts', 'managed_processes', 'managed_events',
                 'attempt_metrics', 'attempt_model_metrics', 'run_projections', 'configuration_revisions')
ACCOUNTING = ('usage_invocations', 'usage_captures', 'usage_components', 'metrics_references', 'usage_valuations',
              'usage_valuation_lines', 'valuation_cohorts', 'valuation_cohort_members')


def priced_history(tmp_path, context, repository):
    port, _, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    c1_capture(repository)
    kwargs = dict(profile=CLAUDE_API, retrospective=True, filters={})
    preview = operations.reprice_preview(repository.engine, name='archive', **kwargs)
    operations.reprice(repository.engine, name='archive', preview_sha256=preview['sha256'], key='a1', **kwargs)
    return port


def test_retention_removes_streams_without_erasing_accounting_facts(tmp_path, context, repository, migrated_database):
    port = priced_history(tmp_path, context, repository)
    path = db_path(migrated_database)
    before = dump_rows(path)
    options = dict(artifact_roots=[port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
    shown = preview_retention(path, **options)
    apply_retention(path, **options, preview_sha256=shown['preview_sha256'], reason='Synthetic retention',
                    confirmed=True, writers_stopped=True)
    after = dump_rows(path)
    assert all(after[table] == before[table] for table in ACCOUNTING)


def test_a31_format3_backup_verifies_accounting_and_restored_consultation_is_query_only(tmp_path, context, repository,
                                                                                        migrated_database):
    port = priced_history(tmp_path, context, repository)
    bundle = tmp_path / 'bundle'
    manifest = create_backup(db_path(migrated_database), bundle, artifact_roots=[port.artifact_root],
                             writers_stopped=True)
    assert manifest['format'] == 3 and manifest['accounting']['usage_valuations'] == 1
    restored = tmp_path / 'restored'
    restore_backup(bundle, restored)
    engine = make_engine(f'sqlite:///{restored / "state.sqlite3"}')
    try:
        assert rows(engine, UsageValuationRow)[0]['amount'] == '0.440000000000'
        with pytest.raises(operations.OperationRefused, match='restored_read_only'):
            operations.backfill_preview(engine, name='archive-backfill')
    finally:
        engine.dispose()
    shutil.rmtree(port.artifact_root)  # consultation needs no original roots
    assert verify_bundle(restored)['accounting'] == manifest['accounting']
    corrupt = tmp_path / 'corrupt'
    shutil.copytree(bundle, corrupt)
    with closing(sqlite3.connect(corrupt / 'state.sqlite3')) as db:
        row = db.execute("SELECT id, content FROM metrics_references WHERE kind='tariff' LIMIT 1").fetchone()
        db.execute('UPDATE metrics_references SET content=? WHERE id=?', (row[1] + ' ', row[0]))
        db.commit()
    reseal_database(corrupt)
    with pytest.raises(BackupError, match='accounting'):
        verify_bundle(corrupt)


def test_older_bundle_upgrade_is_an_explicit_new_copy(tmp_path, context, repository, migrated_database):
    port, _, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    path = db_path(migrated_database)
    clear_accounting(path)
    bundle = tmp_path / 'old'
    create_backup(path, bundle, artifact_roots=[port.artifact_root], writers_stopped=True)
    # Turn it into the exact shape a 0.1.8 release produced: schema 0027 and format 2.
    with closing(sqlite3.connect(bundle / 'state.sqlite3')) as db:
        db.execute('PRAGMA user_version=0')
    from my_harness.storage.migrate import _config
    command.downgrade(_config(f'sqlite:///{bundle / "state.sqlite3"}'), '0027_profile_proposals')
    with closing(sqlite3.connect(bundle / 'state.sqlite3')) as db:
        db.execute('PRAGMA user_version=4732210')
    manifest = json.loads((bundle / 'manifest.json').read_text())
    manifest.update(format=2, schema='0027_profile_proposals')
    manifest.pop('accounting')
    (bundle / 'manifest.json').write_text(json.dumps(manifest))
    reseal_database(bundle)
    originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.rglob('*') if p.is_file()}
    with pytest.raises(BackupError, match='backup-upgrade'):
        verify_bundle(bundle)
    upgraded = upgrade_bundle(bundle, tmp_path / 'upgraded')
    assert upgraded['format'] == 3 and upgraded['upgraded_from']['schema'] == '0027_profile_proposals'
    assert upgraded['files'] == manifest['files'] and upgraded['accounting']['usage_invocations'] == 0
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.rglob('*') if p.is_file()} == originals
    restore_backup(tmp_path / 'upgraded', tmp_path / 'consult')
    with pytest.raises(BackupError):
        upgrade_bundle(tmp_path / 'upgraded', tmp_path / 'twice')  # only older formats are upgraded


def test_a30_upgrade_from_0027_snapshots_first_and_neither_backfills_nor_reprices(tmp_path, context, repository,
                                                                                    migrated_database):
    from my_harness.storage.migrate import migrate_database
    flow(tmp_path, context, repository)[2].run_once()
    path = db_path(migrated_database)
    clear_accounting(path)
    repository.engine.dispose()
    command.downgrade(migrated_database[1], '0027_profile_proposals')
    def legacy_rows():
        with closing(sqlite3.connect(path)) as db:
            return {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in LEGACY_TABLES}
    before = legacy_rows()
    outcome = migrate_database(str(path), tmp_path / 'snapshots', writers_stopped=True)
    # The upgrade reaches the current head; 0029–0031 only add empty continuation, knowledge and command tables (P002).
    assert (outcome.action, outcome.previous, outcome.revision) == ('migrated', '0027_profile_proposals',
                                                                   '0031_domain_commands')
    assert outcome.snapshot is not None and outcome.snapshot.is_file()
    after = dump_rows(path)
    assert all(after[table] == [] for table in ACCOUNTING)  # migration never materializes or values history
    assert legacy_rows() == before
    with closing(sqlite3.connect(outcome.snapshot)) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0027_profile_proposals'
