"""P011-T021: own service and CLI texts follow the visual language of each emission (D171).

An HTTP request reads the stored preferences, a worker the visual language frozen with its job and the CLI
`--ui-language` or the database's preferences. Codes, statuses and hashes never change with the language.
Temporary SQLite/Git, fake agents and synthetic data only; no providers, services or network."""
import ast
import copy
import json
import pickle
import re
import sqlite3
from pathlib import Path

import pytest

from my_harness import i18n
from my_harness.cli import build_parser, main
from my_harness.services.local_config import load_local_config
from my_harness.services.managed import LocalSupervisor
from my_harness.services.project_registry import trust_statement
from test_api_diagnostics import save_language
from test_backup import db_path
from test_local_config import setup, write  # noqa: F401  (fixtures)
from test_managed import context, repository  # noqa: F401  (fixtures)
from test_managed_api import client
from test_project_registry import confirm, operator, register, v3  # noqa: F401  (fixtures)
from test_retention import preview, sealed  # noqa: F401  (fixtures)
from test_typescript_profile import web  # noqa: F401  (fixture)

SOURCE = Path(i18n.__file__).parents[1]
SPANISH = re.compile(r'[áéíóúñ¿¡]|\b(desconocid[oa]s?|gestionad[oa]|requerid[oa]s?|vuelve|revisa|sin resolver)\b')
# Spanish on purpose (D159/D169/D170/D171): work-language vocabulary and bilingual parser aliases, frozen v1 recipes
# and profile values tied to fingerprints, Spanish chat protocol tokens and the unchanged technical commit message.
EXCEPTIONS = {
    'core/engine/document_text.py': None, 'core/engine/language.py': None, 'core/engine/planning.py': None,
    'core/engine/import_commit.py': None, 'core/engine/documents.py': {'fuera de alcance'},
    'core/engine/document_export.py': {'Estado gestionado por My Harness (SQLite).\n\n```json\n'},
    'core/engine/definition.py': {'ROADMAP needs at least one phase section «## PNNN — título»'},
    'core/engine/onboarding_commit.py': {'docs: incorporar al control del harness'},
    'core/engine/chat_commands.py': {'abrir-fase', 'tarea'}, 'storage/chat.py': {'tarea'},
    'api/schemas.py': {'abrir-fase'}, 'recipes/django.py': None, 'recipes/typescript_web.py': None,
    'recipes/django_2.py': None, 'recipes/typescript_web_2.py': None, 'profiles/typescript_web.py': None,
    'services/project_preparation.py': {'Verificar intérprete base', 'Crear entorno aislado',
                                        'Con red, npm descarga del registro y escribe en la caché del operador.'},
}


def literals(path):
    tree = ast.parse(path.read_text())
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


def test_tr_follows_the_emission_and_keeps_its_key():
    assert i18n.current() == 'en' and i18n.tr('registry.unknown') == 'Unknown registered project.'
    with i18n.emission('es'):
        text = i18n.tr('registry.id_used', id='web')
        with i18n.emission(lambda: 'en'):
            assert i18n.tr('registry.unknown') == 'Unknown registered project.'
        assert i18n.current() == 'es'
    assert text == 'El id web ya lo usa otro proyecto.' and text.render('en') == 'The id web is already used by another project.'
    assert i18n.rendered(text, 'en') == text.render('en') and i18n.rendered('raw', 'en') == 'raw'
    with i18n.emission(lambda: 1 / 0):  # a failing resolver never breaks a message
        assert i18n.current() == 'en'
    with i18n.emission('fr'):
        assert i18n.current() == 'en'
    # Everywhere else it is a plain text: copies, pickles, JSON and comparisons keep only the text.
    for value in (copy.copy(text), copy.deepcopy(text), pickle.loads(pickle.dumps(text))):
        assert type(value) is str and value == text
    assert json.dumps({'d': text}, ensure_ascii=False) == '{"d": "El id web ya lo usa otro proyecto."}'


def test_service_catalog_keys_exist_in_both_languages():
    base, other = i18n.catalog('en'), i18n.catalog('es')
    used = set()
    for path in SOURCE.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = getattr(node.func, 'id', getattr(node.func, 'attr', None))
            first = node.args[0]
            if name in ('tr', 'message', 'say') and isinstance(first, ast.Constant) and isinstance(first.value, str):
                used.add(('cli.help.' if path.name == 'cli.py' and name == 'say' else '') + first.value)
    from my_harness.adapters.cli_diagnostics import FIXES
    used |= {f'cli_diagnostics.{code}' for code in FIXES}
    used.discard('{}')
    missing = sorted(key for key in used if '.' in key and (key not in base or key not in other))
    assert not missing, missing
    assert len(used) > 400


