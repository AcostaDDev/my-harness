"""Quiet development checks (OT008): the AGENTS command sets with compact output.

Usage: scripts/check [PATH ...] [--suite NAME ...] [--frontend] [-- PYTEST_ARGS ...]

Without PATH it runs the full pytest suite, unittest and `alembic check`; with PATH only pytest over those paths.
`--frontend` adds the Node tests and `npm run build` (which runs `npm run check` first). Each suite prints one line
with its counts and, on failure, the failing IDs with their first error line. The complete output of each suite is
written to `.local/check/<suite>.log`. Offline: uv runs `--frozen --offline` with `.local/uv-cache`, and
`alembic check` only touches a temporary SQLite database. Standard library only; never edits the tree.
"""
import argparse
import glob
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / '.local/check'
UV = ('uv', 'run', '--frozen', '--offline')
SUITES = ('unittest', 'alembic', 'pytest', 'node', 'build')
DEFAULT, FRONTEND = ('unittest', 'alembic', 'pytest'), ('node', 'build')
MAX_FAILURES, MAX_LINE = 20, 200


def environment(**extra):
    env = dict(os.environ, UV_CACHE_DIR=str(ROOT / '.local/uv-cache'), COLUMNS='400', NO_COLOR='1')
    env.pop('FORCE_COLOR', None)
    return env | extra


def clip(text):
    text = ' '.join(text.split())
    return text if len(text) <= MAX_LINE else text[:MAX_LINE - 1] + '…'


class Result:
    def __init__(self, suite, ok, counts, failures=(), seconds=0.0):
        self.suite, self.ok, self.counts, self.failures, self.seconds = suite, ok, counts, list(failures), seconds

    def lines(self, log):
        head = f"{self.suite}: {'ok' if self.ok else 'FAILED'}" + (f' — {self.counts}' if self.counts else '')
        lines = [f'{head} ({self.seconds:.1f}s)']
        for test_id, message in self.failures[:MAX_FAILURES]:
            lines.append(f'  {clip(test_id)}' + (f' — {clip(message)}' if message else ''))
        if len(self.failures) > MAX_FAILURES:
            lines.append(f'  … {len(self.failures) - MAX_FAILURES} more')
        if not self.ok:
            lines.append(f'  log: {log.relative_to(ROOT)}')
        return lines


def parse_pytest(output, returncode):
    summary = next((line for line in reversed(output.splitlines()) if re.match(r'^=+ .* in [\d.]+s', line)
                    or re.match(r'^\d+ \w+.* in [\d.]+s', line)), '')
    counts = re.sub(r'^=+ | in [\d.]+s.*$', '', summary).strip()
    failures = []
    for line in output.splitlines():
        match = re.match(r'^(FAILED|ERROR) (\S+)(?: - (.*))?$', line)
        if match:
            failures.append((f'{match[1]} {match[2]}', match[3] or ''))
    if returncode and not failures:
        failures.append(('pytest', last_line(output)))
    return returncode == 0, counts or f'exit {returncode}', failures


def parse_unittest(output, returncode):
    ran = re.search(r'^Ran (\d+) tests?', output, re.M)
    status = re.search(r'^(OK|FAILED)(?: \((.*)\))?$', output, re.M)
    counts = ', '.join(part for part in ((f'{ran[1]} ran' if ran else ''), (status[2] or '') if status else '') if part)
    failures = []
    for block in re.split(r'^=+$', output, flags=re.M)[1:]:
        header = re.match(r'\s*(FAIL|ERROR): (.+)', block)
        if not header:
            continue
        body = block.split('Traceback (most recent call last):')[-1].splitlines()
        message = next((line for line in body if line and not line[0].isspace() and not line.startswith('-')), '')
        failures.append((f'{header[1]} {header[2].strip()}', message))
    if returncode and not failures:
        failures.append(('unittest', last_line(output)))
    return returncode == 0, counts or f'exit {returncode}', failures


def parse_node(output, returncode):
    totals = dict(re.findall(r'^# (tests|pass|fail|skipped|cancelled|todo) (\d+)$', output, re.M))
    counts = ', '.join(f'{totals[k]} {k}' for k in ('tests', 'pass', 'fail', 'skipped', 'cancelled')
                       if k in totals and (k in ('tests', 'pass') or totals[k] != '0'))
    failures, lines = [], output.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'^\s*not ok \d+ - (.*)$', line)
        if not match:
            continue
        location, message = '', ''
        for position in range(index + 1, len(lines)):
            field = re.match(r'^\s*(location|error|\.\.\.)(?:: (.*))?$', lines[position])
            if field and field[1] == '...':
                break
            if field and field[1] == 'location':
                location = Path(field[2].strip("'").rsplit(':', 2)[0]).name
            elif field and field[1] == 'error' and not message:
                value = field[2] or ''
                if value.startswith('|'):  # YAML block: the message starts on the next non-empty line
                    value = next((text.strip() for text in lines[position + 1:] if text.strip()), '')
                message = value.strip('\'"')
        failures.append((f'{location} › {match[1]}' if location else match[1], message))
    if returncode and not failures:
        failures.append(('node', last_line(output)))
    return returncode == 0, counts or f'exit {returncode}', failures


