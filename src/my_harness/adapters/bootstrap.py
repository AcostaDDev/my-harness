"""Initial Git H4.2: no shell, hooks, global configuration or file overwrites.

The folder is a capability registered by the server. SQLite exclusion is
complemented by an ownership mark in .git, exclusive new files and
byte/index/HEAD checks. External writers remain cooperative.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile

from my_harness.core.engine.phases import digest
from my_harness.i18n import tr

MARKER = 'harness-bootstrap.json'


def target_identity(context):
    root = context.root
    if root.is_symlink() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError(tr('bootstrap.bootstrap_target_changed_contains'))
    info = root.stat()
    return {'device': info.st_dev, 'inode': info.st_ino}


def inspect_target(context, git):
    identity = target_identity(context)
    entries = sorted(p.name for p in context.root.iterdir())
    # Even an empty folder inside another checkout requires an import.
    nested = git.code('rev-parse', '--is-inside-work-tree') == 0
    return {'identity': identity, 'entries': entries[:100], 'entries_truncated': len(entries) > 100,
            'import_required': bool(entries) or nested,
            'diagnostic': tr('bootstrap.import_required') if entries or nested else None}


class DraftConflict(ValueError):
    """The draft on disk no longer has the expected hash: nothing is overwritten."""


class DraftChanged(DraftConflict):
    """The draft changed since it was read; the API names it with its own code (P011-T022)."""


def inspect_drafts(context, git, *, texts=False):
    """H6.5: reads the target of a v2 definition; only admits drafts at the allowed paths.

    Any other file, folder or link is foreign and blocks acceptance (import flow).
    An own `.git` or a repository containing the folder requires an import."""
    from my_harness.core.engine.definition import allowed_draft, definition_layout, draft_directories
    from my_harness.core.engine.documents import MAX_DOCUMENT_BYTES
    target = definition_layout(context)
    identity = target_identity(context)
    nested = git.code('rev-parse', '--is-inside-work-tree') == 0
    folders = draft_directories(target)
    drafts, contents, foreign, invalid = {}, {}, [], []

    def visit(folder, prefix):
        for item in sorted(folder.iterdir(), key=lambda entry: entry.name):
            path = prefix + item.name
            mode = item.lstat().st_mode
            if stat.S_ISDIR(mode) and path in folders:
                visit(item, path + '/')
            elif stat.S_ISREG(mode) and allowed_draft(target, path):
                data = item.read_bytes()
                try:
                    # Git mode 100644: an executable draft cannot be sealed as is.
                    if len(data) > MAX_DOCUMENT_BYTES or b'\0' in data or stat.S_IMODE(mode) & 0o111:
                        raise ValueError(path)
                    text = data.decode('utf-8')
                except (ValueError, UnicodeError):
                    invalid.append(path)
                    continue
                drafts[path] = sha256(data).hexdigest()
                contents[path] = text
            else:
                foreign.append(path + ('/' if stat.S_ISDIR(mode) else ''))

    visit(context.root, '')
    result = {'identity': identity, 'drafts': drafts, 'foreign': foreign[:100],
              'foreign_truncated': len(foreign) > 100, 'invalid': invalid,
              'import_required': nested or (context.root / '.git').exists() or (context.root / '.git').is_symlink()}
    return {**result, 'texts': contents} if texts else result


def _current(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise DraftConflict(tr('bootstrap.draft_regular_file'))
    return sha256(path.read_bytes()).hexdigest() if path.exists() else None


def write_draft(writer, context, path, content, base_sha256):
    """Writes (or deletes with `content=None`) a draft if its hash is still `base_sha256`.

    Cooperative exclusion like D036: the check is repeated right before replacing, without atomicity
    against an external editor. Returns the previous and new hashes; identical content is not rewritten."""
    from my_harness.core.engine.definition import allowed_draft, definition_layout, draft_directories
    target = definition_layout(context)
    if not allowed_draft(target, path):
        raise ValueError(tr('planning.not_allowed_definition_draft', path=path))
    if inspect_drafts(context, writer._git(context.root))['import_required']:
        raise ValueError(tr('planning.target_belongs_git_repository'))
    folders = draft_directories(target)
    parts = path.split('/')
    for n in range(1, len(parts)):
        folder = context.root.joinpath(*parts[:n])
        if '/'.join(parts[:n]) not in folders or folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError(tr('onboarding.not_inside_allowed_draft', path=path))
    item = context.path(path)
    current = _current(item)
    after = None if content is None else sha256(content.encode('utf-8')).hexdigest()
    if current == after:
        return {'before': current, 'after': after, 'written': False}
    if current != base_sha256:
        raise DraftChanged(tr('onboarding.changed_since_read_expected', path=path, base_sha256=base_sha256,
                               current=current))
    if content is None:
        item.unlink()
    else:
        item.parent.mkdir(parents=True, exist_ok=True)
        _replace_file(item, content.encode('utf-8'), 'draft', lambda: _current(item) == base_sha256)
    return {'before': current, 'after': after, 'written': True}


def _temporary(path, token):
    return path.with_name(f'.{path.name}.{token}.harness-tmp')


def _replace_file(path, content, token, unchanged):
    """Own temporary file in the same folder and `os.replace`; never leaves a half-written file."""
    temporary = _temporary(path, token)
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    _new_file(temporary, content)
    try:
        if not unchanged():
            raise DraftConflict(tr('bootstrap.changed_while_being_replaced', name=path.name))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _new_file(path, content):
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _commit(intent):
    return (f"tree {intent['tree']}\n"
            f"author {intent['author_name']} <{intent['author_email']}> {intent['committed_at']} +0000\n"
            f"committer {intent['author_name']} <{intent['author_email']}> {intent['committed_at']} +0000\n"
            f"\n{intent['message']}\n").encode('utf-8')


def _tree(git, documents):
    # Separate temporary index: adds no staging and runs no worktree filters.
    with tempfile.TemporaryDirectory(prefix='harness-bootstrap-index-') as area:
        env = {'GIT_INDEX_FILE': str(Path(area) / 'index')}
        git.run('read-tree', '--empty', env=env)
        if documents:
            # A single hash-object with exact bytes: --no-filters is equivalent to --stdin without --path.
            sources = []
            for number, doc in enumerate(documents):
                source = Path(area) / f'blob-{number}'
                source.write_bytes(doc['content'].encode('utf-8'))
                sources.append(str(source))
            blobs = git.text('hash-object', '-w', '--no-filters', '--stdin-paths',
                             input=('\n'.join(sources) + '\n').encode('utf-8')).splitlines()
            if len(blobs) != len(documents):
                raise ValueError('Git returned an unexpected number of bootstrap objects')
            cacheinfo = [arg for doc, blob in zip(documents, blobs)
                         for arg in ('--cacheinfo', f"100644,{blob},{doc['path']}")]
            git.run('update-index', '--add', *cacheinfo, env=env)
        return git.text('write-tree', env=env)


def seal(writer, shown, operation_id, committed_at):
    with tempfile.TemporaryDirectory(prefix='harness-bootstrap-seal-') as area:
        git = writer._git(Path(area))
        git.run('init', '-q', '--template=', '--object-format=sha1', '-b', 'main')
        intent = {'operation_id': operation_id, 'preview_sha256': shown['preview_sha256'],
                  'tree': _tree(git, shown['documents']), 'author_name': writer.identity.name,
                  'author_email': writer.identity.email, 'committed_at': committed_at,
                  'message': 'Initialize project from confirmed bootstrap'}
        intent['commit'] = git.text('hash-object', '-t', 'commit', '--stdin', input=_commit(intent))
        return intent


def _directories(documents):
    return {str(parent) for d in documents for parent in Path(d['path']).parents if str(parent) != '.'}


def validate_partial(context, shown, intent):
    if target_identity(context) != shown['target']['identity']:
        raise ValueError(tr('bootstrap.bootstrap_target_replaced_since'))
    documents = {d['path']: d for d in shown['documents']}
    directories = _directories(shown['documents'])
    # H6.5: the own temporary file of an interrupted replacement is discarded before writing.
    temporaries = {_temporary(context.root / path, intent['operation_id']).relative_to(context.root).as_posix()
                   for path, doc in documents.items() if 'before_sha256' in doc}
    for directory, dirs, names in os.walk(context.root, followlinks=False):
        for name in [*dirs, *names]:
            item = Path(directory) / name
            path = item.relative_to(context.root).as_posix()
            mode = item.lstat().st_mode
            if path == '.git':
                if not stat.S_ISDIR(mode):
                    raise ValueError(tr('bootstrap.bootstrap_git_directory_owned'))
                marker = item / MARKER
                if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != marker_bytes(intent):
                    raise ValueError(tr('bootstrap.unowned_git_directory_import'))
                dirs.remove(name)
                continue
            if stat.S_ISDIR(mode) and path in directories:
                continue
            if path in temporaries and stat.S_ISREG(mode):
                continue
            if path not in documents or not stat.S_ISREG(mode):
                raise ValueError(tr('bootstrap.unexpected_bootstrap_path_preserved', path=path))
            doc = documents[path]
            if 'before_sha256' in doc:
                # H6.5: the reviewed draft or the sealed bytes; no executable bit (Git mode 100644).
                if (stat.S_IMODE(mode) & 0o111 or sha256(item.read_bytes()).hexdigest()
                        not in (doc['sha256'], doc['before_sha256'])):
                    raise ValueError(tr('bootstrap.bootstrap_draft_changed_preserved', path=path))
                continue
            if (item.stat().st_size != len(doc['content'].encode('utf-8'))
                    or sha256(item.read_bytes()).hexdigest() != doc['sha256']
                    or stat.S_IMODE(mode) != 0o644):
                raise ValueError(tr('bootstrap.bootstrap_content_changed_preserved', path=path))


def marker_bytes(intent):
    return (json.dumps({'format': 'bootstrap-1', 'intent_sha256': digest(intent),
                        'operation_id': intent['operation_id']}, sort_keys=True) + '\n').encode()


def execute(writer, context, shown, intent):
    validate_partial(context, shown, intent)
    gitdir = context.root / '.git'
    drafts = any('before_sha256' in doc for doc in shown['documents'])
    if not gitdir.exists():
        # Starting requires the same empty directory (or only the reviewed drafts, H6.5), also when claiming.
        if not drafts and any(context.root.iterdir()):
            raise ValueError(tr('bootstrap.target_no_longer_empty'))
        if writer._git(context.root).code('rev-parse', '--is-inside-work-tree') == 0:
            raise ValueError(tr('bootstrap.target_now_belongs_another'))
        gitdir.mkdir()  # exclusive: never replaces a foreign .git
        _new_file(gitdir / MARKER, marker_bytes(intent))
    git = writer._git(context.root)
    for name in ('HEAD', 'config', 'index'):
        if (gitdir / name).is_symlink():
            raise ValueError(tr('bootstrap.bootstrap_git_metadata_contains'))
    if not (gitdir / 'HEAD').exists():
        # Crash between mark and init: only the own mark allows completing the init.
        if sorted(p.name for p in gitdir.iterdir()) != [MARKER]:
            raise ValueError(tr('bootstrap.incomplete_git_initialization_has'))
        git.run('init', '-q', '--template=', '--object-format=sha1', '-b', 'main')
    if git.text('rev-parse', '--show-toplevel') != str(context.root):
        raise ValueError(tr('bootstrap.bootstrap_repository_root_changed'))
    if git.text('symbolic-ref', 'HEAD') != 'refs/heads/main':
        raise ValueError(tr('bootstrap.bootstrap_branch_changed'))
    head = git.run('rev-parse', '--verify', 'HEAD', ok=(0, 128)).decode().strip()
    if head and head != intent['commit']:
        raise ValueError(tr('bootstrap.bootstrap_head_changed_preserved'))
    refs = git.text('for-each-ref', '--format=%(refname) %(objectname)')
    if refs not in ('', 'refs/heads/main ' + intent['commit']):
        raise ValueError(tr('bootstrap.bootstrap_references_changed_recover'))
    empty = git.text('hash-object', '-t', 'tree', '--stdin', input=b'')
    if (gitdir / 'index').exists():
        index = writer._index_tree(git)
        if index not in (empty, intent['tree']):
            raise ValueError(tr('bootstrap.bootstrap_index_changed_preserved'))
    for doc in shown['documents']:
        validate_partial(context, shown, intent)
        path = context.path(doc['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        if 'before_sha256' in doc:
            temporary = _temporary(path, intent['operation_id'])
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
        if not path.exists():
            _new_file(path, doc['content'].encode('utf-8'))
        elif 'before_sha256' in doc and sha256(path.read_bytes()).hexdigest() != doc['sha256']:
            # Reviewed draft → sealed bytes (regenerated blocks); any other content was already rejected above.
            before = doc['before_sha256']
            _replace_file(path, doc['content'].encode('utf-8'), intent['operation_id'],
                          lambda: sha256(path.read_bytes()).hexdigest() == before)
    validate_partial(context, shown, intent)
    if _tree(git, shown['documents']) != intent['tree']:
        raise ValueError(tr('bootstrap.bootstrap_tree_differs_sealed'))
    raw = _commit(intent)
    if git.text('hash-object', '-t', 'commit', '-w', '--stdin', input=raw) != intent['commit']:
        raise ValueError(tr('bootstrap.bootstrap_commit_differs_sealed'))
    validate_partial(context, shown, intent)
    if writer._index_tree(git) not in (empty, intent['tree']):
        raise ValueError(tr('bootstrap.bootstrap_index_changed_before'))
    git.run('update-ref', '-m', 'harness: bootstrap ' + intent['operation_id'], 'refs/heads/main',
            intent['commit'], head or '0' * 40)
    if git.text('cat-file', 'commit', intent['commit']) != raw.decode().strip():
        raise ValueError(tr('bootstrap.bootstrap_commit_content_differs'))
    if writer._index_tree(git) not in (empty, intent['tree']):
        raise ValueError(tr('bootstrap.bootstrap_index_changed_after'))
    if git.text('rev-parse', 'HEAD') != intent['commit']:
        raise ValueError(tr('bootstrap.bootstrap_head_changed_after'))
    git.run('read-tree', intent['tree'])
    evidence = writer.capture(context)
    if evidence.changed_paths or evidence.base_revision != intent['commit']:
        raise ValueError(tr('bootstrap.bootstrap_checkout_differs_sealed'))
    validate_partial(context, shown, intent)
    return {'commit': intent['commit'], 'tree': intent['tree'], 'documents': {
        d['path']: d['sha256'] for d in shown['documents']}}
