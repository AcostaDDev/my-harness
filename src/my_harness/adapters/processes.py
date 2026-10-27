"""POSIX process groups; absence is evidence, permission errors are uncertainty.

Recovery never signals a persisted PID: PID reuse cannot establish identity.
Live handles may cancel their own group; persisted liveness is conservative.
"""
from dataclasses import dataclass
import os
import platform
import signal
import socket
import time
from uuid import getnode


def host_identity():
    return f"{socket.gethostname()}:{getnode()}:{platform.system()}"


def identity(pid=None):
    return {"host": host_identity(), "pid": pid or os.getpid()}


def liveness(value, *, group=False):
    if not value or value.get("host") != host_identity():
        return "unknown"
    pid = value.get("pgid" if group else "pid")
    if type(pid) is not int or pid <= 1:
        return "unknown"
    try:
        (os.killpg if group else os.kill)(pid, 0)
    except ProcessLookupError:
        return "dead"
    except (PermissionError, OSError):
        return "unknown"
    return "alive"


@dataclass(frozen=True)
class CancellationResult:
    requested: bool
    group_state: str


def stop_group(process, *, grace=0.3):
    """TERM then KILL, bounded wait, including children after leader exit."""
    value = {**identity(process.pid), "pgid": process.pid}
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if liveness(value, group=True) == "dead":
            break
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            return CancellationResult(True, "unknown")
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            process.poll()  # Reap leader; zombies remain conservative if not ours.
            if liveness(value, group=True) == "dead":
                return CancellationResult(True, "dead")
            time.sleep(0.01)
    process.poll()
    return CancellationResult(True, liveness(value, group=True))
