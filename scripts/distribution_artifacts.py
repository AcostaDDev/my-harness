"""Self-contained distribution verification; no source checkout or third-party imports."""
import email.parser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tomllib
import zipfile

BUNDLE_SCRIPTS = ('install', 'install.py', 'start', 'start.py', 'toolchain.py', 'distribution_artifacts.py',
                  'check_distribution.py', 'installed_config.py')
MANIFEST = 'distribution-1.json'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '..' not in path.parts and str(path) == name


def archive_members(path):
    """Read, never extract: reject ambiguous names, duplicates and special/link members."""
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            assert len({m.filename for m in members}) == len(members), 'Duplicate wheel members'
            assert all(safe_name(m.filename.rstrip('/')) and
                       stat.S_IFMT(m.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR) for m in members)
            return {m.filename: digest(archive.read(m)) for m in members if not m.is_dir()}
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        assert len({m.name for m in members}) == len(members), 'Duplicate sdist members'
        assert all(safe_name(m.name) and (m.isfile() or m.isdir()) for m in members), 'Unsafe sdist member'
        return {m.name: digest(archive.extractfile(m).read()) for m in members if m.isfile()}


def write_manifest(distribution, project):
    """Called only after the build has compared the artifacts to the checkout's expected bytes."""
    manifest = {'format': 'distribution-1', 'project': project,
                'members': {p.name: archive_members(p) for p in sorted(distribution.iterdir())
                            if p.suffix == '.whl' or p.name.endswith('.tar.gz')}}
    (distribution / MANIFEST).write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')


def check_artifacts(distribution):
    """Verify every delivered file, exact archive members, metadata and pinned dependency hashes."""
    if not __debug__:
        raise ValueError('Artifact verification requires Python without -O')
    distribution = Path(distribution)
    assert distribution.is_dir() and not distribution.is_symlink(), 'Expected a regular distribution directory'
    files = set()
    for path in distribution.rglob('*'):
        assert not path.is_symlink(), f'Symlink in distribution: {path}'
        if not path.is_dir():
            assert path.is_file(), f'Special file in distribution: {path}'
            files.add(path.relative_to(distribution).as_posix())
    sums = {}
    for line in (distribution / 'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split('  ', 1)
        assert safe_name(name) and name not in sums and re.fullmatch('[a-f0-9]{64}', checksum), name
        sums[name] = checksum
    manifest = json.loads((distribution / MANIFEST).read_text())
    assert manifest['format'] == 'distribution-1'
    project = manifest['project']
    name, version = project['name'].replace('-', '_'), project['version']
    assert name == 'my_harness' and re.fullmatch(r'\d+\.\d+\.\d+(?:[a-z0-9.]+)?', version)
    wheel_name, sdist_name = f'{name}-{version}-py3-none-any.whl', f'{name}-{version}.tar.gz'
    expected = {wheel_name, sdist_name, 'pylock.toml', MANIFEST} | {'scripts/' + s for s in BUNDLE_SCRIPTS}
    assert set(sums) == expected, 'Unexpected or missing distribution files'
    assert files == expected | {'SHA256SUMS'}, 'Distribution contains unlisted files'
    for file, checksum in sums.items():
        assert digest((distribution / file).read_bytes()) == checksum, f'Checksum mismatch: {file}'
    assert set(manifest['members']) == {wheel_name, sdist_name}
    for file, members in manifest['members'].items():
        assert archive_members(distribution / file) == members, f'Archive members mismatch: {file}'
    info = f'{name}-{version}.dist-info/'
    with zipfile.ZipFile(distribution / wheel_name) as wheel:
        metadata = email.parser.BytesParser().parsebytes(wheel.read(info + 'METADATA'))
        assert (metadata['Name'], metadata['Version'], metadata['License-Expression']) == (
            project['name'], version, project['license'])
        assert metadata['Requires-Python'].replace(' ', '') == project['requires-python']
        assert metadata.get_all('Requires-Dist') == project['dependencies']
        licenses = ('LICENSE', 'NOTICE.md', 'NOTICE-THIRD-PARTY.md')
        assert sorted(metadata.get_all('License-File')) == sorted(licenses)
        for license in licenses:
            assert wheel.read(info + 'licenses/' + license)
        assert b'<div id="root">' in wheel.read('my_harness/web/index.html')
        assert any(m.startswith('my_harness/migrations/versions/') for m in wheel.namelist())
        assert f'version="{version}"' in wheel.read('my_harness/api/app.py').decode()
    pins = tomllib.loads((distribution / 'pylock.toml').read_text())
    packages = pins['packages']
    assert packages and project['name'] not in {p['name'] for p in packages}
    for package in packages:
        assert package['version'] and package.get('wheels'), 'Unpinned dependency'
        assert not set(package) & {'directory', 'vcs', 'archive'}, 'Non-registry dependency'
        for wheel in package['wheels']:
            assert re.fullmatch('[a-f0-9]{64}', wheel['hashes']['sha256'])
            assert wheel['url'].startswith('https://'), 'Dependency must use HTTPS'
    for dependency in project['dependencies']:
        dependency_name, dependency_version = dependency.split('==')
        assert any(p['name'] == dependency_name and p['version'] == dependency_version for p in packages)
    return manifest
