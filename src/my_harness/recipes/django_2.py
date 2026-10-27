"""Django recipe 2 (P011-T004, D163). Data-only plan construction; no process or checkout reads.

Maintained successor of the frozen `django-recipe-1`, which stays byte-identical for issued receipts. The scaffold
is parametrized by the project's work language: comments and docstrings follow it, while the child application's
functional defaults (`LANGUAGE_CODE`, `<html lang>` and visible text) keep the v1 values (P011-T001 §5).
Steps carry a stable `id`; their `label` is human prose. Selected by `local-config-6` (P011-T020, D168).
"""
import json
from dataclasses import asdict
from pathlib import Path
from textwrap import dedent

from my_harness.core.engine.context import Command, JUnitDeclaration, ProjectProfile

VERSION = 'django-recipe-2'
WORK_LANGUAGES = ('en', 'es')
# Language-neutral data shared with v1: the pinned dependency closure and its hashed lock.
PACKAGES = json.loads(Path(__file__).with_name('django-packages.json').read_text())
LOCK = Path(__file__).with_name('django-requirements.lock').read_text()
WORK = '.harness-preparation'
MODELS_DOCSTRING = {'en': 'Business models pending the tasks of P001.',
                    'es': 'Modelos de negocio pendientes de las tareas de P001.'}


def text(value):
    return dedent(value).lstrip('\n')


def work_language(value):
    if value not in WORK_LANGUAGES:
        raise ValueError(f'Unsupported work language: {value!r}')
    return value


def scaffold(language):
    """The whole technical commit for one work language; only technical prose depends on it."""
    language = work_language(language)
    return {
        'manage.py': text('''
            import os
            import sys

            from django.core.management import execute_from_command_line


            def main() -> None:
                os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
                execute_from_command_line(sys.argv)


            if __name__ == "__main__":
                main()
            '''),
        'config/__init__.py': '',
        'config/settings.py': text('''
            from pathlib import Path

            BASE_DIR = Path(__file__).resolve().parent.parent
            SECRET_KEY = (BASE_DIR / ".django-secret").read_text().strip()
            DEBUG = True
            ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
            INSTALLED_APPS = [
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.sessions",
                "django.contrib.staticfiles",
                "core",
            ]
            MIDDLEWARE = [
                "django.middleware.security.SecurityMiddleware",
                "django.contrib.sessions.middleware.SessionMiddleware",
                "django.middleware.common.CommonMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware",
            ]
            ROOT_URLCONF = "config.urls"
            TEMPLATES = [
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "DIRS": [BASE_DIR / "templates"],
                    "APP_DIRS": True,
                    "OPTIONS": {
                        "context_processors": [
                            "django.template.context_processors.request",
                            "django.contrib.auth.context_processors.auth",
                        ]
                    },
                }
            ]
            WSGI_APPLICATION = "config.wsgi.application"
            ASGI_APPLICATION = "config.asgi.application"
            DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
            AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []
            LANGUAGE_CODE = "es"
            TIME_ZONE = "UTC"
            USE_I18N = True
            USE_TZ = True
            STATIC_URL = "static/"
            STATICFILES_DIRS = [BASE_DIR / "static"]
            DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
            '''),
        'config/urls.py': text('''
            from django.urls import include, path

            urlpatterns = [path("", include("core.urls"))]
            '''),
        **{f'config/{kind}.py': text(f'''
            import os

            from django.core.{kind} import get_{kind}_application

            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
            application = get_{kind}_application()
            ''') for kind in ('asgi', 'wsgi')},
        'core/__init__.py': '',
        'core/apps.py': text('''
            from django.apps import AppConfig


            class CoreConfig(AppConfig):
                default_auto_field = "django.db.models.BigAutoField"
                name = "core"
            '''),
        'core/models.py': f'"""{MODELS_DOCSTRING[language]}"""\n',
        'core/migrations/__init__.py': '',
        'core/urls.py': text('''
            from django.urls import path

            from core.views import index

            urlpatterns = [path("", index, name="index")]
            '''),
        'core/views.py': text('''
            from django.http import HttpRequest, HttpResponse
            from django.shortcuts import render


            def index(request: HttpRequest) -> HttpResponse:
                return render(request, "core/index.html")
            '''),
        'core/tests.py': text('''
            from django.test import Client


            def test_index(client: Client) -> None:
                response = client.get("/")
                assert response.status_code == 200
                assert "Proyecto preparado" in response.content.decode()
            '''),
        'templates/core/index.html': text('''
            {% load static %}
            <!doctype html>
            <html lang="es">
              <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>Proyecto preparado</title>
                <link rel="stylesheet" href="{% static 'core.css' %}">
              </head>
              <body><main><h1>Proyecto preparado</h1><p>La primera fase puede comenzar.</p></main></body>
            </html>
            '''),
        'static/core.css': 'body { font-family: system-ui, sans-serif; margin: 3rem auto; max-width: 48rem; padding: 1rem; }\n',
        '.gitignore': text('''
            .venv/
            .harness-preparation/
            .django-secret
            db.sqlite3
            db.sqlite3-*
            __pycache__/
            *.py[cod]
            .pytest_cache/
            .ruff_cache/
            .mypy_cache/
            reports/
            .env
            .env.*
            '''),
        'requirements.lock': LOCK,
        'pyproject.toml': text('''
            [project]
            name = "django-local-project"
            version = "0.1.0"
            requires-python = ">=3.11,<3.14"
            dependencies = ["Django==5.2.17"]

            [tool.pytest.ini_options]
            DJANGO_SETTINGS_MODULE = "config.settings"
            python_files = ["test_*.py", "tests.py"]
            testpaths = ["core"]

            [tool.ruff]
            target-version = "py311"
            line-length = 100
            extend-exclude = [".harness-preparation"]

            [tool.ruff.lint]
            select = ["E", "F", "I"]

            [tool.mypy]
            python_version = "3.11"
            strict = true
            plugins = ["mypy_django_plugin.main"]

            [tool.django-stubs]
            django_settings_module = "config.settings"
            '''),
    }


