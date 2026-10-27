"""Local-object Git boundary shared by onboarding and project preparation."""
from hashlib import sha256

from my_harness.adapters.git import Git
from my_harness.adapters.local_git import object_size
from my_harness.core.tree import ImportInventoryError
from my_harness.i18n import tr

READABLE_MODES = ('100644', '100755')

def _tree(git: Git, revision: str = 'HEAD') -> list[tuple[str, str, str, int | None, str]]:
    """(mode, type, object, size, path) of a tree, without quoting paths (`-z`)."""
    rows = []
    for record in git.run('ls-tree', '-r', '-z', '-l', '--full-tree', revision).split(b'\0'):
        if not record:
            continue
        header, _, raw_path = record.partition(b'\t')
        mode, kind, obj, size = header.decode('ascii').split()
        path = raw_path.decode('utf-8')
        rows.append((mode, kind, obj, object_size(size, kind, obj, path), path))
    return rows


def _blobs(git: Git, objects: list[str]) -> dict[str, bytes]:
    """Exact blob content with `cat-file --batch`, which applies no filters or textconv."""
    if not objects:
        return {}
    output = git.run('cat-file', '--batch', input=('\n'.join(objects) + '\n').encode('ascii'))
    found, offset = {}, 0
    for obj in objects:
        end = output.find(b'\n', offset)
        if end == -1:
            raise ImportInventoryError(tr('git.git_object_has_incomplete', obj=obj))
        header = output[offset:end].decode('ascii').split()
        if len(header) != 3 or header[0] != obj or header[1] != 'blob':
            raise ImportInventoryError(tr('git.git_object_missing_could', obj=obj))
        if not header[2].isascii() or not header[2].isdecimal():
            raise ImportInventoryError(tr('git.git_object_has_unavailable', obj=obj))
        size = int(header[2])
        if output[end + 1 + size:end + 2 + size] != b'\n':
            raise ImportInventoryError(tr('git.git_object_has_incomplete_2', obj=obj))
        found[obj] = output[end + 1:end + 1 + size]
        offset = end + 1 + size + 1
    return found


def check_filters(git: Git):
    """Before status/add/hash-object: config reads includes, but never runs the filters."""
    if git.run('config', '--includes', '--get-regexp', r'^filter\..*\.(clean|process)$', ok=(0, 1)).strip():
        raise ImportInventoryError(tr('git.import_requires_no_local'))


def check_submodules(git: Git):
    """Rejects gitlinks in HEAD or the index before status/add, without querying the child repository."""
    for source, args in (
        ('HEAD', ('ls-tree', '-r', '-z', '--full-tree', 'HEAD')),
        ('index', ('ls-files', '--stage', '-z')),
    ):
        for record in git.run(*args).split(b'\0'):
            header, _, path = record.partition(b'\t')
            if header.startswith(b'160000 '):
                raise ImportInventoryError(
                    tr('git.import_does_not_support', path=repr(path.decode('utf-8', 'replace')), source=source))


def check_tree(git: Git, tree: str, expected: list[dict], documents: list[dict]):
    """A/B guards before confirming or writing, including archive, binaries and partial recovery."""
    destinations = b''.join(doc['path'].encode() + b'\0' for doc in documents
                            if doc['before_sha256'] is None and doc['after_sha256'] is not None)
    if destinations and git.run('check-ignore', '-z', '--stdin', input=destinations, ok=(0, 1)).strip(b'\0'):
        raise ValueError(tr('git.import_document_destinations_ignored'))
    entries = {path: (mode, obj) for mode, _, obj, _, path in _tree(git, tree)}
    if any(item['path'] not in entries or entries[item['path']][0] not in READABLE_MODES for item in expected):
        raise ValueError(tr('git.sealed_import_tree_lacks'))
    blobs = _blobs(git, sorted({entries[item['path']][1] for item in expected}))
    if any(sha256(blobs[entries[item['path']][1]]).hexdigest() != item['sha256'] for item in expected):
        raise ValueError(tr('git.git_attributes_would_transform'))
    if any(doc['after_sha256'] is None and doc['path'] in entries for doc in documents):
        raise ValueError(tr('git.sealed_import_tree_retains'))
