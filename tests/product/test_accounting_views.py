"""P001-T004: bounded accounting aggregates and API over the T003 ledger (T001 A16/A18/A19/A25/A28–A30).

Synthetic ledger rows, temporary SQLite, the local CLI probe and the packaged pinned references only; no provider.
Run histories hold invalid JSON on purpose: no accounting read may decode them.
"""
import json
import shutil
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage import accounting
from my_harness.storage.accounting_views import AccountingViews
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.models import (
    ConfigurationOperationRow, ManagedAttemptRow, ManagedCommitRow, ManagedJobRow, ManagedRunRow, UsageCaptureRow,
    UsageInvocationRow, UsageValuationRow, ValuationCohortMemberRow, ValuationCohortRow,
)
from test_backup import db_path, dump_rows
from test_managed import VERSIONS, context, repository  # noqa: F401
from test_managed_api import client
from test_usage_accounting import priced_history

ROOT = '/synthetic/root-a'
NOW = '2026-10-28T10:00:00.000000+00:00'
SONNET = 'claude-sonnet-5-5'
GLOBAL = {'root': None, 'phase': None, 'task': None}
C1 = {'input_tokens': 100000, 'cache_read_tokens': 900000, 'cache_write_tokens': 20000, 'write_5m': 20000,
      'write_1h': 0, 'output_tokens': 10000, 'reasoning_tokens': None}
CLAUDE_USD = {'unit': 'USD', 'scheme': 'anthropic_api_usd', 'basis': 'api_usd', 'platform': 'anthropic_first_party',
              'product': 'claude_api'}
CODEX_CREDIT = {'unit': 'chatgpt_work_codex_credit', 'scheme': 'chatgpt_work_codex_credit', 'basis': 'token_credit',
                'platform': 'openai_first_party', 'product': 'work_codex'}
EQUIVALENT = {**CLAUDE_USD, 'basis': 'subscription_equivalent', 'counterfactual': True}


