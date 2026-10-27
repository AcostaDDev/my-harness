"""Read-only checkout and drift checks for existing managed activations."""
import os
from pathlib import Path
import stat

from my_harness.adapters.safe_files import read_raw
from my_harness.core.managed_mode import (LEGACY_RUNS, MARKER_PATH, CheckoutFacts, classify_drift, digest)
from my_harness.i18n import tr

def _repository(root: Path) -> tuple[str | None, str | None]:
    """Git common dir and main checkout by reading `.git`, without running Git."""
    for directory in (root, *root.parents):
        dot = directory / ".git"
        if not os.path.lexists(dot):
            continue
        try:
            if dot.is_dir() and not dot.is_symlink():
                common = dot.resolve()
            elif dot.is_file() and not dot.is_symlink():
                text = dot.read_text(encoding="utf-8").strip()
                if not text.startswith("gitdir:"):
                    return None, None
                gitdir = (directory / text.partition(":")[2].strip()).resolve()
                pointer = gitdir / "commondir"
                common = (gitdir / pointer.read_text(encoding="utf-8").strip()).resolve() if pointer.is_file() else gitdir
            else:
                return None, None
        except (OSError, UnicodeDecodeError):
            return None, None
        main = str(common.parent) if common.name == ".git" else None
        return str(common), main
    return None, None


def probe(root) -> CheckoutFacts:
    checkout = Path(root).expanduser().resolve(strict=True)
    if not checkout.is_dir():
        raise ValueError(tr('mode.root_directory'))
    key, main = _repository(checkout)
    marker, error = None, None
    if os.path.lexists(checkout / MARKER_PATH):
        try:
            marker = read_raw(checkout, MARKER_PATH)
        except (OSError, ValueError) as exc:
            error = f"ilegible: {exc}"
    main_legacy = bool(main and Path(main) != checkout and os.path.lexists(Path(main) / LEGACY_RUNS))
    return CheckoutFacts(str(checkout), key, main, os.path.lexists(checkout / LEGACY_RUNS), main_legacy,
                         marker, error)


def scan_legacy_scope(root: str) -> dict[str, tuple[str, int, int]]:
    """Current state of `.harness/runs` by lstat: (type, size, mtime_ns)."""
    checkout = Path(root)
    runs = checkout / LEGACY_RUNS
    if not os.path.lexists(runs):
        return {}
    if runs.is_symlink() or not runs.is_dir() or (checkout / ".harness").is_symlink():
        return {LEGACY_RUNS: ("other", 0, 0)}
    found = {}
    for current, directories, files in os.walk(runs, followlinks=False):
        for name in [*directories, *files]:
            path = Path(current) / name
            info = path.lstat()
            kind = "dir" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
            found[path.relative_to(checkout).as_posix()] = (kind, info.st_size, info.st_mtime_ns)
    return found


def legacy_drift(root: str, manifest: dict) -> dict[str, list[str]]:
    def hash_of(path):
        try:
            return digest(read_raw(Path(root), path))
        except (OSError, ValueError):
            return None
    return classify_drift(manifest, scan_legacy_scope(root), hash_of)
