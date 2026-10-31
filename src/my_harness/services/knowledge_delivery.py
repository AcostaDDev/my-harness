"""D294 deterministic whole-file delivery. A persistent checkout lock survives uncertain effects."""
from contextlib import contextmanager
from datetime import datetime
import os
import fcntl
from pathlib import Path
import stat
import tempfile

from sqlalchemy import text
from sqlalchemy.orm import Session
from my_harness.adapters.local_git import LocalGit
from my_harness.core.engine import knowledge_documents as d
from my_harness.core.engine.commit import GitIdentity
from my_harness.storage.models import CheckoutLockRow as Lock, KnowledgeProjectRow
from my_harness.storage.knowledge import KnowledgeSession
from my_harness.storage import knowledge_exchange as store


def safe(root, relative):
    if not relative or relative.startswith('/') or any(p in ('', '.', '..', '.git') for p in relative.split('/')):
        raise ValueError('unsafe_target')
    root = Path(root)
    if root.resolve() != root or not root.is_dir():
        raise ValueError('unsafe_root')
    current = root
    for part in relative.split('/'):
        if current.exists():
            if not current.is_dir() or current.is_symlink():
                raise ValueError('unsafe_ancestor')
            if any(p.casefold() == part.casefold() and p != part for p in os.listdir(current)):
                raise ValueError('target_case_collision')
        current = current / part
        if current.is_symlink():
            raise ValueError('target_link')
    if current.exists():
        mode = current.stat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1:
            raise ValueError('target_not_regular')
    return current


def read(root, relative):
    path = safe(root, relative)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > d.MAX_FILE:
            raise ValueError('target_not_regular_or_large')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            data = f.read(d.MAX_FILE + 1)
        return data.decode('utf-8')
    finally:
        os.close(fd)


def head(git):
    return git.text('rev-parse', '--verify', 'HEAD') if git.code('rev-parse', '--verify', 'HEAD') == 0 else None


def baseline(root, paths):
    git = LocalGit(Path(root))
    if not (Path(root) / '.git').exists():
        if Path(root).resolve() != Path(root) or any(Path(root).iterdir()):
            raise ValueError('new_root_not_empty')
        return {'head': None, 'index': None, 'ref': 'refs/heads/main',
                'targets': {p: None for p in paths}, 'init_required': True}
    # No filters, providers or hooks; only the local committed tree is inspected.
    if git.run('status', '--porcelain=v1', '-z', '--untracked-files=all'):
        raise ValueError('dirty_checkout')
    values = {p: read(root, p) for p in paths}
    tree = git.text('write-tree')
    committed = head(git)
    entries = git.run('ls-tree', '-r', '-z', committed).split(b'\0') if committed else []
    for entry in entries:
        if entry:
            header, path = entry.split(b'\t', 1)
            name = path.decode('utf-8')
            if name in values:
                if not header.startswith((b'100644 ', b'100755 ')):
                    raise ValueError('target_git_mode')
                blob = header.split()[2].decode('ascii')
                if git.run('cat-file', 'blob', blob).decode('utf-8') != values[name]:
                    raise ValueError('dirty_target')
    tracked = {entry.split(b'\t', 1)[1].decode('utf-8') for entry in entries if entry}
    if any(value is not None and path not in tracked for path, value in values.items()):
        raise ValueError('uncommitted_target')
    if committed and tree != git.text('rev-parse', committed + '^{tree}'):
        raise ValueError('dirty_index')
    return {'head': committed, 'index': tree, 'ref': git.text('symbolic-ref', 'HEAD'), 'targets': values}


