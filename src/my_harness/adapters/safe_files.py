"""Bounded regular-file reads for sealed compatibility evidence."""
import os
from pathlib import Path
import stat

from my_harness.i18n import tr

class ChangingEvidence(ValueError):
    pass


def read_raw(root: Path, path: str) -> bytes:
    """Bounded regular-file read, without following any path component."""
    descriptors = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(fd)
        parts = (root / path).parts[1:]
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(tr('evidence.not_regular'))
        maximum = 64 * 1024 * 1024
        if before.st_size > maximum:
            raise ValueError(tr('evidence.limit'))
        raw = bytearray()
        while chunk := os.read(fd, 65536):
            raw.extend(chunk)
            if len(raw) > maximum:
                raise ValueError(tr('evidence.grew'))
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ChangingEvidence(tr('evidence.changing'))
        return bytes(raw)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
