"""P001-T006: one synthetic journey across the whole accounting chain (T001 A30/A31, with A28/A29 read back).

Capture through the real adapter and the local CLI probe → native records → an explicit repricing valuation →
aggregates over HTTP → stream retention → format-3 backup → query-only restore served over HTTP without the
original artifact root. Temporary Git/SQLite and the packaged pinned references only; no provider, network or
private data. Each stage reads the same HTTP contracts the accounting page consumes.
"""
import hashlib
from pathlib import Path
import shutil

import pytest

from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage import accounting_operations as operations
from my_harness.storage.backup import create_backup, restore_backup, verify_bundle
from my_harness.storage.database import make_engine
from my_harness.storage.retention import apply_retention, preview_retention
from test_backup import db_path, dump_rows
from test_managed import VERSIONS, context, repository  # noqa: F401
from test_managed_api import client
from test_usage_accounting import ACCOUNTING, CLAUDE_API, LEGACY_TABLES, c1_capture
from test_metrics import flow

LEGACY = ('/api/managed/metrics/summary', '/api/managed/metrics/groups?dimension=provider',
          '/api/managed/metrics/models', '/api/managed/metrics/tasks')
WORK = {'work': ['task_first_pass', 'task_rework']}


def legacy_reads(http, run_id):
    reads = {path: http.get(path) for path in (*LEGACY, f'/api/managed/runs/{run_id}/attempts')}
    assert all(response.status_code == 200 for response in reads.values()), reads
    return {path: response.json() for path, response in reads.items()}