def profile():
    commands = (
        Command(('pytest', '--junitxml=reports/pytest.xml'), timeout_seconds=120),
        Command(('ruff', 'check', '.'), timeout_seconds=60),
        Command(('ruff', 'format', '--check', '.'), timeout_seconds=60),
        Command(('mypy', 'config', 'core', 'manage.py'), timeout_seconds=120),
        Command(('python', 'manage.py', 'check'), timeout_seconds=60),
        Command(('python', 'manage.py', 'makemigrations', '--check', '--dry-run', '--noinput'), timeout_seconds=60),
    )
    return ProjectProfile(name='python-django-recipe', preparation=(), validations=commands,
        allowed_command_prefixes=tuple(c.argv for c in commands),
        protected_paths=('manage.py', 'pyproject.toml', 'requirements.lock', '.gitignore',
                         'config/settings.py', 'config/asgi.py', 'config/wsgi.py', '.harness-preparation/**'),
        sensitive_paths=('.env', '.env.*', '.django-secret', '.venv/**', 'db.sqlite3', 'db.sqlite3-*',
                         '.harness-preparation/**'),
        data_model_paths=('**/models.py', '**/models/**', '**/migrations/**'),
        executor_instructions='Django with SQLite and templates. Use the prepared .venv environment; keep the '
                              'protected configuration files. Model/migration changes update DDBB-DIAGRAM and '
                              'the corresponding flows. Do not install packages or use the network.',
        junit_reports=(JUnitDeclaration(commands[0], 'reports/pytest.xml', 'full'),))


def templates(files):
    """Python files go through startproject/startapp with our literal templates, never Django defaults."""
    result = {}
    for path, content in files.items():
        if path == 'manage.py' or path.startswith('config/'):
            result[f'{WORK}/templates/project/{path}'] = content
        elif path.startswith('core/'):
            result[f'{WORK}/templates/app/{path.removeprefix("core/")}'] = content
    return result


