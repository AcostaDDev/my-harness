"""H5.1: synthetic XML, safe paths and persisted provenance; no providers."""

import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

from session_client import TestClient
import pytest

from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.git import GitWorkspace
from my_harness.api.app import create_app
from my_harness.core.engine.context import Command, JUnitDeclaration
from my_harness.core.engine.contracts import context_snapshot
from my_harness.core.engine.junit import MAX_BYTES, MAX_CASES, capture_junit, observe_report, parse_junit
from my_harness.core.engine.serialization import dump_history, load_history, restore_context
from my_harness.core.engine.validation import CommandResult, run_validations
from my_harness.core.engine.workflow import OfflineEngine
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.managed_views import SQLiteManagedViews
from my_harness.storage.phases import PhaseRepository
from test_engine import context, PLAN, TASK_ID, PHASE_ID, edit, review
from test_git import repo as git_repo, make_context, IDENTITY, VERSIONS, git

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/junit'
COMMAND = Command(('test-runner', 'check'))
DECLARATION = JUnitDeclaration(COMMAND, 'ignored/junit.xml', 'Declared synthetic unit selection; no code coverage')


def configured(context, declaration=DECLARATION):
    return replace(context, profile=replace(context.profile, junit_reports=(declaration,)))


def simple_xml(count=1):
    return ('<testsuite name="Suite" tests="%s">%s</testsuite>' %
            (count, ''.join(f'<testcase name="case-{i}" />' for i in range(count)))).encode()


class ReportRunner:
    def __init__(self, data, result=CommandResult(0), path=DECLARATION.path):
        self.data, self.result, self.path = data, result, path
        self.calls = []

    def run(self, context, command):
        self.calls.append(command)
        if self.data is not None:
            path = context.path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.data)
        return self.result


def test_complete_report_preserves_observed_fields_bytes_and_stable_identity():
    data = (FIXTURES / 'complete.xml').read_bytes()
    report = parse_junit(data, DECLARATION)
    assert report.status == 'complete' and not report.diagnostics
    assert base64.b64decode(report.original_base64) == data
    assert report.sha256 == hashlib.sha256(data).hexdigest() and report.size_bytes == len(data)
    assert [case.result for case in report.cases] == ['passed', 'failed', 'error', 'skipped']
    passed, failed, error, skipped = report.cases
    assert passed.reported_id == 'observed-1' and passed.duration_seconds == 0
    assert error.duration_seconds is None and skipped.classname is None
    assert failed.suite == ('Synthetic & safe',) and failed.message == 'Expected <script>'
    assert failed.error == 'Observed failure & details' and error.error_type == 'RuntimeError'
    assert parse_junit(data, DECLARATION).cases == report.cases


def test_truncated_report_keeps_only_completed_observed_cases():
    data = (FIXTURES / 'partial.xml').read_bytes()
    report = parse_junit(data, DECLARATION)
    assert report.status == 'partial' and len(report.cases) == 1
    assert report.cases[0].name == 'completed' and report.diagnostics
    assert base64.b64decode(report.original_base64) == data


@pytest.mark.parametrize('data', [
    (FIXTURES / 'invalid.xml').read_bytes(), b'not xml', b'',
    b'<!DOCTYPE testsuite [<!ENTITY x SYSTEM "file:///etc/passwd">]><testsuite>&x;</testsuite>',
    '<!DOCTYPE testsuite [<!ENTITY x "expand">]><testsuite>&x;</testsuite>'.encode('utf-16'),
    b'<testsuites><properties><testcase name="wrong-parent" /></properties></testsuites>',
    b'<!DOCTYPE testsuite SYSTEM "https://example.invalid/external"><testsuite/>',
])
def test_invalid_and_active_xml_never_fabricates_cases_or_loads_entities(data):
    report = parse_junit(data, DECLARATION)
    assert report.status in ('invalid', 'partial') and report.diagnostics and not report.cases
    assert base64.b64decode(report.original_base64) == data


@pytest.mark.parametrize('attributes', ['time="nan"', 'time="-1"', 'time="infinity"', 'time="absent"',
                                      'status="notrun"', 'status="unexpected"'])
