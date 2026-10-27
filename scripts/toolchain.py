"""Pinned development toolchain (H0.2): check shared by the repository scripts."""
import subprocess

EXPECTED = (('node', 'v24.15.0'), ('npm', '11.12.1'), ('uv', 'uv 0.12.19'))


def check_tools(uv='uv', build=True):
    for name, expected in EXPECTED:
        if not build and name != 'uv':
            continue
        executable = uv if name == 'uv' else name
        try:
            observed = subprocess.check_output([executable, '--version'], text=True).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(f'{executable}: {expected} required; not available ({exc})') from None
        if (observed.split(' (', 1)[0] if name == 'uv' else observed) != expected:
            raise SystemExit(f'{executable}: {expected} required; found {observed}')
