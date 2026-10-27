"""TypeScript web recipe 1 (D142). Data-only plan construction; no process or checkout reads."""
import json
from pathlib import Path
from textwrap import dedent

from my_harness.profiles.typescript_web import typescript_web_profile

VERSION = 'typescript-web-recipe-1'
WORK = '.harness-preparation'
REGISTRY = 'https://registry.npmjs.org/'
TYPESCRIPT = {'version': '5.9.3', 'resolved': 'https://registry.npmjs.org/typescript/-/typescript-5.9.3.tgz',
              'integrity': 'sha512-jl1vZzPDinLr9eUt3J/t7V6FgNEw9QjvBPdysz9KfQDD41fQrC2Y4vKQdiaUpFT4bXlb1RHhLpp8wtm6M5TgSw=='}
# Ignored and local: dependencies, compiler/build output, JUnit and the preparation's private HOME/TMPDIR.
LOCAL = ('node_modules/', '.build/', 'dist/', '.local/', WORK + '/')


def text(value):
    return dedent(value).lstrip('\n')


def document(value):
    return json.dumps(value, indent=2) + '\n'


def manifest(project_id, config):
    """The whole technical commit. Only the package name and the exact engines vary."""
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
        'tests/main.test.mjs': text('''
            import assert from "node:assert/strict";
            import test from "node:test";
            import { heading } from "../.build/main.js";

            test("names the prepared project", () => {
              assert.equal(heading("Proyecto local"), "Proyecto local preparado");
              assert.equal(heading("  "), "Proyecto preparado");
            });
            '''),
    }


def profile():
    return typescript_web_profile()


def steps(root, config, mode):
    work = root / WORK
    environment = {'HOME': str(work / 'home'), 'TMPDIR': str(work / 'tmp'),
        'PATH': str(Path(config['node_executable']).parent) + ':/usr/bin:/bin', 'LC_ALL': 'C', 'CI': 'true',
        'npm_config_cache': config['npm_cache'], 'npm_config_registry': REGISTRY,
        'npm_config_engine_strict': 'true', 'npm_config_fetch_retries': '0',
        # npm refuses one file as both user and global configuration; both stay empty inside the child.
        'npm_config_userconfig': str(work / 'user.npmrc'), 'npm_config_globalconfig': str(work / 'global.npmrc'),
        'npm_config_update_notifier': 'false', 'npm_config_audit': 'false', 'npm_config_fund': 'false'}
    def command(argv, label, timeout=None):
        return {'kind': 'command', 'label': label, 'argv': list(argv), 'cwd': str(root),
                'environment': environment, 'timeout_seconds': timeout or config['timeout_seconds'],
                'max_output_bytes': config['max_output_bytes']}
    npm = config['npm_executable']
    install = (npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund') + (('--offline',) if mode == 'offline' else ())
    return [
        {'kind': 'files', 'label': 'Manifiesto empaquetado y entorno local de procesos'},
        command((config['node_executable'], '--version'), 'Verificar Node'),
        command((npm, '--version'), 'Verificar npm'),
        command(install, 'Instalar dependencias fijadas del lock (sin scripts)'),
        *[command((npm, *c.argv[1:]), 'Validar: ' + ' '.join(c.argv), c.timeout_seconds)
          for c in profile().validations],
        {'kind': 'commit', 'label': 'Commit técnico y recibo de preparación'},
    ]


def fingerprint():
    from dataclasses import asdict
    import hashlib
    from my_harness.core.engine.contracts import freeze
    sample = manifest('project', {'node_version': 'node', 'npm_version': 'npm'})
    return hashlib.sha256(freeze({'files': sample, 'profile': asdict(profile()),
                                 'implementation': Path(__file__).read_text()}).encode()).hexdigest()