class Ledger:
    """Minimal native rows and accounting records; every value is synthetic."""

    def __init__(self, session):
        self.session = session
        accounting.store_bundle(session, accounting.packaged(), source='packaged', now=NOW)

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row

    def run(self, task='P001-T001', *, phase='P001', root=ROOT, purpose='task', created=NOW):
        return self.add(ManagedRunRow(id=str(uuid4()), root=root, task_id=task, phase_id=phase, context_json='{}',
                                      versions_json='{}', history_json='{not json', status='COMPLETED', stage='DONE',
                                      revisions=0, revision_limit=1, version=1, created_at=created, updated_at=created,
                                      purpose=purpose)).id

    def call(self, run, role, *, provider='claude', model=SONNET, launch='observed', started=NOW, basis='api_usd',
             purpose=None):
        """A managed attempt and its expected invocation (no capture yet)."""
        number = 1 + self.session.query(ManagedAttemptRow).filter_by(run_id=run).count()
        attempt = self.add(ManagedAttemptRow(id=str(uuid4()), run_id=run, number=number,
                                             request_json=json.dumps({'role': role}), versions_json='{}',
                                             status='COMPLETED', result_json='{}', started_at=started,
                                             finished_at=started))
        native = self.session.get(ManagedRunRow, run)
        agent = accounting.agent_of(role)
        return self.add(UsageInvocationRow(
            id=accounting.key('managed_attempt', attempt.id), source_kind='managed_attempt', source_id=attempt.id,
            attempt_id=attempt.id, run_id=run, request_id=attempt.id, root=native.root, phase_code=native.phase_id,
            task_id=native.task_id, purpose=purpose or native.purpose, role=role, agent=agent, requested_model=model,
            versions={f'{agent}_provider': provider}, binding={'profile': {'basis': basis}} if basis else None,
            launch=launch, started_at=started, finished_at=started, recorded_at=started, updated_at=started))

    def assistance(self, *, started=NOW):
        operation = self.add(ConfigurationOperationRow(
            id=str(uuid4()), format='configuration-operation-1', kind='ASSIST', status='APPLIED',
            idempotency_key=str(uuid4()), request_sha256='0' * 64, payload={}, created_at=started, updated_at=started))
        return self.add(UsageInvocationRow(
            id=accounting.key('configuration_assistance', operation.id), source_kind='configuration_assistance',
            source_id=operation.id, operation_id=operation.id, purpose='configuration_assistance',
            role='configuration', agent='reviewer', versions={'reviewer_provider': 'claude'}, binding=None,
            launch='observed', started_at=started, finished_at=started, recorded_at=started, updated_at=started))

    def capture(self, invocation, components=None, *, coverage='complete', wall_ms=2000, version='usage-capture-1'):
        components = [{'key': 'invocation', 'reported_model': SONNET, 'semantics': 'claude-cli-1', **C1}] \
            if components is None else components
        evidence = None if version != 'usage-capture-1' else {
            'format': 'usage-accounting-1', 'coverage': coverage, 'components': components, 'reasons': [],
            'partition': 'single' if len(components) < 2 else 'disjoint', 'delegation': 'none',
            'charges_complete': True}
        return self.add(UsageCaptureRow(invocation_id=invocation.id, version=version, digest=uuid4().hex * 2,
                                        document={'format': version, 'client': {'provider': 'claude'},
                                                  'timing': {'wall_ms': wall_ms}},
                                        evidence=evidence, evidence_digest=None, source='capture', recorded_at=NOW))

    def value(self, invocation, capture, *, status='complete', amount=None, known=None, origin='admission',
              reasons=(), recorded=NOW, bucket=None, discrepancy=None):
        bucket = {**CLAUDE_USD, **(bucket or {})}
        known = known if known is not None else amount
        return self.add(UsageValuationRow(
            id=uuid4().hex * 2, invocation_id=invocation.id, capture_id=capture.id, origin=origin,
            normalization='usage-accounting-1', calculator='valuation-1', profile_digest='1' * 64,
            reference_set_digest=accounting.packaged().id, basis=bucket['basis'], scenario_digest=uuid4().hex * 2,
            evidence_digest='2' * 64, scenario={'platform': bucket['platform'], 'product': bucket['product']},
            status=status, unit=bucket['unit'], scheme=bucket['scheme'], amount=amount if status == 'complete' else None,
            known_subtotal=known, exact_sum=known, rounding_adjustment='0', counterfactual=bucket.get('counterfactual', False),
            retrospective=False, reasons=list(reasons), warnings=[], selected_components=['invocation'],
            discrepancy={'status': discrepancy} if discrepancy else None, recorded_at=recorded))

    def priced(self, run, role, amount, **kwargs):
        bucket = kwargs.pop('bucket', None)
        invocation = self.call(run, role, **kwargs)
        return self.value(invocation, self.capture(invocation), amount=amount, bucket=bucket)

    def commit(self, run, status='COMMITTED'):
        job = self.add(ManagedJobRow(idempotency_key=str(uuid4()), run_id=run, request_json='{}', status='SUCCEEDED',
                                     created_at=NOW))
        self.add(ManagedCommitRow(operation_id=str(uuid4()), run_id=run, job_id=job.id, status=status,
                                  base_revision='a', reviewed_fingerprint='b', expected_tree='c', expected_commit='d',
                                  intent_json='{}', created_at=NOW, finished_at=NOW))


@pytest.fixture
def ledger(repository):
    with Session(repository.engine) as session:
        yield Ledger(session)


def views(repository):
    return AccountingViews(repository.engine)


def every(page_function):
    items, offset = [], 0
    while offset is not None:
        page = page_function(offset)
        items += page['items']
        offset = page['next_offset']
    return items


# --- coverage and compatible amounts -------------------------------------------------------------


