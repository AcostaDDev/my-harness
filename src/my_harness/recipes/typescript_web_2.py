"""TypeScript web recipe 2 (P011-T004, D163). Data-only plan construction; no process or checkout reads.

Maintained successor of the frozen `typescript-web-recipe-1`, which keeps its bytes and the built-in
`typescript-web` profile for issued receipts. The profile is declared here, so later edits to the built-in one never
change this identity. Test descriptions follow the work language; the application's functional defaults
(`<html lang>` and visible text) keep the v1 values (P011-T001 §5). Steps carry a stable `id`; their `label` is
human prose. Selected by `local-config-6` (P011-T020, D168).
"""
import json
from dataclasses import asdict
from pathlib import Path
from textwrap import dedent

from my_harness.core.engine.context import Command, JUnitDeclaration, ProjectProfile

VERSION = 'typescript-web-recipe-2'
WORK_LANGUAGES = ('en', 'es')
WORK = '.harness-preparation'
REGISTRY = 'https://registry.npmjs.org/'
TYPESCRIPT = {'version': '5.9.3', 'resolved': 'https://registry.npmjs.org/typescript/-/typescript-5.9.3.tgz',
              'integrity': 'sha512-jl1vZzPDinLr9eUt3J/t7V6FgNEw9QjvBPdysz9KfQDD41fQrC2Y4vKQdiaUpFT4bXlb1RHhLpp8wtm6M5TgSw=='}
# Ignored and local: dependencies, compiler/build output, JUnit and the preparation's private HOME/TMPDIR.
LOCAL = ('node_modules/', '.build/', 'dist/', '.local/', WORK + '/')
TEST_NAME = {'en': 'names the prepared project', 'es': 'nombra el proyecto preparado'}


def text(value):
    return dedent(value).lstrip('\n')


def document(value):
    return json.dumps(value, indent=2) + '\n'


def work_language(value):
    if value not in WORK_LANGUAGES:
        raise ValueError(f'Unsupported work language: {value!r}')
    return value


def manifest(project_id, config, language):
    """The whole technical commit. Only the package name, the exact engines and test prose vary."""
    language = work_language(language)
    engines = {'node': config['node_version'], 'npm': config['npm_version']}
    return {
        'package.json': document({
            'name': project_id, 'version': '0.1.0', 'private': True, 'type': 'module', 'engines': engines,
            'scripts': {'check': 'tsc --noEmit', 'test': 'tsc && node scripts/test.mjs',
                        'build': 'tsc && node scripts/build.mjs'},
            'devDependencies': {'typescript': TYPESCRIPT['version']}}),
        'package-lock.json': document({
            'name': project_id, 'version': '0.1.0', 'lockfileVersion': 3, 'requires': True,
            'packages': {
                '': {'name': project_id, 'version': '0.1.0',
                     'devDependencies': {'typescript': TYPESCRIPT['version']}, 'engines': engines},
                'node_modules/typescript': {
                    **TYPESCRIPT, 'dev': True, 'license': 'Apache-2.0',
                    'bin': {'tsc': 'bin/tsc', 'tsserver': 'bin/tsserver'}, 'engines': {'node': '>=14.17'}}}}),
        'tsconfig.json': document({
            'compilerOptions': {'target': 'ES2022', 'module': 'NodeNext', 'moduleResolution': 'NodeNext',
                                'lib': ['ES2022', 'DOM'], 'strict': True, 'noEmitOnError': True,
                                'rootDir': 'src', 'outDir': '.build'},
            'include': ['src/**/*.ts']}),
        '.gitignore': ''.join(f'{path}\n' for path in (*LOCAL, '.env', '.env.*')),
        'scripts/test.mjs': text('''
            import { mkdirSync, readdirSync } from 'node:fs';
            import { spawnSync } from 'node:child_process';

            mkdirSync('.local', { recursive: true });
            const files = readdirSync('tests').filter(name => name.endsWith('.test.mjs')).sort().map(name => `tests/${name}`);
            const result = spawnSync(process.execPath, ['--test', '--test-reporter=tap', '--test-reporter=junit',
              '--test-reporter-destination=stdout', '--test-reporter-destination=.local/junit.xml', ...files], { stdio: 'inherit' });
            process.exit(result.status ?? 1);
            '''),
        'scripts/build.mjs': text('''
            import { copyFile, mkdir } from "node:fs/promises";

            await mkdir("dist", { recursive: true });
            await copyFile(".build/main.js", "dist/main.js");
            await copyFile("index.html", "dist/index.html");
            console.log("Built static web application in dist/");
            '''),
        'index.html': text('''
            <!doctype html>
            <html lang="es">
              <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>Proyecto local</title>
              </head>
              <body>
                <h1>Proyecto local</h1>
                <script type="module" src="./main.js"></script>
              </body>
            </html>
            '''),
        'src/main.ts': text('''
            export function heading(title: string): string {
              return `${title.trim() || "Proyecto"} preparado`;
            }

            if (typeof document !== "undefined") {
              const element = document.querySelector("h1");
              if (element) element.textContent = heading(document.title);
            }
            '''),
        'tests/main.test.mjs': text(f'''
            import assert from "node:assert/strict";
            import test from "node:test";
            import {{ heading }} from "../.build/main.js";

            test("{TEST_NAME[language]}", () => {{
              assert.equal(heading("Proyecto local"), "Proyecto local preparado");
              assert.equal(heading("  "), "Proyecto preparado");
            }});
            '''),
    }


