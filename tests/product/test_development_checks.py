"""Development check scripts (OT008): compact suite summaries and documentation checks. Synthetic, offline."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import check  # noqa: E402
import check_docs  # noqa: E402


PYTEST_OUTPUT = '''..F.sE
=================================== ERRORS ===================================
___________________ ERROR at setup of test_fixture_error ____________________
E   ValueError: synthetic fixture error
=========================== short test summary info ===========================
FAILED tests/product/test_synthetic.py::test_fails - AssertionError: synthetic mismatch
FAILED tests/product/test_synthetic.py::Group::test_raises[case-1] - RuntimeError: synthetic runtime error
ERROR tests/product/test_synthetic.py::test_fixture_error - ValueError: synthetic fixture error
2 failed, 3 passed, 1 skipped, 1 error in 0.42s
'''

NODE_OUTPUT = '''TAP version 13
# Subtest: passes
ok 1 - passes
  ---
  duration_ms: 0.3
  ...
# Subtest: synthetic failure
not ok 2 - synthetic failure
  ---
  location: '/synthetic/frontend/tests/labels.test.mjs:3:1'
  error: |-
    one is not two

    1 !== 2
  code: 'ERR_ASSERTION'
  ...
# Subtest: inline error
not ok 3 - inline error
  ---
  location: '/synthetic/frontend/tests/forms.test.mjs:9:1'
  error: 'synthetic inline'
  ...
1..3
# tests 3
# suites 0
# pass 1
# fail 2
# cancelled 0
# skipped 0
'''


def test_pytest_summary_keeps_counts_ids_and_first_error_line():
    ok, counts, failures = check.parse_pytest(PYTEST_OUTPUT, 1)
    assert not ok and counts == '2 failed, 3 passed, 1 skipped, 1 error'
    assert failures == [
        ('FAILED tests/product/test_synthetic.py::test_fails', 'AssertionError: synthetic mismatch'),
        ('FAILED tests/product/test_synthetic.py::Group::test_raises[case-1]', 'RuntimeError: synthetic runtime error'),
        ('ERROR tests/product/test_synthetic.py::test_fixture_error', 'ValueError: synthetic fixture error'),
    ]
    assert check.parse_pytest('=== 5 passed, 2 skipped, 3 subtests passed in 1.20s (0:00:01) ===\n', 0) == (
        True, '5 passed, 2 skipped, 3 subtests passed', [])


def test_pytest_failure_without_summary_reports_the_last_line():
    ok, counts, failures = check.parse_pytest('ERROR: file or directory not found: tests/missing.py\n', 4)
    assert (ok, counts) == (False, 'exit 4')
    assert failures == [('pytest', 'ERROR: file or directory not found: tests/missing.py')]


def test_node_tap_failures_name_file_test_and_error():
    ok, counts, failures = check.parse_node(NODE_OUTPUT, 1)
    assert not ok and counts == '3 tests, 1 pass, 2 fail'
    assert failures == [('labels.test.mjs › synthetic failure', 'one is not two'),
                        ('forms.test.mjs › inline error', 'synthetic inline')]


def test_build_reports_typescript_errors_and_alembic_reports_new_operations():
    output = "src/pages/Settings.tsx(12,5): error TS2322: Type 'number' is not assignable to type 'string'.\n"
    assert check.parse_build(output, 2) == (False, '', [
        ('src/pages/Settings.tsx(12,5)', "TS2322: Type 'number' is not assignable to type 'string'.")])
    assert check.parse_build('✓ built in 724ms\n', 0) == (True, 'tsc + vite built in 724ms', [])
    assert check.parse_alembic('No new upgrade operations detected.\n', 0)[0]
    failed = check.parse_alembic("FAILED: New upgrade operations detected: [('add_table', ...)]\n", 255)
    assert failed == (False, 'exit 255', [('alembic', "FAILED: New upgrade operations detected: [('add_table', ...)]")])


def test_suite_selection_and_pytest_passthrough():
    args = check.parse_arguments(['tests/product/test_a.py', '--', '-k', 'name', '-n', '0'])
    assert check.selected_suites(args) == ['pytest'] and args.pytest_args == ['-k', 'name', '-n', '0']
    assert check.selected_suites(check.parse_arguments([])) == ['unittest', 'alembic', 'pytest']
    assert check.selected_suites(check.parse_arguments(['--frontend'])) == [
        'unittest', 'alembic', 'pytest', 'node', 'build']
    assert check.selected_suites(check.parse_arguments(['--suite', 'node', '--suite', 'alembic'])) == [
        'alembic', 'node']


def test_failure_list_and_lines_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(check, 'ROOT', tmp_path)
    failures = [(f'FAILED tests/test_{index}.py::test', 'x' * 500) for index in range(25)]
    lines = check.Result('pytest', False, '25 failed', failures, 1.0).lines(tmp_path / 'pytest.log')
    assert lines[0] == 'pytest: FAILED — 25 failed (1.0s)'
    assert len(lines) == 1 + check.MAX_FAILURES + 2 and lines[-2] == '  … 5 more' and lines[-1] == '  log: pytest.log'
    assert all(len(line) < 2 * check.MAX_LINE for line in lines)


@pytest.mark.parametrize('failing', [False, True])
def test_unittest_suite_matches_the_direct_outcome(tmp_path, monkeypatch, capsys, failing):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_synthetic.py').write_text(
        'import unittest\n\n\nclass Synthetic(unittest.TestCase):\n'
        '    def test_passes(self):\n        self.assertTrue(True)\n\n'
        f'    def test_compares(self):\n        self.assertEqual(1, {2 if failing else 1}, "synthetic mismatch")\n')
    monkeypatch.setattr(check, 'ROOT', tmp_path)
    monkeypatch.setattr(check, 'LOGS', tmp_path / '.local/check')
    assert check.main(['--suite', 'unittest']) == (1 if failing else 0)
    printed = capsys.readouterr().out.splitlines()
    if failing:
        assert printed[0].startswith('unittest: FAILED — 2 ran, failures=1 (')
        assert printed[1] == ('  FAIL test_compares (test_synthetic.Synthetic.test_compares)'
                              ' — AssertionError: 1 != 2 : synthetic mismatch')
        assert printed[2] == '  log: .local/check/unittest.log'
    else:
        assert len(printed) == 1 and printed[0].startswith('unittest: ok — 2 ran (')
    assert 'Ran 2 tests' in (tmp_path / '.local/check/unittest.log').read_text()
    assert [path.name for path in (tmp_path / '.local/check').iterdir()] == ['unittest.log']


@pytest.mark.parametrize(('heading', 'anchor'), [
    ('D235 — Release branch, integration branch and topic branches',
     'd235--release-branch-integration-branch-and-topic-branches'),
    ('`scripts/check` and snake_case _emphasis_', 'scriptscheck-and-snake_case-emphasis'),
    ('P001 — Metrics **Records** [link](x.md)', 'p001--metrics-records-link'),
    ('Ñandú: «cámara» ¿sí?', 'ñandú-cámara-sí'),
])
def test_heading_slugs_follow_github(heading, anchor):
    assert check_docs.slug(heading) == anchor


@pytest.fixture
def docs(tmp_path, monkeypatch):
    monkeypatch.setattr(check_docs, 'ROOT', tmp_path)
    check_docs.anchors.cache_clear()
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/TARGET.md').write_text(
        '# Target\n\n## D260 — Quiet checks\n\n## Repeat\n\n## Repeat\n\n<a id="explicit-anchor"></a>\n'
        '```md\n## Not a heading\n```\n')
    return tmp_path


def test_links_accept_headings_duplicates_explicit_anchors_and_external_urls(docs):
    page = docs / 'docs/PAGE.md'
    page.write_text('[a](TARGET.md#d260--quiet-checks) [b](TARGET.md#repeat-1) [c](./TARGET.md#explicit-anchor)\n'
                    '[d](https://example.invalid/x) [e](#local) [f](../docs/) [g](<TARGET.md>)\n\n## Local\n'
                    '`[not](missing.md)`\n\n```\n[not](missing.md)\n```\n[ref]: TARGET.md#target\n')
    assert check_docs.link_errors(page) == []


def test_links_report_missing_targets_and_anchors(docs):
    page = docs / 'docs/PAGE.md'
    page.write_text('Intro\n[a](MISSING.md)\n[b](TARGET.md#not-a-heading) [c](TARGET.md#repeat-2)\n[d](#nowhere)\n')
    assert check_docs.link_errors(page) == [
        'docs/PAGE.md:2: missing target MISSING.md',
        'docs/PAGE.md:3: missing anchor #not-a-heading in docs/TARGET.md',
        'docs/PAGE.md:3: missing anchor #repeat-2 in docs/TARGET.md',
        'docs/PAGE.md:4: missing anchor #nowhere in docs/PAGE.md',
    ]


def test_unpaired_fence_is_reported_at_its_opening_line():
    assert check_docs.unclosed_fence('# T\n\n```sh\nrun\n```\n\n~~~\ntext\n~~~\n') is None
    assert check_docs.unclosed_fence('# T\n\n````md\n```\nnested\n```\n') == 3
    assert check_docs.unclosed_fence('# T\n\n```python\ncode\n') == 3


def test_catalog_pairs_must_have_the_same_keys(tmp_path):
    (tmp_path / 'en.json').write_text(json.dumps({'a.one': 'One', 'a.two': 'Two'}))
    (tmp_path / 'es.json').write_text(json.dumps({'a.one': 'Uno', 'a.three': 'Tres'}))
    assert check_docs.catalog_errors(tmp_path, [('en.json', 'es.json')]) == [
        'en.json: missing keys a.three', 'es.json: missing keys a.two']


def test_diagram_head_and_table_count_follow_the_code(tmp_path):
    storage, versions = tmp_path / 'src/my_harness/storage', tmp_path / 'src/my_harness/migrations/versions'
    storage.mkdir(parents=True)
    versions.mkdir(parents=True)
    (versions / '0001_base.py').write_text("revision = '0001_base'\ndown_revision = None\n")
    (versions / '0002_more.py').write_text("revision = '0002_more'\ndown_revision = '0001_base'\n")
    (storage / 'schema.py').write_text('SCHEMA_REVISION = "0002_more"\n')
    (storage / 'models.py').write_text('class A:\n    __tablename__ = "a"\n\n\nclass B:\n    __tablename__ = "b"\n')
    (tmp_path / 'docs').mkdir()
    diagram = tmp_path / check_docs.DIAGRAM
    diagram.write_text('Alembic head `0002_more`, 2 tables.\n')
    assert check_docs.diagram_errors(tmp_path) == []
    diagram.write_text('Alembic head `0001_base`, 2 tables.\n')
    assert check_docs.diagram_errors(tmp_path) == [
        'docs/DDBB-DIAGRAM.md: states head 0001_base with 2 tables; code has 0002_more with 2 tables']
    (versions / '0003_new.py').write_text("revision = '0003_new'\ndown_revision = '0002_more'\n")
    assert 'SCHEMA_REVISION 0002_more is not the migration head 0003_new' in check_docs.diagram_errors(tmp_path)[0]