def test_a28_partial_and_absent_calls_leave_only_a_known_subtotal(repository, ledger):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.440000000000')
    partial = ledger.call(run, 'reviewer')
    ledger.value(partial, ledger.capture(partial, coverage='partial'), status='incomplete', known='0.100000000000',
                 reasons=['terminal_missing'])
    ledger.call(run, 'reviewer', launch='unknown_execution')  # expected, no capture: never zero
    ledger.call(run, 'executor', launch='not_invoked')  # positive no-launch evidence: excluded
    ledger.session.commit()
    summary = views(repository).summary(GLOBAL)
    coverage = summary['coverage']
    assert (coverage['invocations'], coverage['expected'], coverage['captured']) == (4, 3, 2)
    assert coverage['launch'] == {'pending': 0, 'not_invoked': 1, 'observed': 2, 'unknown_execution': 1}
    assert coverage['usage'] == {'complete': 1, 'partial': 1, 'absent': 1}
    assert coverage['valuation'] == {'complete': 1, 'incomplete': 1, 'unsupported': 0, 'unpriced': 1}
    assert coverage['unpriced_reasons'] == {'capture_unavailable': 1} and coverage['full_scope_priced'] is False
    [bucket] = summary['amounts']
    assert (bucket['amount'], bucket['known_subtotal']) == (None, '0.540000000000')
    assert (bucket['complete'], bucket['incomplete'], bucket['denominator']) == (1, 1, 3)
    assert bucket['reasons'] == {'terminal_missing': 1}
    assert summary['selection'] == {'policy': 'admission', 'cohort': None, 'complete': True}
    # Tokens: the partial subtotal is labelled; nothing is filled with zero.
    assert summary['tokens']['output_tokens'] == {'sum': 20000, 'invocations': 2, 'partial': 1}
    assert summary['tokens']['reasoning_tokens'] == {'sum': None, 'invocations': 0, 'partial': 0}


def test_a25_buckets_only_add_identical_unit_scheme_and_basis(repository, ledger):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.440000000000')
    ledger.priced(run, 'executor', '0.030000000001')
    ledger.priced(run, 'planner', '9.750000000000', provider='codex', model='gpt-sol', bucket=CODEX_CREDIT)
    ledger.priced(run, 'reviewer', '0.440000000000', bucket=EQUIVALENT)
    ledger.session.commit()
    summary = views(repository).summary(GLOBAL)
    assert summary['coverage']['full_scope_priced'] is True
    amounts = {(b['unit'], b['basis'], b['counterfactual']): b['amount'] for b in summary['amounts']}
    assert amounts == {('USD', 'api_usd', False): '0.470000000001',
                       ('USD', 'subscription_equivalent', True): '0.440000000000',
                       ('chatgpt_work_codex_credit', 'token_credit', False): '9.750000000000'}


def test_unpriced_invocations_name_their_reason_and_block_every_full_amount(repository, ledger):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.440000000000')
    unbound = ledger.call(run, 'reviewer', basis=None)
    ledger.capture(unbound)
    legacy = ledger.call(run, 'reviewer')
    ledger.capture(legacy, version='legacy-metrics-1')
    assistance = ledger.assistance()
    ledger.capture(assistance)
    ledger.session.commit()
    summary = views(repository).summary(GLOBAL)
    assert summary['coverage']['unpriced_reasons'] == {'billing_profile_unknown': 2, 'legacy_evidence': 1}
    assert summary['coverage']['usage'] == {'complete': 3, 'partial': 0, 'absent': 1}
    assert [(b['amount'], b['known_subtotal']) for b in summary['amounts']] == [(None, '0.440000000000')]
    page = views(repository).invocations(GLOBAL, 0, 10)
    reasons = {item['source_kind'] + ':' + item['role']: item['unpriced_reason'] for item in page['items']}
    assert reasons['configuration_assistance:configuration'] == 'billing_profile_unknown'
    legacy_item = next(i for i in page['items'] if i['id'] == legacy.id)
    assert legacy_item['usage']['reasons'] == ['legacy_evidence'] and legacy_item['usage']['coverage'] == 'absent'
    # A19: assistance is global setup work with no invented project or phase.
    setup = views(repository).groups(GLOBAL, 'work', 0, 10)
    assert {(g['key'], g['coverage']['invocations']) for g in setup['items']} == {('task_first_pass', 3), ('setup', 1)}
    assert next(g for g in setup['items'] if g['key'] == 'setup')['root'] is None


# --- dimensions, models and pagination ---------------------------------------------------------


