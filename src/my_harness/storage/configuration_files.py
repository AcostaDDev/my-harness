"""Private, bounded TOML publication with a cooperative installation lock.

Every component is opened with O_NOFOLLOW. CAS is cooperative with the SQLite
write barrier; it does not claim OS isolation against arbitrary concurrent writers.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import uuid

from my_harness.i18n import tr
from my_harness.services.configuration import MAX_BYTES, digest


class ConfigurationFiles:
    def __init__(self, directory):
        self.root = Path(directory)
        if not self.root.is_absolute() or '..' in self.root.parts or self.root.resolve() != self.root:
            raise ValueError(tr('configuration.directory'))
        with self.folder(()) as fd:
            self._private(os.fstat(fd), directory=True)

    @staticmethod
    def _private(info, *, directory=False):
        kind = stat.S_ISDIR if directory else stat.S_ISREG
        if (not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or (not directory and info.st_nlink != 1)):
            raise ValueError(tr('configuration.private'))

    @contextmanager
    def folder(self, parts, *, create=False):
        fds = []
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            fds.append(fd)
            for part in self.root.parts[1:]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                fds.append(fd)
            self._private(os.fstat(fd), directory=True)
            for part in parts:
                if part in ('', '.', '..') or '/' in part:
                    raise ValueError(tr('configuration.internal_path'))
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                fds.append(fd)
                self._private(os.fstat(fd), directory=True)
            yield fd
        finally:
            for fd in reversed(fds):
                os.close(fd)

    @contextmanager
    def locked(self):
        with self.folder(()) as parent:
            fd = os.open('.configuration.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600,
                         dir_fd=parent)
            try:
                self._private(os.fstat(fd))
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                os.close(fd)

    @staticmethod
    def working(scope):
        return ('global.toml',) if scope == 'global' else ('projects', scope[8:], 'project.toml')

    @staticmethod
    def immutable(scope, revision, sha256):
        return ('versions', scope.replace(':', '-'), f'{revision}-{sha256}.toml')

    def read(self, parts):
        try:
            with self.folder(parts[:-1]) as parent:
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                with os.fdopen(fd, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    self._private(before)
                    if before.st_size > MAX_BYTES:
                        raise ValueError(tr('configuration.file_size'))
                    raw = stream.read(MAX_BYTES + 1)
                    after = os.fstat(stream.fileno())
                    if (len(raw) > MAX_BYTES or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                            != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                        raise ValueError(tr('configuration.read_changed'))
                    return raw
        except FileNotFoundError:
            return None

    def hash(self, parts):
        raw = self.read(parts)
        return digest(raw) if raw is not None else None

    def publish(self, parts, raw, before, *, immutable=False):
        after = digest(raw)
        current = self.hash(parts)
        if current == after:
            # A previous process may have died after replace but before directory fsync.
            with self.folder(parts[:-1]) as parent:
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    self._private(os.fstat(fd))
                    os.fsync(fd)
                    os.fsync(parent)
                finally:
                    os.close(fd)
            return
        if current != before or (immutable and current is not None):
            raise ValueError(tr('configuration.publication_unknown'))
        with self.folder(parts[:-1], create=True) as parent:
            temporary = f'.{uuid.uuid4()}.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                if self.hash(parts) != before:
                    raise ValueError(tr('configuration.publication_changed'))
                if immutable:
                    # Rename-exclusive semantics without creating a hardlinked authority file.
                    # Installation lock + SQLite intent exclude every cooperative publisher.
                    if self.hash(parts) is not None:
                        raise ValueError(tr('configuration.immutable_exists'))
                os.replace(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