def parse_build(output, returncode):
    errors = [(match[1], match[2]) for match in re.finditer(r'^(\S+\(\d+,\d+\)): error (.*)$', output, re.M)]
    if returncode and not errors:
        errors.append(('build', last_line(output)))
    built = re.search(r'built in ([\d.]+\s?m?s)', output)
    return returncode == 0, (f'tsc + vite built in {built[1]}' if built else '') or ('' if returncode else 'ok'), errors


def parse_alembic(output, returncode):
    if returncode == 0 and 'No new upgrade operations detected' in output:
        return True, 'no new upgrade operations', []
    return False, f'exit {returncode}', [('alembic', last_line(output))]


def last_line(output):
    return next((line for line in reversed(output.splitlines()) if line.strip()), 'no output')


def execute(command, log, env, append=False):
    with open(log, 'a' if append else 'w') as stream:
        stream.write('$ ' + ' '.join(command) + '\n')
        stream.flush()
        try:
            completed = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, text=True,
                                       stdin=subprocess.DEVNULL)
        except OSError as error:
            stream.write(f'{error}\n')
            return 127
    return completed.returncode


def run_suite(suite, paths, pytest_args, log):
    env = environment()
    if suite == 'pytest':
        returncode = execute([*UV, 'pytest', '-q', '-rfE', '--color=no', *paths, *pytest_args], log, env)
        parse = parse_pytest
    elif suite == 'unittest':
        returncode = execute([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'], log, env)
        parse = parse_unittest
    elif suite == 'alembic':
        # Never the development database: HARNESS_DATABASE_URL points at a fresh temporary file.
        with tempfile.TemporaryDirectory(prefix='harness-check-') as directory:
            env = environment(HARNESS_DATABASE_URL=f'sqlite:///{Path(directory) / "check.sqlite3"}')
            returncode = execute([*UV, 'alembic', 'upgrade', 'head'], log, env)
            if returncode == 0:
                returncode = execute([*UV, 'alembic', 'check'], log, env, append=True)
        parse = parse_alembic
    elif suite == 'node':
        tests = sorted(glob.glob(str(ROOT / 'frontend/tests/*.test.mjs')))
        returncode = execute(['node', '--test', '--test-reporter=tap', *tests], log, env)
        parse = parse_node
    else:
        returncode = execute(['npm', '--prefix', 'frontend', 'run', 'build'], log, env)
        parse = parse_build
    return parse(log.read_text(errors='replace'), returncode)


def selected_suites(args):
    if args.suite:
        return [suite for suite in SUITES if suite in args.suite]
    suites = ['pytest'] if args.paths else list(DEFAULT)
    return suites + (list(FRONTEND) if args.frontend else [])


def parse_arguments(argv):
    argv = list(argv)
    pytest_args = argv[argv.index('--') + 1:] if '--' in argv else []
    argv = argv[:argv.index('--')] if '--' in argv else argv
    parser = argparse.ArgumentParser(prog='scripts/check', description=__doc__.split('\n\n')[0])
    parser.add_argument('paths', nargs='*', help='pytest paths or node IDs; only pytest runs when given')
    parser.add_argument('--suite', action='append', choices=SUITES, help='run only these suites (repeatable)')
    parser.add_argument('--frontend', action='store_true', help='also run the Node tests and the frontend build')
    args = parser.parse_args(argv)
    args.pytest_args = pytest_args
    return args


def main(argv=None):
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    if shutil.which('uv') is None and {'pytest', 'alembic'} & set(selected_suites(args)):
        print('check: uv is not available', file=sys.stderr)
        return 2
    LOGS.mkdir(parents=True, exist_ok=True)
    ok = True
    for suite in selected_suites(args):
        # A private file per run, renamed when done, so that concurrent runs never interleave one log.
        log, private = LOGS / f'{suite}.log', LOGS / f'{suite}.{os.getpid()}.log'
        started = time.monotonic()
        try:
            passed, counts, failures = run_suite(suite, args.paths, args.pytest_args, private)
        finally:
            if private.exists():
                os.replace(private, log)
        result = Result(suite, passed, counts, failures, time.monotonic() - started)
        print('\n'.join(result.lines(log)), flush=True)
        ok = ok and passed
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