def test_a16_a29_mixed_and_unknown_models_are_visible_groups_counted_once(repository, ledger):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.440000000000')
    mixed = ledger.call(run, 'executor')
    half = {**C1, 'input_tokens': 50000, 'output_tokens': 5000}
    ledger.value(mixed, ledger.capture(mixed, [
        {'key': 'model:a', 'reported_model': SONNET, 'semantics': 'claude-cli-1', **half},
        {'key': 'model:b', 'reported_model': 'claude-haiku-5-5', 'semantics': 'claude-cli-1', **half}]),
        amount='0.300000000000')
    unknown = ledger.call(run, 'planner', provider='codex', model='gpt-sol', basis=None)
    ledger.capture(unknown, [{'key': 'invocation', 'reported_model': None, 'semantics': 'codex-cli-1',
                              'input_tokens': 1000, 'cache_read_tokens': 900, 'cache_write_tokens': None,
                              'output_tokens': 10, 'reasoning_tokens': 3}])
    ledger.session.commit()
    total = views(repository).summary(GLOBAL)
    assert total['tokens']['output_tokens']['sum'] == 10000 + 10000 + 10
    assert total['tokens']['uncached_input_tokens']['sum'] == 100000 + 100000 + 100  # Codex input includes reads
    for dimension in ('effective_model', 'requested_model', 'provider', 'role', 'day', 'task', 'launch'):
        groups = every(lambda offset: views(repository).groups(GLOBAL, dimension, offset, 1))
        assert sum(g['coverage']['invocations'] for g in groups) == 3
        assert sum(g['tokens']['output_tokens']['sum'] or 0 for g in groups) == 20010
    models = {(g['key_kind'], g['key']): g for g in views(repository).groups(GLOBAL, 'effective_model', 0, 10)['items']}
    assert set(models) == {('reported', SONNET), ('mixed', None), ('unknown', None)}
    assert models[('mixed', None)]['tokens']['output_tokens']['sum'] == 10000  # the partition, added once
    requested = {g['key'] for g in views(repository).groups(GLOBAL, 'requested_model', 0, 10)['items']}
    assert requested == {SONNET, 'gpt-sol'}  # requested never becomes effective
    tasks = views(repository).groups(GLOBAL, 'task', 0, 10)['items']
    assert [(g['key'], g['root'], g['phase_code']) for g in tasks] == [('P001-T001', ROOT, 'P001')]
    by_key = views(repository).groups(GLOBAL, 'role', 0, 10, order='key')['items']
    assert [g['key'] for g in by_key] == ['planner', 'executor']
    with pytest.raises(ValueError):
        views(repository).groups(GLOBAL, 'quota', 0, 10)
    with pytest.raises(ValueError):
        views(repository).summary({**GLOBAL, 'colour': 'blue'})


def test_a29_utc_start_boundaries_and_stable_invocation_pages(repository, ledger):
    run = ledger.run()
    late = ledger.call(run, 'executor', started='2026-10-27T23:59:59.999999+00:00')
    early = ledger.call(run, 'reviewer', started='2026-10-28T00:00:00.000000+00:00')
    ledger.call(run, 'executor', started='2026-10-28T12:00:00.000000+00:00')
    ledger.session.commit()
    days = views(repository).groups(GLOBAL, 'day', 0, 10, order='key')['items']
    assert [(g['key'], g['coverage']['invocations']) for g in days] == [('2026-10-28', 2), ('2026-10-27', 1)]
    window = {**GLOBAL, 'started_from': '2026-10-28T00:00:00.000000+00:00',
              'started_before': '2026-10-28T12:00:00.000000+00:00'}
    assert [i['id'] for i in views(repository).invocations(window, 0, 10)['items']] == [early.id]
    pages = every(lambda offset: views(repository).invocations(GLOBAL, offset, 2))
    assert [i['id'] for i in pages][:2] == [late.id, early.id] and len(pages) == 3


# --- task work, retries and indicators ---------------------------------------------------------