def test_invalid_duration_or_unobserved_execution_is_diagnosed(attributes):
    report = parse_junit(f'<testsuite><testcase name="case" {attributes}/></testsuite>'.encode(), DECLARATION)
    assert report.status == 'partial' and report.diagnostics
    assert report.cases[0].duration_seconds is None
    if 'status' in attributes:
        assert report.cases[0].result == 'unknown'


def test_missing_names_duplicate_cases_nested_suites_and_count_mismatch():
    report = parse_junit(b'<testsuites tests="5"><testsuite name="outer"><testsuite name="inner">'
                         b'<testcase name="same"/><testcase name="same"/><testcase/>'
                         b'</testsuite></testsuite></testsuites>', DECLARATION)
    assert report.status == 'partial' and len(report.cases) == 3
    assert report.cases[0].suite == ('outer', 'inner')
    assert len({case.id for case in report.cases}) == 3 and report.cases[-1].result == 'unknown'
    assert report.cases[-1].name is None and report.cases[-1].reported_id is None
    assert any('differs' in d for d in report.diagnostics)


def test_contradictory_or_unknown_markers_are_not_successes():
    for body in ('<failure/><skipped/>', '<unknown-result/>'):
        report = parse_junit(f'<testsuite><testcase name="case">{body}</testcase></testsuite>'.encode(), DECLARATION)
        assert report.status == 'partial' and report.cases[0].result == 'unknown'


def test_xml_limits_are_explicit_without_truncated_original_or_fabricated_cases():
    oversized = parse_junit(b'x' * (MAX_BYTES + 1), DECLARATION)
    assert oversized.status == 'limit' and oversized.original_base64 is None and oversized.sha256 is None
    for data in (b'<testsuite>' * 65 + b'</testsuite>' * 65, simple_xml(MAX_CASES + 1)):
        report = parse_junit(data, DECLARATION)
        assert report.status == 'invalid' and not report.cases and report.original_base64
        assert 'limit' in report.diagnostics[0]


@pytest.mark.parametrize('path', ['/tmp/external.xml', '../external.xml', 'folder/../../outside', r'folder\external', '.git/report.xml', '.'])
def test_declarations_cannot_select_external_or_git_paths(path):
    with pytest.raises(ValueError):
        JUnitDeclaration(COMMAND, path, 'Declared selection')


@pytest.mark.parametrize('kind', ['file-symlink', 'directory-symlink', 'fifo', 'directory', 'hardlink', 'oversized'])
def test_capture_does_not_read_external_links_or_special_files(context, tmp_path, kind):
    context = configured(context)
    external = tmp_path / 'external'
    external.mkdir()
    target = external / 'junit.xml'
    target.write_bytes(simple_xml())
    directory = context.root / 'ignored'
    path = directory / 'junit.xml'
    if kind == 'directory-symlink':
        directory.symlink_to(external, target_is_directory=True)
    else:
        directory.mkdir()
        if kind == 'file-symlink':
            path.symlink_to(target)
        elif kind == 'fifo':
            os.mkfifo(path)
        elif kind == 'directory':
            path.mkdir()
        elif kind == 'hardlink':
            os.link(target, path)
        else:
            with path.open('wb') as stream:
                stream.truncate(MAX_BYTES + 1)
    observation = observe_report(context, DECLARATION.path)
    assert observation.data is None and observation.status in ('unreadable', 'limit')
    assert target.read_bytes() == simple_xml()


def test_report_replaced_during_capture_is_not_attributed(context, monkeypatch):
    context = configured(context)
    path = context.path(DECLARATION.path)
    path.parent.mkdir()
    path.write_bytes(simple_xml())
    original_stat = os.stat

    def replaced(name, *args, **kwargs):
        if name == 'junit.xml' and kwargs.get('dir_fd') is not None:
            path.rename(path.with_suffix('.previous'))
            path.write_bytes(simple_xml(2))
        return original_stat(name, *args, **kwargs)

    monkeypatch.setattr(os, 'stat', replaced)
    observation = observe_report(context, DECLARATION.path)
    assert observation.status == 'unreadable' and observation.data is None