class KnowledgeDelivery:
    def __init__(self, engine, root, project):
        self.engine, self.root, self.project = engine, str(root), project
        from my_harness.storage.managed_mode import ModeGuard
        self.guard = ModeGuard(engine)

    @contextmanager
    def write(self):
        assessment = self.guard.assess(Path(self.root))
        with Session(self.engine) as session, session.begin():
            if session.execute(text('PRAGMA query_only')).scalar():
                raise ValueError('query_only')
            session.execute(text('DELETE FROM knowledge_exchange_records WHERE 0'))
            self.guard.enforce(session, assessment)
            project = session.get(KnowledgeProjectRow, self.project)
            if project is None or project.root != self.root:
                raise ValueError('project_not_found')
            yield session

    def status(self, ident):
        with Session(self.engine) as session:
            scope = session.get(KnowledgeProjectRow, self.project)
            if scope is None or scope.root != self.root:
                raise ValueError('exchange_not_found')
            intent = store.get(session, self.project, ident)
            outcomes = [r.payload for r in store.records(session, self.project) if r.payload.get('intent_id') == ident]
            return {'record_id': ident, 'kind': intent.kind, 'outcomes': outcomes, 'intent': intent.payload,
                    'preview_sha256': intent.sha256,
                    'pending': not any(o.get('status') == 'COMPLETED' for o in outcomes)}

    def execute(self, ident, preview_sha256, identity, *, writer_stopped=False, after_write=None, key=None):
        # Cross-thread/process exclusion prevents a claimed stopped writer from racing a live recovery.
        # Query-only consultation creates no lock file.
        with Session(self.engine) as session:
            if session.execute(text('PRAGMA query_only')).scalar():
                raise ValueError('query_only')
        lock_path = Path(self.engine.url.database).absolute().with_name(
            '.harness-delivery-' + d.sha(self.root) + '.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('checkout_writer_active') from None
            if key is not None:
                request = {'intent_id': ident, 'preview_sha256': preview_sha256, 'writer_stopped': writer_stopped}
                with self.write() as session:
                    store.get(session, self.project, ident)
                    prior = next((r for r in store.records(session, self.project, 'delivery_request')
                                  if r.record_key == 'delivery:' + key), None)
                    if prior and prior.payload != request:
                        raise ValueError('idempotency_conflict')
                    if not prior:
                        store.add(session, self.project, 'delivery_request', request, 'delivery:' + key)
            try:
                return self._execute(ident, preview_sha256, identity, writer_stopped=writer_stopped, after_write=after_write)
            except Exception as exc:
                with self.write() as session:
                    lock = session.get(Lock, self.root)
                    if lock and lock.exchange_id == ident:
                        store.add(session, self.project, 'export_failed',
                            {'intent_id': ident, 'status': 'PENDING', 'code': type(exc).__name__})
                raise
        finally:
            os.close(fd)

    def _execute(self, ident, preview_sha256, identity, *, writer_stopped=False, after_write=None):
        GitIdentity(identity.name, identity.email)
        with self.write() as session:
            intent = store.get(session, self.project, ident)
            if intent.kind != 'export_intent' or intent.sha256 != preview_sha256:
                raise ValueError('export_consent_mismatch')
            completed = next((r for r in store.records(session, self.project, 'export_completed')
                              if r.payload['intent_id'] == ident), None)
            if completed:
                return completed.payload
            current = KnowledgeSession(session).head(self.project)
            ownership = store.latest(session, self.project, 'ownership')
            if current.id != intent.payload['revision_id'] or ownership.id != intent.payload['ownership_id']:
                raise ValueError('export_revision_or_ownership_stale')
            lock = session.get(Lock, self.root)
            if lock and (lock.exchange_id != ident or not writer_stopped):
                raise ValueError('checkout_writer_not_confirmed_stopped')
            if lock is None:
                session.add(Lock(root=self.root, exchange_id=ident))
            payload = intent.payload
            seals = [r for r in store.records(session, self.project, 'export_identity') if r.payload['intent_id'] == ident]
            if seals:
                identity = GitIdentity(**seals[-1].payload['identity'])
            else:
                store.add(session, self.project, 'export_identity', {'intent_id': ident, 'identity': {'name': identity.name, 'email': identity.email}})
        # Durable lock remains on every exception, including a killed process. No lease-based release.
        git = LocalGit(Path(self.root))
        base, files = dict(payload['baseline']), payload['files']
        if base.get('init_required'):
            gitdir = Path(self.root) / '.git'
            if gitdir.is_symlink() or gitdir.exists() and not gitdir.is_dir():
                raise ValueError('unsafe_git_root')
            if not gitdir.exists() and any(Path(self.root).iterdir()):
                raise ValueError('new_root_not_empty')
            git.run('init', '--initial-branch=main')
            base['index'] = git.text('mktree', input=b'')
        with Session(self.engine) as session:
            plans = [r for r in store.records(session, self.project, 'export_commit') if r.payload['intent_id'] == ident]
        plan = plans[-1].payload if plans else None
        current_head = head(git)
        expected_heads = {base['head']} | ({plan['commit']} if plan else set())
        if current_head not in expected_heads or git.text('symbolic-ref', 'HEAD') != base['ref']:
            raise ValueError('export_head_changed')
        current_index = git.text('write-tree')
        if current_index not in {base['index']} | ({plan['tree']} if plan else set()):
            raise ValueError('export_index_changed')
        # Remove only a deterministic scratch path of this same sealed intent. A partial write is a prefix.
        for path, rendered in files.items():
            scratch = str(Path(path).parent / ('.harness-export-' + ident + '-' + d.sha(path)[:12]))
            temporary = read(self.root, scratch)
            if temporary is not None:
                if not rendered.startswith(temporary):
                    raise ValueError('export_scratch_changed')
                safe(self.root, scratch).unlink()
        # Changes outside sealed targets cannot be swept into a generated commit.
        for entry in git.run('status', '--porcelain=v1', '-z', '--untracked-files=all').split(b'\0'):
            if entry and (len(entry) < 4 or entry[3:].decode('utf-8') not in files or entry[:2] not in (b' M', b'??', b'M ', b'A ', b'D ', b' D', b'AM', b'MM', b'AD', b'MD')):
                raise ValueError('export_unrelated_changes')
        for path, rendered in files.items():
            actual = read(self.root, path)
            if actual != base['targets'][path] and actual != rendered:
                raise ValueError('export_target_changed')
        for path, rendered in files.items():
            if read(self.root, path) != rendered:
                target = safe(self.root, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                safe(self.root, path)
                temp = target.parent / ('.harness-export-' + ident + '-' + d.sha(path)[:12])
                fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(rendered.encode('utf-8'))
                        f.flush()
                        os.fsync(f.fileno())
                    # Rule 8 CAS against the sealed baseline or the same intent's output.
                    if read(self.root, path) not in (base['targets'][path], rendered):
                        raise ValueError('export_target_changed')
                    os.replace(temp, target)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
            with self.write() as session:
                key = ident + ':target:' + d.sha(path)
                if not any(r.record_key == key for r in store.records(session, self.project, 'export_target')):
                    store.add(session, self.project, 'export_target', {'intent_id': ident, 'path': path,
                              'sha256': d.sha(rendered), 'status': 'WRITTEN'}, key)
            if after_write:
                after_write(path)
        if plan is None:
            with tempfile.TemporaryDirectory() as directory:
                env = {'GIT_INDEX_FILE': str(Path(directory) / 'index')}
                git.run('read-tree', base['index'], env=env)
                for path, rendered in files.items():
                    blob = git.text('hash-object', '-w', '--stdin', input=rendered.encode('utf-8'))
                    git.run('update-index', '--add', '--cacheinfo', '100644', blob, path, env=env)
                tree = git.text('write-tree', env=env)
            with self.write() as session:
                intent = store.get(session, self.project, ident)
                timestamp = int(datetime.fromisoformat(intent.created_at).timestamp())
                who = f'{identity.name} <{identity.email}> {timestamp} +0000'
                parent = f'parent {base["head"]}\n' if base['head'] else ''
                raw = f'tree {tree}\n{parent}author {who}\ncommitter {who}\n\nHarness knowledge export\n\nHarness-Export: {ident}\n'
                commit = git.text('hash-object', '-t', 'commit', '-w', '--stdin', input=raw.encode('utf-8'))
                plan = {'intent_id': ident, 'commit': commit, 'tree': tree}
                store.add(session, self.project, 'export_commit', plan)
        for path, rendered in files.items():
            if read(self.root, path) != rendered:
                raise ValueError('export_target_changed')
        if git.text('write-tree') not in {base['index'], plan['tree']}:
            raise ValueError('export_index_changed')
        if git.text('symbolic-ref', 'HEAD') != base['ref']:
            raise ValueError('export_head_changed')
        if head(git) != plan['commit']:
            git.run('update-ref', base['ref'], plan['commit'], base['head'] or '0' * len(plan['commit']))
        if git.text('write-tree') not in {base['index'], plan['tree']}:
            raise ValueError('export_index_changed')
        git.run('read-tree', plan['tree'])
        with self.write() as session:
            lock = session.get(Lock, self.root)
            if lock is None or lock.exchange_id != ident:
                raise ValueError('writer_fence_lost')
            result = {'intent_id': ident, 'status': 'COMPLETED', 'commit': plan['commit'],
                      'revision_id': payload['revision_id'], 'revision_sha256': payload['revision_sha256']}
            store.add(session, self.project, 'export_completed', result)
            session.delete(lock)
        return result