def test_task_work_rework_and_cost_per_committed_task(repository, ledger):
    first = ledger.run('P001-T001')
    ledger.priced(first, 'planner', '0.100000000000')
    ledger.priced(first, 'executor', '0.200000000000')
    ledger.priced(first, 'reviewer', '0.100000000000')
    ledger.priced(first, 'executor', '0.300000000000')  # second execution of the run: a revision
    ledger.priced(first, 'reviewer', '0.100000000000')
    ledger.commit(first)
    failed = ledger.run('P001-T002', created='2026-10-28T09:00:00.000000+00:00')
    ledger.priced(failed, 'executor', '0.500000000000')
    retry = ledger.run('P001-T002', created='2026-10-28T11:00:00.000000+00:00')
    ledger.priced(retry, 'executor', '0.400000000000')  # a new harness run of the task: a retry
    chat = ledger.run('chat', purpose='chat')
    ledger.priced(chat, 'chat', '9.000000000000')
    unresolved = ledger.run('P002-T001', phase='P002')
    ledger.priced(unresolved, 'executor', '0.100000000000')
    ledger.commit(unresolved, 'INTENT')
    ledger.session.commit()
    project = {'root': ROOT, 'phase': None, 'task': None}
    work = {g['key']: g['coverage']['invocations'] for g in views(repository).groups(project, 'work', 0, 10)['items']}
    assert work == {'task_first_pass': 5, 'task_rework': 3, 'conversation': 1}
    phase = {'root': ROOT, 'phase': 'P001', 'task': None}
    summary = views(repository).summary(phase)
    assert summary['filters']['work'] == ['task_first_pass', 'task_rework', 'phase', 'other']
    assert summary['coverage']['invocations'] == 7  # chat and other phases excluded by default
    report = views(repository).tasks(phase)
    assert report['tasks'] == {'attempted': 2, 'committed': 1, 'acceptance_unknown': 0, 'not_committed': 1}
    [indicator] = report['indicators']
    assert indicator['total'] == {'amount': '1.700000000000', 'known_subtotal': '1.700000000000'}
    assert indicator['committed_work'] == {'amount': '0.800000000000', 'known_subtotal': '0.800000000000'}
    assert indicator['per_committed_task'] == '1.700000000000'  # failed retries are overhead of accepted work
    assert indicator['per_attempted_task'] == '0.850000000000'
    assert indicator['committed_work_per_committed_task'] == '0.800000000000'
    everything = views(repository).tasks(project)
    assert everything['tasks']['acceptance_unknown'] == 1
    [indicator] = everything['indicators']
    assert indicator['per_committed_task'] is None and indicator['per_attempted_task'] == '0.600000000000'
    none = views(repository).tasks({**project, 'work': ['conversation']})
    assert none['tasks']['attempted'] == 0 and none['indicators'] == []


def test_indicators_need_a_fully_priced_scope(repository, ledger):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.200000000000')
    ledger.call(run, 'reviewer')  # no capture
    ledger.commit(run)
    ledger.session.commit()
    [indicator] = views(repository).tasks({'root': ROOT, 'phase': None, 'task': None})['indicators']
    assert indicator['total'] == {'amount': None, 'known_subtotal': '0.200000000000'}
    assert indicator['per_committed_task'] is None and indicator['per_attempted_task'] is None


def test_cache_hit_and_wall_throughput_use_explicit_denominators(repository, ledger):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.440000000000')
    partial = ledger.call(run, 'executor')
    ledger.capture(partial, coverage='partial')
    codex = ledger.call(run, 'planner', provider='codex')
    ledger.capture(codex, [{'key': 'invocation', 'reported_model': 'gpt-sol', 'semantics': 'codex-cli-1',
                            'input_tokens': 1000, 'cache_read_tokens': 900, 'cache_write_tokens': None,
                            'output_tokens': 10}], wall_ms=0)
    ledger.session.commit()
    summary = views(repository).summary(GLOBAL)
    assert summary['cache_hit'] == {'cache_read_tokens': 900000, 'input_tokens': 1020000, 'invocations': 1,
                                    'excluded': 2, 'ratio': 900000 / 1020000}
    assert summary['wall_throughput'] == {'output_tokens': 10000, 'wall_ms': 2000, 'invocations': 1, 'excluded': 2,
                                          'output_tokens_per_wall_second': 5000.0}


# --- selection policy --------------------------------------------------------------------------