def test_freshness_missing_stale_and_identical_rewrite_are_observed(context):
    context = configured(context)
    evidence = SyntheticWorkspace(context, ('app/main.txt',)).capture(context)
    runner = ReportRunner(simple_xml())
    first = run_validations(context, {'validation_commands': []}, evidence, runner).entries[0].reports[0]
    assert first.status == 'complete' and first.freshness == 'created'
    path = context.path(DECLARATION.path)
    stale = run_validations(context, {'validation_commands': []}, evidence, ReportRunner(None)).entries[0].reports[0]
    assert stale.status == 'stale' and stale.freshness == 'unchanged' and stale.sha256 == first.sha256
    rewritten = run_validations(context, {'validation_commands': []}, evidence, runner).entries[0].reports[0]
    assert rewritten.sha256 == first.sha256 and rewritten.freshness == 'changed'
    path.unlink()
    missing = run_validations(context, {'validation_commands': []}, evidence, ReportRunner(None)).entries[0].reports[0]
    assert missing.status == 'missing' and missing.sha256 is None and missing.cases == ()


def test_exact_command_configuration_selects_reports_and_profile_snapshot_is_frozen(context):
    command = Command(COMMAND.argv, cwd='app', environment=(('MODE', 'tests'),), timeout_seconds=90)
    declaration = replace(DECLARATION, command=command)
    context = configured(replace(context, profile=replace(context.profile, validations=(command,))), declaration)
    evidence = SyntheticWorkspace(context, ('app/main.txt',)).capture(context)
    report = run_validations(context, {'validation_commands': ['test-runner check']}, evidence, ReportRunner(simple_xml()))
    assert len(report.entries) == 2 and not report.entries[0].reports and report.entries[1].reports
    snapshot = context_snapshot(context)
    assert restore_context(snapshot) == context
    changed = configured(context, replace(declaration, coverage='Another selection'))
    assert context_snapshot(changed) != snapshot and restore_context(snapshot) == context


@pytest.mark.parametrize('xml,exit_code', [(simple_xml(), 2), ((FIXTURES / 'partial.xml').read_bytes(), 0), (None, 0)])
def test_reports_do_not_replace_command_outcome_or_accept_without_review(context, xml, exit_code):
    context = configured(context)
    runner = ReportRunner(xml, CommandResult(exit_code, duration_seconds=4.0))
    agents = ScriptedAgentAdapter([edit(), review()])
    engine = OfflineEngine(agents, runner, SyntheticWorkspace(context, ('app/main.txt',)))
    history = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    validation = history.cycles[0].validation
    assert validation.run_id == history.id and validation.source_attempt_id == history.attempts[0].request.id
    assert validation.entries[0].result.exit_code == exit_code and validation.entries[0].result.duration_seconds == 4.0
    assert validation.all_passed == (exit_code == 0)
    assert history.acceptance.eligible == (exit_code == 0) and history.cycles[0].verdict == 'ACCEPT'
    assert json.loads(dump_history(history))['format'] == 6 and load_history(dump_history(history)) == history
    reviewer = agents.requests[-1]
    assert 'original_base64' not in reviewer.prompt
    # An invalid agent output is never turned into acceptance by JUnit.
    failed_engine = OfflineEngine(ScriptedAgentAdapter([edit(), {'bad': 'review'}]), runner,
                                  SyntheticWorkspace(context, ('app/main.txt',)))
    assert failed_engine.start(context, TASK_ID, PHASE_ID, PLAN).acceptance is None


def test_legacy_context_and_history_shapes_without_reports_remain_compatible(context):
    assert 'junit_reports' not in json.loads(context_snapshot(context))['profile']
    assert restore_context(context_snapshot(context)) == context
    engine = OfflineEngine(ScriptedAgentAdapter([edit(), review()]), ScriptedCommandRunner(),
                           SyntheticWorkspace(context, ('app/main.txt',)))
    history = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    snapshot = dump_history(history)
    serialized = json.loads(snapshot)
    assert serialized['format'] == 4
    # Prompt text is opaque: it may discuss reports without introducing JUnit fields into legacy entries.
    assert all('command_id' not in entry and 'reports' not in entry
               for cycle in serialized['history']['cycles'] for entry in cycle['validation']['entries'])
    assert load_history(snapshot) == history and dump_history(load_history(snapshot)) == snapshot