def test_no_own_spanish_literals_outside_the_documented_exceptions():
    found = []
    for path in sorted(SOURCE.rglob('*.py')):
        relative = path.relative_to(SOURCE).as_posix()
        if relative.startswith('migrations/'):
            continue
        allowed = EXCEPTIONS.get(relative, set())
        if allowed is None:
            continue
        found += [(relative, node.lineno, node.value[:80]) for node in literals(path)
                  if SPANISH.search(node.value) and node.value not in allowed]
    assert not found, found


def test_registry_diagnostics_and_trust_follow_the_saved_visual_language(operator, migrated_database):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        for language in ('en', 'es'):
            save_language(http, language)
            refused = http.post('/api/managed/registry/preview', json=register('relative/path'))
            assert refused.status_code == 422
            assert refused.json()['detail'] == {'code': 'root_not_absolute',
                                                'diagnostic': i18n.message('registry.root_absolute', language)}
            shown = http.post('/api/managed/registry/preview', json=register(context.root)).json()
            assert shown['trust_statement'] == i18n.message('registry.trust', language)
            assert http.get('/api/managed/registry').json()['trust_statement'] == shown['trust_statement']
        # The record keeps the statement confirmed in the preview, in the language it was shown.
        assert confirm(http, register(context.root))[1].status_code == 200
        trust = http.get('/api/managed/registry/projects/web').json()['trust']
        assert trust['statement'] == i18n.message('registry.trust', 'es') != i18n.message('registry.trust', 'en')
    assert trust_statement() == i18n.message('registry.trust', 'en')


def test_cli_help_and_errors_follow_the_invocation_language(tmp_path, capsys, migrated_database):
    assert 'Destino nuevo; restauración solo de consulta' in build_parser('es').format_help() + ''.join(
        action.format_help() for action in build_parser('es')._subparsers._group_actions[0].choices.values())
    with pytest.raises(SystemExit):
        main(['--ui-language', 'es', '--help'])
    assert 'Backup, retención, diagnóstico y operación local del servicio' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(['--help'])
    assert 'Local backup, retention, diagnostics and service operation' in capsys.readouterr().out
    database = db_path(migrated_database)
    stop = ['migrate', '--database', str(database), '--snapshots', str(tmp_path / 'snapshots')]
    assert main(['--ui-language', 'es', *stop]) == 1
    assert capsys.readouterr().err.strip() == i18n.message('migrate.writers', 'es')
    assert main(stop) == 1  # the database's preferences (factory en)
    assert capsys.readouterr().err.strip() == i18n.message('migrate.writers', 'en')
    with sqlite3.connect(database) as db:
        db.execute("UPDATE product_preferences SET ui_language = 'es'")
    assert main(stop) == 1
    assert capsys.readouterr().err.strip() == i18n.message('migrate.writers', 'es')
    assert main(['--ui-language', 'en', *stop]) == 1  # the override is not saved
    assert capsys.readouterr().err.strip() == i18n.message('migrate.writers', 'en')


def test_retention_preview_hash_does_not_depend_on_the_language(sealed):  # noqa: F811
    with i18n.emission('es'):
        spanish = preview(sealed, min_bytes=1000000)
    english = preview(sealed, min_bytes=1000000)
    assert spanish['preview_sha256'] == english['preview_sha256']
    assert {item['diagnostic'] for item in spanish['items']} == {i18n.message('retention.kept_policy', 'es')}
    assert {item['diagnostic'] for item in english['items']} == {i18n.message('retention.kept_policy', 'en')}


def test_a_claimed_job_runs_in_its_frozen_visual_language(repository, monkeypatch):  # noqa: F811
    claim = type('Claim', (), {'id': 1})()
    monkeypatch.setattr(repository, 'job_language', lambda claimed: {'format': 'language-context-1', 'ui_language': 'es'})
    assert repository.job_visual(claim) == 'es'
    monkeypatch.setattr(repository, 'job_language', lambda claimed: None)  # admitted before D166: stored value
    assert repository.job_visual(claim) == 'en'
    seen = []
    supervisor = LocalSupervisor.__new__(LocalSupervisor)
    supervisor.lane, supervisor.lease_seconds = 'chat', 30
    supervisor.repository = type('Repository', (), {
        'recover_expired': lambda self: None, 'claim': lambda self, **kwargs: claim,
        'job_visual': lambda self, claimed: 'es'})()
    monkeypatch.setattr(LocalSupervisor, '_run_claimed', lambda self, claimed: seen.append(i18n.tr('views.job_unknown')))
    supervisor.run_once()
    assert seen == ['Job gestionado desconocido.'] and i18n.current() == 'en'