def test_cohort_selection_counts_members_once_and_building_cohorts_have_no_full_amount(repository, ledger):
    run = ledger.run()
    first = ledger.call(run, 'executor')
    capture = ledger.capture(first)
    ledger.value(first, capture, amount='0.440000000000')  # original admission valuation
    repriced = ledger.value(first, capture, amount='0.500000000000', origin='repricing')
    second = ledger.call(run, 'executor')
    ledger.capture(second)
    outside = ledger.call(run, 'reviewer')
    ledger.value(outside, ledger.capture(outside), amount='0.100000000000')
    cohort = ledger.add(ValuationCohortRow(
        id=str(uuid4()), name='retrospective', kind='repricing', idempotency_key='k', request_sha256='0' * 64,
        selection={}, selection_digest='3' * 64, scenario={'profile': {'basis': 'api_usd'}, 'retrospective': True},
        status='CLOSED', expected=2, built=2, created_at=NOW, closed_at=NOW))
    ledger.add(ValuationCohortMemberRow(cohort_id=cohort.id, invocation_id=first.id, basis='api_usd',
                                        valuation_id=repriced.id, recorded_at=NOW))
    ledger.add(ValuationCohortMemberRow(cohort_id=cohort.id, invocation_id=second.id, basis='api_usd',
                                        reason='reference_missing', recorded_at=NOW))
    ledger.session.commit()
    admission = views(repository).summary(GLOBAL)
    assert admission['amounts'][0]['known_subtotal'] == '0.540000000000'  # never the later repricing
    chosen = views(repository).summary(GLOBAL, cohort='retrospective')
    assert chosen['selection']['cohort']['name'] == 'retrospective' and chosen['selection']['complete'] is True
    assert chosen['coverage']['invocations'] == 2 and chosen['coverage']['outside_selection'] == 1
    assert chosen['coverage']['unpriced_reasons'] == {'reference_missing': 1}
    assert [(b['amount'], b['known_subtotal']) for b in chosen['amounts']] == [(None, '0.500000000000')]
    listed = views(repository).invocations(GLOBAL, 0, 10, cohort=cohort.id)['items']
    assert {i['id']: i['in_selection'] for i in listed} == {first.id: True, second.id: True, outside.id: False}
    assert next(i for i in listed if i['id'] == first.id)['valuations'][0]['amount'] == '0.500000000000'
    with Session(repository.engine) as session, session.begin():
        session.get(ValuationCohortRow, cohort.id).status = 'BUILDING'
        session.get(ValuationCohortMemberRow, (cohort.id, second.id, 'api_usd')).reason = None
        session.get(ValuationCohortMemberRow, (cohort.id, second.id, 'api_usd')).valuation_id = repriced.id
    building = views(repository).summary(GLOBAL, cohort='retrospective')
    assert building['selection']['complete'] is False and building['coverage']['full_scope_priced'] is False
    assert [(b['amount'], b['known_subtotal']) for b in building['amounts']] == [(None, '1.000000000000')]
    with pytest.raises(LookupError):
        views(repository).summary(GLOBAL, cohort='missing')
    assert [c['name'] for c in views(repository).cohorts(0, 10)['items']] == ['retrospective']


def test_a30_reads_never_write_or_decode_histories(repository, ledger, migrated_database):
    run = ledger.run()
    ledger.priced(run, 'executor', '0.440000000000')
    ledger.session.commit()
    before = dump_rows(db_path(migrated_database))
    reader = views(repository)
    reader.summary(GLOBAL), reader.tasks(GLOBAL), reader.invocations(GLOBAL, 0, 5), reader.cohorts(0, 5)
    for dimension in ('work', 'effective_model', 'phase'):
        reader.groups(GLOBAL, dimension, 0, 5)
    item = reader.invocations(GLOBAL, 0, 1)['items'][0]
    reader.invocation(item['id']), reader.valuations(item['id'], 0, 5)
    assert dump_rows(db_path(migrated_database)) == before
    with pytest.raises(LookupError):
        reader.invocation('managed_attempt:missing')


# --- integrated ledger, HTTP and restored archive ------------------------------------------------