def accounting_reads(http, executor):
    """Every accounting surface of the page, for the cohort and the default admission policy."""
    paths = {
        'admission': ('/api/managed/accounting/summary', {}),
        'cohort': ('/api/managed/accounting/summary', {'cohort': 'archive'}),
        'providers': ('/api/managed/accounting/groups', {'dimension': 'provider', 'cohort': 'archive', **WORK}),
        'models': ('/api/managed/accounting/groups', {'dimension': 'effective_model', 'cohort': 'archive'}),
        'requested': ('/api/managed/accounting/groups', {'dimension': 'requested_model', 'cohort': 'archive'}),
        'tasks': ('/api/managed/accounting/tasks', {'cohort': 'archive'}),
        'invocations': ('/api/managed/accounting/invocations', {'cohort': 'archive', 'limit': 10}),
        'detail': (f'/api/managed/accounting/invocations/{executor}', {}),
        'valuations': (f'/api/managed/accounting/invocations/{executor}/valuations', {}),
        'cohorts': ('/api/managed/accounting/cohorts', {}),
        'references': ('/api/managed/configuration/references', {}),
    }
    reads = {name: http.get(path, params=params) for name, (path, params) in paths.items()}
    assert all(response.status_code == 200 for response in reads.values()), {
        name: response.text for name, response in reads.items() if response.status_code != 200}
    return {name: response.json() for name, response in reads.items()}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_capture_valuation_api_retention_backup_and_query_only_restore(tmp_path, context, repository,
                                                                       migrated_database):
    path = db_path(migrated_database)
    live = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),))
    port, job, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()  # Codex planner and reviewer, Claude executor: three native invocations
    with client(str(repository.engine.url), tmp_path, live) as http:
        legacy = legacy_reads(http, job.run_id)
    legacy_rows = {table: rows for table, rows in dump_rows(path).items() if table in LEGACY_TABLES}

    # Records → valuation: changed evidence is appended, then an explicit previewed repricing cohort prices it.
    executor = c1_capture(repository)
    kwargs = dict(profile=CLAUDE_API, retrospective=True, filters={})
    preview = operations.reprice_preview(repository.engine, name='archive', **kwargs)
    report = operations.reprice(repository.engine, name='archive', preview_sha256=preview['sha256'], key='q1',
                                **kwargs)
    assert (report['status'], report['valuations']) == ('CLOSED', {'complete': 1})
    after_operations = dump_rows(path)
    assert {table: after_operations[table] for table in LEGACY_TABLES} == legacy_rows  # A30: history untouched

    # Aggregates/API: coverage, one compatible bucket, distinct provider/effective/requested models, details.
    with client(str(repository.engine.url), tmp_path, live) as http:
        assert legacy_reads(http, job.run_id) == legacy  # old contracts answer as before the accounting work
        reads = accounting_reads(http, executor)
    assert dump_rows(path) == after_operations  # reads never write or recalculate
    admission, cohort = reads['admission'], reads['cohort']
    assert admission['amounts'] == [] and admission['coverage']['expected'] == 3
    assert admission['coverage']['unpriced_reasons'] == {'billing_profile_unknown': 3}  # unknown, never zero
    assert (cohort['coverage']['expected'], cohort['coverage']['outside_selection']) == (1, 2)
    [bucket] = cohort['amounts']
    assert (bucket['unit'], bucket['basis'], bucket['retrospective'], bucket['amount']) == (
        'USD', 'api_usd', True, '0.440000000000')
    assert {group['key'] for group in reads['providers']['items']} == {'claude', 'codex'}
    requested = {group['key'] for group in reads['requested']['items']}
    assert 'synthetic-executor' in requested  # a requested model never becomes the effective one (A20)
    assert not requested & {group['key'] for group in reads['models']['items']}
    [valuation] = reads['valuations']['items']
    assert valuation['cohorts'][0]['name'] == 'archive' and valuation['warnings'] == ['effective_period_unknown']
    assert sum(line['quantity'] for line in valuation['lines']) == 100000 + 900000 + 20000 + 10000
    assert reads['detail']['captures'] == 2 and 'argv' not in str(reads['detail']['capture_document'])
    assert [item['source'] for item in reads['references']['items']] == ['packaged']

    # Retention removes stream bytes only; every accounting fact and answer stays the same.
    options = dict(artifact_roots=[port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
    shown = preview_retention(path, **options)
    retired = [Path(item['source']) for item in shown['items'] if item['eligible']]
    assert retired and all(source.exists() for source in retired)
    apply_retention(path, **options, preview_sha256=shown['preview_sha256'], reason='Synthetic qualification',
                    confirmed=True, writers_stopped=True)
    assert not any(source.exists() for source in retired)
    retained = dump_rows(path)
    assert all(retained[table] == after_operations[table] for table in ACCOUNTING)
    with client(str(repository.engine.url), tmp_path, live) as http:
        assert accounting_reads(http, executor) == reads

    # Format-3 backup → query-only restore, consulted without the original artifact root or a managed project.
    bundle, restored = tmp_path / 'bundle', tmp_path / 'restored'
    manifest = create_backup(path, bundle, artifact_roots=[port.artifact_root], writers_stopped=True)
    assert manifest['format'] == 3 and manifest['accounting']['usage_valuations'] == 1
    restore_backup(bundle, restored)
    shutil.rmtree(port.artifact_root)
    archive = restored / 'state.sqlite3'
    before = (sha256(archive), dump_rows(archive))
    with client(f'sqlite:///{archive}', tmp_path, None) as http:
        assert accounting_reads(http, executor) == reads
        refused = [http.post('/api/managed/configuration/references/preview', json={'content': '{}'}),
                   http.post(f'/api/managed/runs/{job.run_id}/actions',
                             json={'action': 'commit', 'expected_version': 0}, headers={'Idempotency-Key': 'q'})]
        assert [(r.status_code, r.json()['code']) for r in refused] == [(409, 'restored_read_only')] * 2
    assert (sha256(archive), dump_rows(archive)) == before
    assert verify_bundle(restored)['accounting'] == manifest['accounting']
    engine = make_engine(f'sqlite:///{archive}')
    try:
        with pytest.raises(operations.OperationRefused, match='restored_read_only'):
            operations.backfill_preview(engine, name='archive-backfill')
        with pytest.raises(operations.OperationRefused, match='restored_read_only'):
            operations.reprice_preview(engine, name='archive-2', **kwargs)
    finally:
        engine.dispose()