def profile():
    test = Command(('npm', 'run', 'test'), timeout_seconds=120)
    return ProjectProfile(
        name='typescript-web',
        preparation=(
            Command(('node', '--version'), timeout_seconds=30),
            Command(('npm', '--version'), timeout_seconds=30),
            Command(('npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund'),
                    environment=(('npm_config_engine_strict', 'true'),), timeout_seconds=120),
        ),
        validations=tuple(Command(('npm', 'run', script), timeout_seconds=120)
                          for script in ('check', 'test', 'build')),
        allowed_command_prefixes=(('npm', 'run', 'check'), ('npm', 'run', 'test'), ('npm', 'run', 'build')),
        junit_reports=(JUnitDeclaration(test, '.local/junit.xml',
                                        'Node tests from tests/*.test.mjs; no code coverage'),),
        # D088 point 6: the executor may maintain product documentation, diagrams, `docs/flows/` and `docs/phase/`
        # if its contract includes them; control documents belong to the harness.
        protected_paths=('docs/STATE.md', 'docs/NEXT_STEPS.md', 'docs/ROADMAP.md', 'docs/DECISIONS.md',
                         'docs/archive/**', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
                         '.harness/**', '.codex/**', '.claude/**', 'package.json', 'package-lock.json',
                         'tsconfig.json', 'scripts/**', 'tests/**', '.gitignore'),
        sensitive_paths=('.env', '.env.*', '**/.env', '**/.env.*', '*.pem', '*.key', '*.p12', '*.pfx', 'id_rsa*'),
        sensitive_allowlist=('.env.example',),
        executor_instructions=(
            'Implement the static TypeScript web application within the frozen task paths. '
            'Use the existing npm run check, npm run test and npm run build scripts. '
            'Do not weaken tests, compiler settings, scripts or the dependency lock. '
            'Keep node_modules, .build, dist and the npm cache ignored. '
            'Preparation uses an already populated, explicitly configured npm cache offline; '
            'a cache miss stops the task. Dependency downloads, configuration changes and '
            'network access require separate authorization. Command prefixes do not grant '
            'agent tools or provide a sandbox.'
        ),
    )


def steps(root, config, mode):
    """Same effects and order as v1; `id` is the stable key, `label` the human description."""
    work = root / WORK
    environment = {'HOME': str(work / 'home'), 'TMPDIR': str(work / 'tmp'),
        'PATH': str(Path(config['node_executable']).parent) + ':/usr/bin:/bin', 'LC_ALL': 'C', 'CI': 'true',
        'npm_config_cache': config['npm_cache'], 'npm_config_registry': REGISTRY,
        'npm_config_engine_strict': 'true', 'npm_config_fetch_retries': '0',
        # npm refuses one file as both user and global configuration; both stay empty inside the child.
        'npm_config_userconfig': str(work / 'user.npmrc'), 'npm_config_globalconfig': str(work / 'global.npmrc'),
        'npm_config_update_notifier': 'false', 'npm_config_audit': 'false', 'npm_config_fund': 'false'}
    def command(step, argv, label, timeout=None):
        return {'kind': 'command', 'id': step, 'label': label, 'argv': list(argv), 'cwd': str(root),
                'environment': environment, 'timeout_seconds': timeout or config['timeout_seconds'],
                'max_output_bytes': config['max_output_bytes']}
    npm = config['npm_executable']
    install = (npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund') + (('--offline',) if mode == 'offline' else ())
    return [
        {'kind': 'files', 'id': 'files', 'label': 'Packaged manifest and local process environment'},
        command('node-version', (config['node_executable'], '--version'), 'Verify Node'),
        command('npm-version', (npm, '--version'), 'Verify npm'),
        command('install', install, 'Install the lock\'s pinned dependencies (no scripts)'),
        *[command(f'validate-{number}', (npm, *c.argv[1:]), 'Validate: ' + ' '.join(c.argv), c.timeout_seconds)
          for number, c in enumerate(profile().validations, 1)],
        {'kind': 'commit', 'id': 'commit', 'label': 'Technical commit and preparation receipt'},
    ]


def fingerprint(language):
    """Identity of version, work language, manifest, profile and producer source."""
    import hashlib
    from my_harness.core.engine.contracts import freeze
    language = work_language(language)
    sample = manifest('project', {'node_version': 'node', 'npm_version': 'npm'}, language)
    return hashlib.sha256(freeze({'version': VERSION, 'work_language': language, 'files': sample,
                                 'profile': asdict(profile()),
                                 'implementation': Path(__file__).read_text()}).encode()).hexdigest()
