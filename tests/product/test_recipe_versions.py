"""P011-T004 (D163): frozen v1 recipe identities and the maintained v2 successors (wired by T020, D168).

Data-only: no preparation, process, Git or SQLite. The v1 hashes are the T001 §5 baseline, reissued once by the
rename to my_harness (D230); a change to any of them would invalidate issued receipts and composition hashes.
"""
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from my_harness import recipes
from my_harness.recipes import django, django_2, typescript_web, typescript_web_2
from my_harness.services import project_preparation

SOURCES = Path(recipes.__file__).parent
V1_BYTES = {
    'django-packages.json': '4c73e05b05cd14ac38284341e42ff3e39938ec4055e9c91f0baf4c6b3942d9e8',
    'django-requirements.lock': '0f2ce9afc90274a6da1b6c1d8b10cc62d6f530dd0b1f1c8c95609fd27d313c1b',
    'django.py': '23459eac8c1248e722ee86413bcc6f5473ece7649ae76d147b16adc7cc4cd8d7',
    'typescript_web.py': 'c3df3655cafd2f9284166c93109aa62f14607fc8587746877c92b1eba4fe14fe',
}
V1_FINGERPRINTS = {django: 'd2b89bcaa647d659dac7417c4af53e7cb532cfbaef1fd7346cb29d440eb35ff2',
                   typescript_web: 'db5cc7d21fe4ef7b82b47ac3ce14a9445137d836ffdc5f8c9e25cf03d5638041'}
DJANGO = {'installer_executable': '/tools/uv', 'python_executable': '/tools/python', 'timeout_seconds': 300,
          'max_output_bytes': 4096}
NODE = {'node_executable': '/tools/node', 'npm_executable': '/tools/npm', 'npm_cache': '/cache',
        'node_version': '1.2.3', 'npm_version': '4.5.6', 'timeout_seconds': 300, 'max_output_bytes': 4096}


def effects(steps):
    """The step without its human description and stable id: what actually runs or is published."""
    return [{key: value for key, value in step.items() if key not in ('id', 'label')} for step in steps]


def test_v1_sources_and_fingerprints_keep_their_issued_identity():
    assert {name: hashlib.sha256((SOURCES / name).read_bytes()).hexdigest() for name in V1_BYTES} == V1_BYTES
    assert {module: module.fingerprint() for module in V1_FINGERPRINTS} == V1_FINGERPRINTS


def test_each_format_selects_its_recipe_generation_and_frozen_versions_stay_readable():
    # P011-T020 (D168): v5 keeps v1, v6 selects v2; issued plans/receipts of both resolve by their version.
    generations = {'local-config-5': (django, typescript_web), 'local-config-6': (django_2, typescript_web_2),
                   'local-config-7': (django_2, typescript_web_2),
                   'local-config-8': (django_2, typescript_web_2)}
    for fmt, modules in generations.items():
        assert (recipes.module('django', fmt), recipes.module('typescript-web', fmt)) == modules
        for name, module in zip(('django', 'typescript-web'), modules):
            assert recipes.by_version(module.VERSION) == (name, module)
    assert recipes.by_version('django-recipe-3') is None
    assert set(project_preparation.RECIPES) == {m.VERSION for m in (django, typescript_web, django_2, typescript_web_2)}
    assert recipes.implementation(django) == {'implementation_sha256': V1_FINGERPRINTS[django]}
    assert recipes.implementation(django_2) == {'implementation_sha256_by_work_language': {
        language: django_2.fingerprint(language) for language in ('en', 'es')}}


def test_django_v2_changes_only_technical_prose_by_work_language():
    assert django_2.scaffold('es') == django.scaffold()
    english = django_2.scaffold('en')
    assert {path for path in english if english[path] != django.scaffold()[path]} == {'core/models.py'}
    assert english['core/models.py'] == '"""Business models pending the tasks of P001."""\n'
    # Functional defaults of the child application are not derived from the work language.
    assert 'LANGUAGE_CODE = "es"' in english['config/settings.py']
    assert '<html lang="es">' in english['templates/core/index.html']
    assert replace(django_2.profile(), executor_instructions='') == replace(django.profile(), executor_instructions='')
    assert django_2.templates(english).keys() == django.templates(django.scaffold()).keys()


def test_typescript_v2_changes_only_test_prose_and_owns_its_profile():
    assert typescript_web_2.manifest('web', NODE, 'en') == typescript_web.manifest('web', NODE)
    spanish = typescript_web_2.manifest('web', NODE, 'es')
    assert {path for path in spanish if spanish[path] != typescript_web.manifest('web', NODE)[path]} == {
        'tests/main.test.mjs'}
    assert 'test("nombra el proyecto preparado"' in spanish['tests/main.test.mjs']
    assert '<html lang="es">' in spanish['index.html']
    v2, v1 = typescript_web_2.profile(), typescript_web.profile()
    assert replace(v2, junit_reports=()) == replace(v1, junit_reports=())
    assert [(r.command, r.path) for r in v2.junit_reports] == [(r.command, r.path) for r in v1.junit_reports]
    assert v2.junit_reports[0].coverage == 'Node tests from tests/*.test.mjs; no code coverage'


@pytest.mark.parametrize('mode', ['offline', 'network'])
def test_v2_steps_keep_v1_effects_with_stable_ids(mode, tmp_path):
    pairs = ((django, django_2, {**DJANGO, 'wheelhouse': str(tmp_path)}), (typescript_web, typescript_web_2, NODE))
    for old, new, config in pairs:
        steps = new.steps(tmp_path, config, mode)
        assert effects(steps) == effects(old.steps(tmp_path, config, mode))
        ids = [step['id'] for step in steps]
        assert len(set(ids)) == len(ids) and all(step['label'] for step in steps)


def test_v2_fingerprints_bind_version_and_work_language():
    prints = {(module, language): module.fingerprint(language)
              for module in (django_2, typescript_web_2) for language in ('en', 'es')}
    assert len(set(prints.values())) == 4
    assert set(prints.values()).isdisjoint(V1_FINGERPRINTS.values())
    assert prints == {key: key[0].fingerprint(key[1]) for key in prints}
    for module in (django_2, typescript_web_2):
        with pytest.raises(ValueError, match='work language'):
            module.fingerprint('fr')
