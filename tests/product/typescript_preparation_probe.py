"""Synthetic node/npm for the TypeScript web recipe (D142). No packages, installs, providers or network.

The operator cache is a test directory: `_cacache/typescript-5.9.3` stands for a cached tarball. Markers in the
cache steer failures, and every call is appended to `probe.jsonl` there, outside the child checkout.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import time

root = Path.cwd()
args = sys.argv[1:]
name = Path(sys.argv[0]).name
cache = Path(os.environ['npm_config_cache'])
with (cache / 'probe.jsonl').open('a') as log:
    log.write(json.dumps([name, args, os.environ.get('npm_config_engine_strict')]) + '\n')
if args == ['--version']:
    print('v24.15.0' if name == 'synthetic-node' else '11.12.1')
elif args[:1] == ['ci']:
    assert os.environ.get('npm_config_engine_strict') == 'true' and '--ignore-scripts' in args, args
    lock = json.loads((root / 'package-lock.json').read_text())
    assert lock['packages']['node_modules/typescript']['version'] == '5.9.3'
    modules = root / 'node_modules'
    if (cache / 'pause').exists():
        time.sleep(30)
    if (cache / 'partial').exists():
        (modules / 'typescript').mkdir(parents=True)
        (modules / 'typescript/partial').write_text('synthetic interrupted extraction')
        sys.exit(1)
    if '--offline' in args and not (cache / '_cacache/typescript-5.9.3').exists():
        print("npm error code ENOTCACHED", file=sys.stderr)
        sys.exit(1)
    if '--offline' not in args:
        (cache / '_cacache').mkdir(exist_ok=True)
        (cache / '_cacache/typescript-5.9.3').write_text('synthetic downloaded tarball')
    shutil.rmtree(modules, ignore_errors=True)
    (modules / 'typescript/bin').mkdir(parents=True)
    (modules / 'typescript/package.json').write_text('{"name": "typescript", "version": "5.9.3"}\n')
    (modules / 'typescript/bin/tsc').write_text('synthetic compiler\n')
    (modules / '.bin').mkdir()
    (modules / '.bin/tsc').symlink_to('../typescript/bin/tsc')
    (modules / '.package-lock.json').write_text(json.dumps(lock))
    print('added 1 package')
elif args[:1] == ['run']:
    if not (root / 'node_modules/typescript/package.json').exists():
        print('tsc: command not found', file=sys.stderr)
        sys.exit(127)
    sources = ''.join(path.read_text() for path in sorted((root / 'src').glob('*.ts')))
    if 'SYNTHETIC_TYPE_ERROR' in sources:
        print('src/main.ts: error TS2322', file=sys.stderr)
        sys.exit(2)
    script = args[1]
    if script in ('test', 'build'):
        (root / '.build').mkdir(exist_ok=True)
        (root / '.build/main.js').write_text(sources)
    if script == 'test':
        (root / '.local').mkdir(exist_ok=True)
        # `bad-junit` models a runner that exits 0 although its report records a failure.
        failure = '<failure message="synthetic"/>' if (cache / 'bad-junit').exists() else ''
        (root / '.local/junit.xml').write_text(
            '<testsuites><testsuite name="tests/main.test.mjs"><testcase name="names the prepared project">'
            + failure + '</testcase></testsuite></testsuites>')
    if script == 'build':
        (root / 'dist').mkdir(exist_ok=True)
        shutil.copyfile(root / '.build/main.js', root / 'dist/main.js')
        shutil.copyfile(root / 'index.html', root / 'dist/index.html')
else:
    print(f'unexpected synthetic call {name} {args}', file=sys.stderr)
    sys.exit(64)
