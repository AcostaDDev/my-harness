"""Private per-invocation Unix connection to the supervisor; no domain authority in the stdio relay.

The directory is mode 0700 and socket 0600. This is cooperative same-user containment (D064), not OS isolation.
Closing the connection is an independent termination channel, including while a domain call is in flight.
"""
import errno
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from threading import Event, Thread
import time
from uuid import uuid4

from sqlalchemy.orm import Session

from my_harness.adapters.processes import identity, liveness
from my_harness.core.engine import tool_bridge as core
from my_harness.core.engine.contracts import freeze
from my_harness.i18n import tr


class BridgeSession:
    def __init__(self, broker, directory):
        self.broker = broker
        # AF_UNIX has a short platform path limit; never use the possibly long artifact path as endpoint.
        self.temporary = tempfile.TemporaryDirectory(prefix='mh-bridge-', dir='/tmp')
        self.path = str(Path(self.temporary.name).resolve() / 's')
        self.stopped = Event()
        self.available = Event()
        self.connection = None
        self.process = None
        self.error = None
        self.failure = None
        self.closed = False
        self.journal_update = None
        self.disconnect_reason = None
        self.response_lost = False
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(1)
        self.server.settimeout(0.1)
        self.config = {'command': sys.executable,
                       # -I excludes the launch cwd, PYTHON* variables and the user site. Resolve the package
                       # through this interpreter's installed environment, never the managed checkout.
                       'args': ['-I', '-m', 'my_harness.adapters.tool_bridge_stdio'],
                       'env': {'MY_HARNESS_BRIDGE': self.path}}
        self.thread = Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _event(self, kind, payload):
        if self.journal_update is not None:
            self.journal_update(kind, payload)
        with Session(self.broker.operations.engine) as session, session.begin():
            self.broker.event(session, kind, f'bridge:process:{uuid4()}', payload)

    def _serve(self):
        try:
            while not self.stopped.is_set():
                try:
                    conn, _ = self.server.accept()
                    break
                except TimeoutError:
                    continue
                except OSError as error:
                    if self.stopped.is_set() and error.errno == errno.EBADF:
                        return
                    raise
            else:
                return
            self.connection = conn
            with conn, conn.makefile('rb') as reader:
                raw = self._read(reader, 4096)
                if not raw:
                    self.disconnect_reason = self.disconnect_reason or 'peer_eof'
                    return
                hello = json.loads(raw)
                if (set(hello) != {'pid', 'parent', 'pgid'} or type(hello['pid']) is not int or hello['pid'] <= 1
                        or any(type(hello[k]) is not int or hello[k] <= 1 for k in ('parent', 'pgid'))):
                    raise ValueError(tr('bridge.registration'))
                self.process = {**identity(hello['pid']), 'parent': hello['parent'], 'pgid': hello['pgid']}
                # Intent and live registration are persisted before acknowledging any request.
                self._event('bridge.registered', self.process)
                if not self._send(conn, b'{"ready":true}\n'):
                    return
                while True:
                    line = self._read(reader, core.MAX_MESSAGE + 1)
                    if not line:
                        self.disconnect_reason = self.disconnect_reason or 'peer_eof'
                        break
                    if self.stopped.is_set():
                        self.disconnect_reason = 'supervisor_closed'
                        break
                    if len(line) > core.MAX_MESSAGE:
                        raise ValueError(tr('bridge.parameters'))
                    request = json.loads(line)
                    if isinstance(request, dict) and set(request) == {'ready'}:
                        ready = request['ready']
                        if (self.available.is_set() or not isinstance(ready, dict)
                                or set(ready) != {'protocol', 'surface_sha256'}
                                or ready['protocol'] not in core.PROTOCOLS
                                or ready['surface_sha256'] != core.SURFACE_SHA256):
                            raise ValueError(tr('bridge.parameters'))
                        self._event('bridge.ready', {'identity': self.process, **ready})
                        if not self._send(conn, b'{"ready":true}\n'):
                            break
                        self.available.set()
                        continue
                    if not self.available.is_set():
                        raise ValueError(tr('bridge.unavailable'))
                    response = self.broker.call(request.get('name'), request.get('arguments'))
                    if self.stopped.is_set():
                        self.disconnect_reason = 'supervisor_closed'
                        self.response_lost = True
                        break
                    if not self._send(conn, (freeze(response) + '\n').encode(), response=True):
                        break
        except Exception as error:  # no error is converted to successful unrecorded content
            # Socket disconnects are handled only at the read/write boundary. A service or persistence error
            # must survive concurrent cancellation; stopped is not permission to discard it.
            self.error = type(error).__name__
            self.failure = error
        finally:
            if self.process:
                try:
                    self._event('bridge.disconnected', {'identity': self.process, 'error': self.error,
                        'reason': self.disconnect_reason, 'response_lost': self.response_lost})
                except Exception as error:
                    self.error = 'JournalError'
                    self.failure = error

    def _read(self, reader, limit):
        try:
            return reader.readline(limit)
        except (ConnectionResetError, ConnectionAbortedError):
            self.disconnect_reason = 'peer_reset'
            return b''

    def _send(self, conn, data, *, response=False):
        try:
            conn.sendall(data)
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.disconnect_reason = 'peer_closed'
            self.response_lost |= response
            return False

    def close(self, *, require_available=True):
        if self.closed:
            self._check_completion(require_available)
            return
        self.closed = True
        self.stopped.set()
        if self.connection is not None:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError as error:
                if error.errno not in (errno.ENOTCONN, errno.EBADF):
                    raise
        self.server.close()
        self.thread.join(timeout=6)
        self.temporary.cleanup()
        if self.thread.is_alive():
            raise RuntimeError(tr('bridge.settlement'))
        if self.process:
            deadline = time.monotonic() + 1
            while liveness(self.process) == 'alive' and time.monotonic() < deadline:
                time.sleep(0.01)
            state = liveness(self.process)
            self._event('bridge.stopped', {'identity': self.process, 'state': state})
            if state != 'dead':
                raise RuntimeError(tr('bridge.process_alive'))
        self._check_completion(require_available)

    def _check_completion(self, require_available):
        if self.error:
            raise RuntimeError(tr('bridge.transport', error=self.error)) from self.failure
        if require_available and not self.available.is_set():
            raise RuntimeError(tr('bridge.unavailable'))


def codex_config(bridge):
    """TOML is a superset of JSON strings/arrays; approval applies only to this single server."""
    server = {**bridge, 'enabled_tools': list(core.NAMES), 'default_tools_approval_mode': 'approve'}
    # One inline table prevents inherited servers or per-tool approval overrides.
    value = ','.join(f'{key}={freeze(item)}' for key, item in server.items() if key != 'env')
    env = ','.join(f'{key}={freeze(item)}' for key, item in server['env'].items())
    return 'mcp_servers={harness={' + value + ',env={' + env + '}}}'