def managed_run(git_repo, migrated_database, data=simple_xml(55), result=CommandResult(0)):
    context = configured(make_context(git_repo))
    database = make_engine(migrated_database[0])
    repository = SQLiteManagedRepository(database)
    workspace = GitWorkspace(IDENTITY)
    runner = ReportRunner(data, result)
    agents = ScriptedAgentAdapter([edit(), review()])
    supervisor = LocalSupervisor(repository, lambda *_: (agents, runner, workspace), commit_factory=lambda *_: workspace)
    job = repository.submit(context, TASK_ID, PHASE_ID, PLAN, VERSIONS, key='junit-start')
    assert supervisor.run_once().status == 'DONE'
    return context, repository, supervisor, job, agents


def test_sqlite_api_pagination_original_download_restart_and_exact_commit(git_repo, migrated_database, tmp_path):
    context, repository, supervisor, job, agents = managed_run(git_repo, migrated_database)
    record = repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY'
    validation = record.history.cycles[0].validation
    entry = validation.entries[0]
    views = SQLiteManagedViews(repository.engine)
    summary = views.run(job.run_id)['history']['latest_cycle']['validation']
    assert summary['entries'][0]['reports'][0]['case_count'] == 55
    assert 'cases' not in summary['entries'][0]['reports'][0] and 'original_base64' not in json.dumps(summary)
    events = repository.events(job.run_id)
    command_ids = [e['payload']['command_id'] for e in events if e['kind'] == 'command_started']
    assert command_ids == [entry.command_id]
    original = context.path(DECLARATION.path).read_bytes()
    context.path(DECLARATION.path).write_bytes(b'<external>later changed bytes</external>')
    managed = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),))
    app = create_app(migrated_database[0], tmp_path / 'ui', managed=managed)
    prefix = f'/api/managed/runs/{job.run_id}/cycles/0/validations/0/reports/0'
    with TestClient(app, base_url='http://127.0.0.1:8013') as http:
        collected = []
        offset = 0
        while offset is not None:
            response = http.get(prefix, params={'offset': offset, 'limit': 17})
            assert response.status_code == 200, response.text
            page = response.json()
            collected += page['items']
            assert page['run_id'] == job.run_id and page['source_attempt_id'] == validation.source_attempt_id
            assert page['command_id'] == entry.command_id and page['evidence']['fingerprint'] == validation.evidence.fingerprint
            offset = page['next_offset']
        assert len(collected) == len({c['id'] for c in collected}) == 55
        assert all(c['duration_seconds'] is None for c in collected)
        download = http.get(prefix + '/original')
        assert download.content == original and download.headers['content-type'] == 'application/octet-stream'
        assert download.headers['x-content-type-options'] == 'nosniff'
        assert download.headers['etag'] == f'"{hashlib.sha256(original).hexdigest()}"'
        assert http.get(prefix, params={'limit': 101}).status_code == 422
        assert http.get(prefix.replace('/cycles/0/', '/cycles/-1/')).status_code == 404
        assert http.get(prefix, headers={'Host': 'external.invalid'}).status_code == 403
        detail = http.get(f'/api/managed/runs/{job.run_id}').json()
        assert detail['history']['latest_cycle']['validation'] == json.loads(json.dumps(summary))
    # Restarting and deleting the source file do not remove the imported evidence.
    context.path(DECLARATION.path).unlink()
    restarted = SQLiteManagedRepository(repository.engine)
    assert restarted.get_run(job.run_id).history == record.history
    assert SQLiteManagedViews(repository.engine).test_original(job.run_id, 0, 0, 0)[0] == original
    restarted.submit_commit(job.run_id, key='junit-commit', expected_version=record.version)
    assert supervisor.run_once().status == 'DONE'
    assert restarted.get_run(job.run_id).status == 'COMMITTED'
    assert git(context.root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD') == 'app/main.txt'
    assert len(agents.requests) == 2
    repository.engine.dispose()


def test_report_success_cannot_commit_failed_command_or_changed_content(git_repo, migrated_database):
    context, repository, supervisor, job, _ = managed_run(git_repo, migrated_database, result=CommandResult(1))
    record = repository.get_run(job.run_id)
    assert record.status == 'STOPPED' and not record.history.acceptance.eligible
    assert record.history.cycles[0].validation.entries[0].reports[0].cases[0].result == 'passed'
    with pytest.raises(Conflict):
        repository.submit_commit(job.run_id, key='failed-command', expected_version=record.version)
    repository.engine.dispose()


def test_changed_content_invalidates_commit_even_with_complete_junit(git_repo, migrated_database):
    context, repository, supervisor, job, _ = managed_run(git_repo, migrated_database)
    record = repository.get_run(job.run_id)
    context.path('app/main.txt').write_text('external edit\n')
    repository.submit_commit(job.run_id, key='external-change', expected_version=record.version)
    supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'STOPPED' and repository.commit_record(job.run_id) is None
    assert context.path('app/main.txt').read_text() == 'external edit\n'
    repository.engine.dispose()


def test_observed_report_failures_block_accept_without_replacing_successful_command(context):
    context = configured(context)
    runner = ReportRunner((FIXTURES / 'complete.xml').read_bytes(), CommandResult(0, stdout='Command succeeded'))
    engine = OfflineEngine(ScriptedAgentAdapter([edit(), review()]), runner,
                           SyntheticWorkspace(context, ('app/main.txt',)))
    history = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    entry = history.cycles[0].validation.entries[0]
    assert entry.result.passed and entry.result.exit_code == 0 and entry.result.stdout == 'Command succeeded'
    assert not history.cycles[0].validation.all_passed and not history.acceptance.eligible
    assert history.status == 'stopped' and entry.reports[0].status == 'complete'


def test_phase_baseline_report_is_preserved_in_the_check_run(git_repo, migrated_database):
    context = configured(make_context(git_repo))
    database = make_engine(migrated_database[0])
    repository = SQLiteManagedRepository(database)
    phases = PhaseRepository(repository)
    phase_id = phases.create(context, {'code': 'P001', 'objective': 'Synthetic phase', 'exit_criteria': ['Validated'],
                                       'tasks': [], 'documents': ['docs/STATE.md'], 'tag': None})
    workspace = GitWorkspace(IDENTITY)
    agents = ScriptedAgentAdapter([{'phase_id': 'P001', 'verdict': 'READY', 'summary': 'Observed synthetic result',
                                   'exit_criteria_results': [{'criterion': 'Validated', 'passed': True, 'evidence': 'Synthetic'}],
                                   'required_actions': [], 'blocking_questions': []}])
    runner = ReportRunner(simple_xml())
    supervisor = LocalSupervisor(repository, lambda *_: (agents, runner, workspace), commit_factory=lambda *_: workspace)
    job = phases.submit_check(context, phase_id, phases.get(phase_id)['version'], key='phase-junit', versions=VERSIONS)
    assert supervisor.run_once().status == 'DONE'
    record = repository.get_run(job.run_id)
    assert record.history.status == 'completed'
    report = record.history.cycles[0].validation
    assert report.run_id == job.run_id and report.source_attempt_id is None  # No executor in a phase check.
    assert report.entries[0].reports[0].status == 'complete'
    assert SQLiteManagedViews(database).test_original(job.run_id, 0, 0, 0)[0] == simple_xml()
    assert 'original_base64' not in agents.requests[0].prompt
    assert load_history(dump_history(record.history)) == record.history
    database.dispose()


def test_revalidation_keeps_previous_original_and_execution_provenance(git_repo, migrated_database):
    context, repository, supervisor, job, agents = managed_run(git_repo, migrated_database, result=CommandResult(2))
    previous = repository.get_run(job.run_id)
    first = previous.history.cycles[0].validation
    workspace = GitWorkspace(IDENTITY)
    runner = ReportRunner(simple_xml(2))
    revalidator = LocalSupervisor(repository, lambda *_: (ScriptedAgentAdapter([review()]), runner, workspace),
                                  commit_factory=lambda *_: workspace)
    repository.resume(job.run_id, key='junit-revalidate', expected_version=previous.version)
    assert revalidator.run_once().status == 'DONE'
    history = repository.get_run(job.run_id).history
    assert history.status == 'acceptance_ready' and len(history.cycles) == 2
    second = history.cycles[-1].validation
    assert history.cycles[0].validation == first and second.source_attempt_id == first.source_attempt_id
    assert second.entries[0].command_id != first.entries[0].command_id
    assert SQLiteManagedViews(repository.engine).test_original(job.run_id, 0, 0, 0)[0] == simple_xml(55)
    assert SQLiteManagedViews(repository.engine).test_original(job.run_id, 1, 0, 0)[0] == simple_xml(2)
    assert len(agents.requests) == 2  # Revalidating does not repeat execution.
    repository.engine.dispose()
