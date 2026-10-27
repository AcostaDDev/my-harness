"""Bounded export of a commit for the chat. No index or registered worktree.

Read-only permissions are cooperative; the evidence detects alterations, it does not
certify isolation of the process outside this tree.
"""
import hashlib
from pathlib import Path
import os
import shutil
import stat

from my_harness.adapters.git import Git, GitError
from my_harness.adapters.local_git import object_size
from my_harness.core.engine.context import relative_path
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.evidence import ContentEvidence
from my_harness.i18n import tr

FORMAT = 'head-export-1'
MAX_FILES = 20_000
MAX_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024


class HeadSnapshot:
    def __init__(self, root, *, executable='git', timeout=120):
        self.git = Git(root, executable=executable, timeout=timeout)

    def head(self):
        try:
            return self.git.text('rev-parse', '--verify', 'HEAD^{commit}')
        except GitError as exc:
            raise ValueError(tr('chat.head_required')) from exc

    def entries(self, head):
        entries = {}
        total = 0
        for raw in self.git.run('ls-tree', '-rz', '-l', '--full-tree', head).split(b'\0'):
            if not raw:
                continue
            meta, name = raw.split(b'\t', 1)
            mode, kind, oid, size = meta.decode('ascii').split()
            path = name.decode('utf-8')
            parts = relative_path(path).parts
            if kind != 'blob' or mode not in ('100644', '100755') or '.git' in parts:
                raise ValueError(tr('chat.chat_snapshots_require_regular'))
            size = object_size(size, kind, oid, path)
            total += size
            if size > MAX_FILE_BYTES or total > MAX_BYTES or len(entries) >= MAX_FILES:
                raise ValueError(tr('chat.chat_head_snapshot_exceeds'))
            entries[path] = (oid, size, mode)
        return entries

    def documents(self, context, head, paths):
        entries = self.entries(head)
        result = []
        for path in paths:
            relative_path(path)
            # Validate the caller's spelling even when the path is absent from HEAD.
            if path != str(relative_path(path)) or '.git' in relative_path(path).parts:
                raise ValueError(tr('chat.invalid_chat_document_path'))
            entry = entries.get(path)
            data = self.git.run('cat-file', 'blob', entry[0]) if entry else None
            result.append({'path': path, 'sha256': hashlib.sha256(data).hexdigest() if data is not None else None,
                           'size': len(data) if data is not None else None,
                           'content': data[:65536].decode('utf-8', 'replace') if data is not None else None,
                           'truncated': data is not None and len(data) > 65536})
        return result

    def export(self, head, destination):
        entries = self.entries(head)
        destination.mkdir(mode=0o700)  # Never reuse a previous export.
        for path, (oid, size, mode) in entries.items():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            data = self.git.run('cat-file', 'blob', oid)
            if len(data) != size:
                raise ValueError(tr('chat.git_blob_size_changed'))
            target.write_bytes(data)
            target.chmod(0o555 if mode == '100755' else 0o444)
        for directory, _, _ in os.walk(destination, topdown=False):
            Path(directory).chmod(0o555)
        return SnapshotEvidence(head)


class SnapshotEvidence:
    def __init__(self, head):
        self.head = head

    def capture(self, context):
        files = []
        total = 0
        if context.root.is_symlink() or not context.root.is_dir():
            raise ValueError(tr('chat.chat_snapshot_root_missing'))
        def unreadable(error):
            raise error
        for directory, dirs, names in os.walk(context.root, followlinks=False, onerror=unreadable):
            for name in sorted(dirs + names):
                path = Path(directory) / name
                mode = path.lstat().st_mode
                relative = path.relative_to(context.root).as_posix()
                if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError(tr('chat.non_regular_entry_chat'))
                if stat.S_ISREG(mode):
                    size = path.stat().st_size
                    total += size
                    if size > MAX_FILE_BYTES or total > MAX_BYTES or len(files) >= MAX_FILES:
                        raise ValueError(tr('chat.chat_snapshot_evidence_exceeds'))
                    files.append((relative, stat.S_IMODE(mode), hashlib.sha256(path.read_bytes()).hexdigest()))
                else:
                    files.append((relative + '/', stat.S_IMODE(mode), None))
        fingerprint = hashlib.sha256(freeze(sorted(files)).encode()).hexdigest()
        return ContentEvidence(self.head, fingerprint, (), '', freeze({'format': FORMAT, 'head': self.head}))


def snapshot_path(repository, job):
    """Derived only from the private database and persisted job identity, never HTTP paths."""
    parent = Path(repository.engine.url.database).resolve().parent / 'chat-snapshots'
    if parent.is_symlink():
        raise ValueError(tr('chat.chat_snapshot_directory_cannot'))
    parent.mkdir(mode=0o700, exist_ok=True)
    return parent / f'{job.id}-{job.owner_token}'


def cleanup(repository, job):
    path = snapshot_path(repository, job)
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        # Do not follow symlinks a misbehaving agent might have introduced.
        for directory, dirs, _ in os.walk(path, followlinks=False):
            Path(directory).chmod(0o700)
        shutil.rmtree(path)
