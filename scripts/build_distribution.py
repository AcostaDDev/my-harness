"""Offline local build: UI from the lock, sdist/wheel, `pylock.toml` installation pins and SHA256SUMS."""
import argparse
import hashlib
import os
import sys
import tomllib
from pathlib import Path
import shutil
import subprocess
import tempfile

from toolchain import check_tools
from distribution_artifacts import BUNDLE_SCRIPTS, write_manifest

ROOT = Path(__file__).resolve().parents[1]
# Files besides `src/` that enter the sdist; the license files also enter the wheel (`license-files`).
PROJECT_FILES = ('pyproject.toml', 'README.md', 'LICENSE', 'NOTICE.md', 'NOTICE-THIRD-PARTY.md')
# Every packaged source has one of these suffixes; anything else under src/ stops the build.
SOURCE_SUFFIXES = {'.py', '.md', '.json', '.lock', '.mako'}


def package_sources():
    """Relative paths under src/ that the package carries, without caches or unexpected files."""
    sources, unexpected = [], []
    for path in sorted((ROOT / 'src').rglob('*')):
        relative = path.relative_to(ROOT / 'src')
        if '__pycache__' in relative.parts or path.suffix == '.pyc' or path.is_dir():
            continue
        if path.is_symlink() or not path.is_file() or path.suffix not in SOURCE_SUFFIXES or path.name.startswith('.'):
            unexpected.append(str(relative))
        else:
            sources.append(relative)
    if unexpected:
        raise SystemExit('Unexpected files under src/ (remove them before building): ' + ', '.join(unexpected))
    return sources


def write_checksums(output):
    sums = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(output).as_posix()}\n'
            for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS']
    (output / 'SHA256SUMS').write_text(''.join(sums))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--cache-dir', type=Path, help='Cache root with uv/ and npm/; default preserves development caches')
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--uv', default='uv')
    network = parser.add_mutually_exclusive_group()
    network.add_argument('--offline', action='store_true', help='Default: never access the network')
    network.add_argument('--allow-network', action='store_true', help='Allow locked npm/Python dependency downloads')
    args = parser.parse_args()
    cache = args.cache_dir.resolve() if args.cache_dir else None
    os.environ['UV_CACHE_DIR'] = str(cache / 'uv') if cache else os.environ.get('UV_CACHE_DIR', str(ROOT / '.local/uv-cache'))
    npm_cache = cache / 'npm' if cache else ROOT / '.local/npm-cache'
    os.environ['UV_PYTHON'] = args.python
    os.environ['UV_PYTHON_DOWNLOADS'] = 'never'
    mode = [] if args.allow_network else ['--offline']
    output = args.out_dir.resolve()
    # Old artifacts are never mixed with a new build.
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f'{output} is not empty; choose a new or empty output directory')
    output.mkdir(parents=True, exist_ok=True)
    check_tools(args.uv)
    sources = package_sources()
    subprocess.run(['npm', 'ci', *mode, '--ignore-scripts', '--no-audit', '--no-fund', '--cache', str(npm_cache)],
                   cwd=ROOT / 'frontend', check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'frontend', check=True)
    with tempfile.TemporaryDirectory(prefix='harness-package-') as temporary:
        stage = Path(temporary)
        for name in PROJECT_FILES:
            shutil.copy2(ROOT / name, stage)
        for relative in sources:
            (stage / 'src' / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / 'src' / relative, stage / 'src' / relative)
        shutil.copytree(ROOT / 'frontend/dist', stage / 'src/my_harness/web')
        subprocess.run([args.uv, 'build', *mode, '--no-create-gitignore', '--no-python-downloads', '--python', args.python, '--out-dir', str(output), str(stage)],
                       cwd=ROOT, check=True)
    # PEP 751 lock with the URL and hash of every wheel: it installs offline from the cache filled by `uv sync`, which
    # a requirements file cannot (it needs the index metadata). Without the header, which would record the output path.
    subprocess.run([args.uv, 'export', '--frozen', '--offline', '--no-dev', '--no-emit-project', '--no-header',
                    '--format', 'pylock.toml', '--output-file', str(output / 'pylock.toml')],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    write_checksums(output)
    from check_distribution import check_checkout_artifacts
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    check_checkout_artifacts(output, project)
    (output / 'scripts').mkdir()
    for name in BUNDLE_SCRIPTS:
        source = ROOT / ('tests/fixtures/e2e' if name == 'installed_config.py' else 'scripts') / name
        shutil.copy2(source, output / 'scripts' / name)
    write_manifest(output, project)
    write_checksums(output)


if __name__ == '__main__':
    main()
