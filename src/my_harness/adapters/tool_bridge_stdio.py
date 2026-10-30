"""Executable MCP stdio relay (D281). Only the three broker tools; stdout contains JSON-RPC only.

EOF, lost CLI parent and closed supervisor connection terminate even during a call. No database, credentials,
permission configuration, SQL, domain dispatch, fallback or provider lives here. Runs from the installed wheel.
"""
import json
import os
import queue
import select
import socket
import sys
from threading import Thread
import time

from my_harness.core.engine import tool_bridge as core
from my_harness.core.engine.contracts import freeze
from my_harness.i18n import tr


def main():
    endpoint = os.environ.get('MY_HARNESS_BRIDGE')
    if not endpoint:
        return 2
    parent = os.getppid()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(endpoint)
    connection.sendall((freeze({'pid': os.getpid(), 'parent': parent, 'pgid': os.getpgrp()}) + '\n').encode())
    reader = connection.makefile('rb')
    if json.loads(reader.readline(4096)) != {'ready': True}:
        return 2
    inputs = queue.Queue(maxsize=8)

    def stdin_reader():
        while True:
            line = sys.stdin.buffer.readline(core.MAX_MESSAGE + 1)
            if not line:
                os._exit(0)  # independent of an in-flight broker read
            if len(line) > core.MAX_MESSAGE:
                os._exit(2)
            try:
                inputs.put_nowait(line)
            except queue.Full:
                os._exit(2)

    def watchdog():
        while True:
            if os.getppid() != parent or parent <= 1:
                os._exit(0)
            # A supervisor close is readable as EOF, including while idle. MSG_PEEK never consumes a response.
            if select.select([connection], [], [], 0)[0]:
                try:
                    if not connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT):
                        os._exit(0)
                except BlockingIOError:
                    pass
                except OSError:
                    os._exit(0)
            time.sleep(0.03)

    Thread(target=stdin_reader, daemon=True).start()
    Thread(target=watchdog, daemon=True).start()
    initialized = False
    while True:
        raw = inputs.get()
        request_id = None
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(tr('bridge.parameters'))
                    result[key] = value
                return result
            request = json.loads(raw, object_pairs_hook=unique,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError(tr('bridge.parameters'))))
            if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
                raise ValueError(tr('bridge.parameters'))
            request_id = request.get('id')
            if request_id is not None and (type(request_id) not in (int, str) or len(str(request_id)) > 200):
                raise ValueError(tr('bridge.parameters'))
            method = request.get('method')
            params = request.get('params', {})
            if 'id' not in request:
                continue
            if method == 'initialize':
                if initialized or not isinstance(params, dict) or params.get('protocolVersion') not in core.PROTOCOLS:
                    raise ValueError(tr('bridge.parameters'))
                # A persisted readiness round trip proves successful protocol/surface preparation. No logical
                # tool call is required, and a registration alone cannot establish client availability.
                connection.sendall((freeze({'ready': {'protocol': params['protocolVersion'],
                                                     'surface_sha256': core.SURFACE_SHA256}}) + '\n').encode())
                if json.loads(reader.readline(4096)) != {'ready': True}:
                    return 2
                initialized = True
                result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'my-harness', 'version': core.FORMAT}}
            elif method not in ('ping', 'tools/list', 'tools/call'):
                print(freeze({'jsonrpc': '2.0', 'id': request_id,
                              'error': {'code': -32601, 'message': tr('bridge.method')}}), flush=True)
                continue
            elif not initialized:
                raise ValueError(tr('bridge.parameters'))
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                if params:
                    raise ValueError(tr('bridge.parameters'))
                result = {'tools': core.TOOLS}
            elif method == 'tools/call':
                if not isinstance(params, dict) or set(params) != {'name', 'arguments'}:
                    raise ValueError(tr('bridge.parameters'))
                connection.sendall((freeze(params) + '\n').encode())
                line = reader.readline(core.MAX_MESSAGE + 1)
                if not line:
                    return 0
                value = json.loads(line)
                result = {'content': [{'type': 'text', 'text': freeze(value)}], 'isError': not value['ok']}
            response = {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except (ValueError, TypeError, KeyError, RecursionError):
            response = {'jsonrpc': '2.0', 'id': request_id,
                        'error': {'code': -32602, 'message': tr('bridge.parameters')}}
        print(freeze(response), flush=True)


if __name__ == '__main__':
    try:
        exit_code = main()
    except OSError:
        exit_code = 2
    # The reader may be blocked in stdin at EOF on the supervisor connection. Avoid interpreter shutdown
    # racing that daemon's buffered-I/O lock; every protocol response was explicitly flushed above.
    os._exit(exit_code)