def steps(root, config, mode):
    """Same effects and order as v1; `id` is the stable key, `label` the human description."""
    python = str(root / '.venv/bin/python')
    installer = config['installer_executable']
    environment = {'HOME': str(root / WORK / 'home'), 'TMPDIR': str(root / WORK / 'tmp'),
        'PATH': str(root / '.venv/bin') + ':/usr/bin:/bin', 'LC_ALL': 'C',
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
        'UV_CACHE_DIR': str(root / WORK / 'cache'), 'UV_NO_CONFIG': '1',
        'UV_PYTHON_DOWNLOADS': 'never', 'UV_OFFLINE': '1' if mode == 'offline' else '0',
        'UV_NO_PROGRESS': '1', 'UV_HTTP_RETRIES': '0', 'UV_INDEX_URL': 'https://pypi.org/simple'}
    def command(step, argv, label, timeout=None):
        return {'kind': 'command', 'id': step, 'label': label, 'argv': list(argv), 'cwd': str(root),
                'environment': environment, 'timeout_seconds': timeout or config['timeout_seconds'],
                'max_output_bytes': config['max_output_bytes']}
    install = (installer, '--no-config', 'pip', 'install', '--python', python,
               '--no-python-downloads', '--require-hashes', '--no-deps', '--only-binary', ':all:',
               '--link-mode', 'copy', '--index-url', 'https://pypi.org/simple', '-r', 'requirements.lock')
    if mode == 'offline':
        install += ('--offline',)
        if config.get('wheelhouse'):
            install += ('--no-index', '--find-links', config['wheelhouse'])
    return [
        {'kind': 'files', 'id': 'files', 'label': 'Own templates, lock and local process environment'},
        command('python-version', (config['python_executable'], '--version'), 'Verify base interpreter'),
        command('installer-version', (installer, '--version'), 'Verify uv installer'),
        command('create-environment', (config['python_executable'], '-I', '-m', 'venv', '--without-pip', '.venv'),
                'Create isolated environment'),
        command('install', install, 'Install pinned wheels (no builds or transitive resolution)'),
        command('check-dependencies', (installer, '--no-config', 'pip', 'check', '--python', python, '--offline'),
                'Check dependencies'),
        command('installed-versions', (python, '-I', '-c', 'import importlib.metadata,json,sys; '
                'print(json.dumps({"python":list(sys.version_info[:3]),"packages":'
                '{d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}},sort_keys=True))'),
                'Record installed versions'),
        command('generate-project', (python, '-m', 'django', 'startproject', 'config', f'{WORK}/output',
                                     '--template', f'{WORK}/templates/project'),
                'Generate project from own template'),
        command('generate-app', (python, '-m', 'django', 'startapp', 'core', f'{WORK}/output/core',
                                 '--template', f'{WORK}/templates/app'),
                'Generate base app from own template'),
        {'kind': 'publish', 'id': 'publish', 'label': 'Verify deterministic output and publish new files'},
        command('migrate', (python, 'manage.py', 'migrate', '--noinput'), 'Migrate local SQLite'),
        *[command(f'validate-{number}', (str(root / '.venv/bin' / c.argv[0]), *c.argv[1:]),
                  'Validate: ' + ' '.join(c.argv), c.timeout_seconds)
          for number, c in enumerate(profile().validations, 1)],
        {'kind': 'commit', 'id': 'commit', 'label': 'Technical commit and preparation receipt'},
    ]


def fingerprint(language):
    """Identity of version, work language, scaffold, dependency closure, profile and producer source."""
    import hashlib
    from my_harness.core.engine.contracts import freeze
    language = work_language(language)
    return hashlib.sha256(freeze({'version': VERSION, 'work_language': language, 'files': scaffold(language),
                                 'packages': PACKAGES, 'profile': asdict(profile()),
                                 'implementation': Path(__file__).read_text()}).encode()).hexdigest()
