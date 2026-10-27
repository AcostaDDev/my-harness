import atexit
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def _bypass_xcode_git_shim():
    """On macOS, `/usr/bin/git` is an xcrun shim that doubles the cost of every Git call.

    The tests launch thousands of Git processes: the session PATH gets a prefix with the same
    real binary, its `libexec/git-core` and its `share` (Apple Git resolves both relative to the
    executable). It must happen when this conftest is imported, before the test modules copy
    `os.environ` into their Git environments.
    """
    if sys.platform != 'darwin' or shutil.which('git') != '/usr/bin/git':
        return
    try:
        real = Path(subprocess.run(['xcrun', '--find', 'git'], capture_output=True, text=True,
                                   check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return
    prefix = real.parent.parent
    if not all((prefix / name).is_dir() for name in ('libexec/git-core', 'share')):
        return
    shim = Path(tempfile.mkdtemp(prefix='harness-test-git-'))
    atexit.register(shutil.rmtree, shim, ignore_errors=True)
    (shim / 'bin').mkdir()
    (shim / 'bin' / 'git').symlink_to(real)
    for name in ('libexec', 'share'):
        (shim / name).symlink_to(prefix / name)
    os.environ['PATH'] = f"{shim / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"


_bypass_xcode_git_shim()