def test_real_ledger_details_api_and_restored_archive(tmp_path, context, repository, migrated_database):
    port = priced_history(tmp_path, context, repository)
    reader = views(repository)
    admission = reader.summary(GLOBAL)
    assert admission['coverage']['expected'] == 3
    assert admission['coverage']['unpriced_reasons'] == {'billing_profile_unknown': 3} and admission['amounts'] == []
    cohort = reader.summary(GLOBAL, cohort='archive')
    assert cohort['coverage']['outside_selection'] == 2  # Codex planner/reviewer: another provider's profile
    [bucket] = cohort['amounts']
    assert (bucket['unit'], bucket['retrospective'], bucket['amount']) == ('USD', True, '0.440000000000')
    executor = next(i for i in reader.invocations(GLOBAL, 0, 10, cohort='archive')['items'] if i['in_selection'])
    assert executor['provider'] == 'claude' and executor['effective_model_kind'] == 'reported'
    detail = reader.invocation(executor['id'])
    assert detail['captures'] == 2 and {c['grain'] for c in detail['components']} >= {'invocation_total', 'request'}
    assert 'argv' not in json.dumps(detail['capture_document'])
    [valuation] = reader.valuations(executor['id'], 0, 5)['items']
    assert valuation['cohorts'][0]['name'] == 'archive' and valuation['lines']
    assert {ref['kind'] for ref in valuation['references']} >= {'tariff'}
    configuration = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),))
    with client(str(repository.engine.url), tmp_path, configuration) as http:
        summary = http.get('/api/managed/accounting/summary', params={'cohort': 'archive'})
        assert summary.status_code == 200, summary.text
        assert summary.json()['amounts'][0]['amount'] == '0.440000000000'
        scoped = http.get('/api/managed/accounting/summary', params={'project_id': 'synthetic', 'phase': 'P001'})
        assert scoped.json()['filters']['work'] == ['task_first_pass', 'task_rework', 'phase', 'other']
        groups = http.get('/api/managed/accounting/groups', params={'dimension': 'provider', 'work': ['task_first_pass',
                                                                                                    'task_rework']})
        assert {g['key'] for g in groups.json()['items']} == {'claude', 'codex'}
        page = http.get('/api/managed/accounting/invocations', params={'limit': 1})
        assert len(page.json()['items']) == 1 and page.json()['next_offset'] == 1
        assert http.get(f"/api/managed/accounting/invocations/{executor['id']}").status_code == 200
        lines = http.get(f"/api/managed/accounting/invocations/{executor['id']}/valuations")
        assert lines.json()['items'][0]['lines'][0]['exact_amount']
        assert http.get('/api/managed/accounting/tasks').status_code == 200
        assert http.get('/api/managed/accounting/cohorts').json()['items'][0]['status'] == 'CLOSED'
        window = http.get('/api/managed/accounting/invocations', params={'started_from': '2026-10-28T00:00:00+02:00'})
        assert window.json()['filters']['started_from'] == '2026-10-27T22:00:00.000000+00:00'
        assert http.get('/api/managed/accounting/summary', params={'started_from': '2026-10-28T00:00:00'}).status_code == 422
        assert http.get('/api/managed/accounting/summary', params={'phase': 'P001'}).status_code == 422
        assert http.get('/api/managed/accounting/summary', params={'cohort': 'missing'}).status_code == 404
        assert http.get('/api/managed/accounting/groups', params={'dimension': 'quota'}).status_code == 422
        assert http.get('/api/managed/accounting/invocations/managed_attempt:none').status_code == 404
        assert http.post('/api/managed/accounting/summary').status_code == 405
    bundle, restored = tmp_path / 'bundle', tmp_path / 'restored'
    create_backup(db_path(migrated_database), bundle, artifact_roots=[port.artifact_root], writers_stopped=True)
    restore_backup(bundle, restored)
    shutil.rmtree(port.artifact_root)  # consultation needs no original roots
    engine = make_engine(f'sqlite:///{restored / "state.sqlite3"}')
    try:
        archived = AccountingViews(engine).summary(GLOBAL, cohort='archive')
        assert archived['amounts'] == cohort['amounts'] and archived['coverage'] == cohort['coverage']
    finally:
        engine.dispose()
