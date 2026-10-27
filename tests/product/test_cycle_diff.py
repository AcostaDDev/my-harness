"""D085 finding 1: reviewed diff of each cycle by pages and a run without the diff content.

Temporary Git and SQLite with fake agents; no providers or network.
"""

import hashlib

import pytest

from my_harness.storage.managed_views import MAX_DIFF_PAGE, diff_page
from test_managed_api import Ports, client, config, review, settle, submit, url, repo, task  # noqa: F401  (fixtures)


def pages(text, limit):
    offset, chunks = 0, []
    while offset is not None:
        page = diff_page(text, offset, limit)
        assert page['offset'] == offset
        chunks.append(page)
        offset = page['next_offset']
    return chunks


@pytest.mark.parametrize('limit', [1, 3, 7, 64, 4096])
def test_pages_reassemble_the_exact_text_and_end_on_lines(limit):
    text = ''.join(f'+línea {n} ñandú €\n' for n in range(200)) + '+sin salto final ' + 'x' * 50
    chunks = pages(text, limit)
    assert ''.join(chunk['text'] for chunk in chunks) == text
    for chunk in chunks[:-1]:
        data = chunk['text'].encode('utf-8')
        # Ends at an end of line, or at a UTF-8 boundary if the line does not fit in the page.
        assert data.endswith(b'\n') or len(data) <= limit + 3


def test_long_line_is_cut_on_a_utf8_boundary_and_bad_cursors_are_rejected():
    text = 'ñ' * 10 + '\n'
    first = diff_page(text, 0, 3)
    assert first == {'offset': 0, 'next_offset': 4, 'text': 'ññ'}
    with pytest.raises(ValueError, match='previous next_offset'):
        diff_page(text, 1, 3)  # in the middle of «ñ»
    with pytest.raises(ValueError, match='previous next_offset'):
        diff_page(text, len(text.encode('utf-8')) + 1, 3)
    for offset, limit in ((-1, 3), (0, 0), (0, MAX_DIFF_PAGE + 1)):
        with pytest.raises(ValueError, match='Invalid diff page'):
            diff_page(text, offset, limit)
    assert diff_page('', 0, 4096) == {'offset': 0, 'next_offset': None, 'text': ''}


def test_run_carries_the_diff_summary_and_the_diff_is_read_by_pages(tmp_path, url, task):  # noqa: F811
    body = ''.join(f'línea {n:05d} con ñ y €\n' for n in range(12_000))  # ~290 KiB

    def large(context, request):
        context.path('app/main.txt').write_text(body, encoding='utf-8')
        return {'result': 'synthetic'}

    with client(url, tmp_path, config(task, Ports([large, review()]))) as http:
        job = submit(http).json()
        run = settle(http, job['run_id'])
        assert run['status'] == 'ACCEPTANCE_READY' and run['active_job'] is None
        raw = http.get(f"/api/managed/runs/{job['run_id']}")
        assert len(raw.content) < 32 * 1024  # polling no longer transfers the diff
        cycle = run['history']['latest_cycle']
        assert run['history']['cycle_count'] == 1
        assert 'diff' not in cycle and cycle['diff_bytes'] > 256 * 1024
        evidence = cycle['validation']['evidence']  # same validated evidence, also without the text
        assert 'diff' not in evidence and evidence['diff_sha256'] == cycle['diff_sha256']
        path = f"/api/managed/runs/{job['run_id']}/cycles/0/diff"
        text, offset, count = '', 0, 0
        while offset is not None:
            page = http.get(path, params={'offset': offset, 'limit': 64 * 1024, 'sha256': cycle['diff_sha256']}).json()
            assert (page['run_id'], page['cycle'], page['sha256'], page['size_bytes']) == (
                job['run_id'], 0, cycle['diff_sha256'], cycle['diff_bytes'])
            assert page['offset'] == offset and len(page['text'].encode('utf-8')) <= 64 * 1024
            assert page['next_offset'] is None or page['text'].endswith('\n')
            text, offset, count = text + page['text'], page['next_offset'], count + 1
        assert count >= 5
        assert hashlib.sha256(text.encode('utf-8')).hexdigest() == cycle['diff_sha256']
        assert len(text.encode('utf-8')) == cycle['diff_bytes'] and '+línea 11999 con ñ y €' in text
        # Without `sha256` it is served too; with another hash, 409. Limits and cursors outside the contract, 422;
        # unknown cycle or run, 404.
        default = http.get(path).json()  # default 64 KiB page
        assert default['next_offset'] is not None and len(default['text'].encode('utf-8')) <= 64 * 1024
        assert http.get(path, params={'sha256': '0' * 64}).status_code == 409
        assert http.get(path, params={'sha256': 'not-a-hash'}).status_code == 422
        assert http.get(path, params={'limit': 1024}).status_code == 422
        assert http.get(path, params={'limit': MAX_DIFF_PAGE + 1}).status_code == 422
        middle = text.encode('utf-8').index('ñ'.encode('utf-8')) + 1
        assert http.get(path, params={'offset': middle}).status_code == 422
        assert http.get(path, params={'offset': cycle['diff_bytes'] + 1}).status_code == 422
        assert http.get(f"/api/managed/runs/{job['run_id']}/cycles/1/diff").status_code == 404
        assert http.get(f"/api/managed/runs/{job['run_id']}/cycles/-1/diff").status_code == 404
        assert http.get('/api/managed/runs/unknown/cycles/0/diff').status_code == 404


def test_run_jobs_are_paginated_newest_first(tmp_path, url, task):  # noqa: F811
    def edit(context, request):
        context.path('app/main.txt').write_text('implemented\n', encoding='utf-8')
        return {'result': 'synthetic'}

    with client(url, tmp_path, config(task, Ports([edit, review()]))) as http:
        job = submit(http).json()
        run = settle(http, job['run_id'])
        commit = http.post(f"/api/managed/runs/{job['run_id']}/actions",
                           json={'action': 'commit', 'expected_version': run['version']},
                           headers={'Idempotency-Key': 'commit'}).json()
        settle(http, job['run_id'])
        path = f"/api/managed/runs/{job['run_id']}/jobs"
        first = http.get(path, params={'limit': 1}).json()
        assert [j['id'] for j in first['items']] == [commit['id']] and first['next_offset'] == 1
        second = http.get(path, params={'offset': 1, 'limit': 1}).json()
        assert [j['id'] for j in second['items']] == [job['id']] and second['next_offset'] is None
        assert http.get(path, params={'limit': 101}).status_code == 422
        assert http.get('/api/managed/runs/unknown/jobs').status_code == 404
