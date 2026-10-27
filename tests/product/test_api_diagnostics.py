"""P011-T010: own HTTP diagnostics of the API package follow the stored visual language.

Codes and statuses never change with the language. Temporary SQLite/Git and fake agents only; no providers,
services or network."""
import ast
from pathlib import Path
import re

from my_harness import i18n
from my_harness.api import session as session_module
from test_managed import context, repository, submit, worker  # noqa: F401  (fixtures)
from test_managed_api import client, config, repo, task, url  # noqa: F401  (fixtures)

PREFERENCES = '/api/managed/preferences'
API = Path(session_module.__file__).parent


def save_language(http, language):
    current = http.get(PREFERENCES).json()
    saved = http.put(PREFERENCES, json={'expected_version': current['version'], 'ui_language': language,
                                        'default_work_language': current['default_work_language']},
                     headers={'Idempotency-Key': f'ui-{language}-{current["version"]}'})
    assert saved.status_code == 200, saved.text


def test_guard_and_router_diagnostics_follow_the_visual_language(url, tmp_path, task):  # noqa: F811
    with client(url, tmp_path, config(task)) as http:
        for language in ('en', 'es'):
            save_language(http, language)
            unguarded = http.put(PREFERENCES, json={}, headers={'X-My-Harness': ''})
            assert unguarded.status_code == 403
            assert unguarded.json()['detail'] == {'code': 'csrf_header_required',
                                                  'diagnostic': i18n.message('api.csrf_header_required', language)}
            foreign = http.get(PREFERENCES, headers={'Sec-Fetch-Site': 'cross-site'})
            assert foreign.json()['detail'] == {'code': 'origin_rejected',
                                                'diagnostic': i18n.message('api.cross_site', language)}
            metrics = http.get('/api/managed/metrics/summary?phase=P001')
            assert metrics.status_code == 422
            assert metrics.json()['detail'] == {'code': 'invalid_request',
                                                'diagnostic': i18n.message('api.project_id_required', language)}
        assert i18n.message('api.cross_site', 'es') != i18n.message('api.cross_site', 'en')


def test_the_access_key_line_is_fixed_technical_output():
    # Maintainer scripts read the key path from this line; it is never localized.
    source = (API / 'session.py').read_text()
    assert "print(f'My Harness: access key at {self.path}', flush=True)" in source
    for script in ('scripts/dev.py', 'scripts/check_distribution.py'):
        assert 'access key at' in (API.parents[2] / script).read_text(), script


def test_api_package_has_no_own_spanish_literals():
    """Visible texts of the API package come from the catalogs; docstrings are English since T004."""
    for path in sorted(API.glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not re.search(r'[áéíóúñ¿¡]', node.value), (path.name, node.lineno, node.value)
