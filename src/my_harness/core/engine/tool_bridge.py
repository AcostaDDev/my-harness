"""D275/D281: small portable broker contract. No transport, persistence or provider imports."""
from dataclasses import dataclass, replace
import json

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.domain_catalogue import CATALOGUE, ID, NUMBER, SHA, _object, digest
from my_harness.i18n import tr

FORMAT = 'scoped-tools-1'
PROTOCOL = '2024-11-05'
PROTOCOLS = (PROTOCOL, '2025-03-26', '2025-06-18')
MAX_MESSAGE = 2 * 1024 * 1024 + 8192
MAX_RESPONSE = 128 * 1024
MC = tuple(f'MC{i}' for i in range(1, 8))
KEY = {'type': 'string', 'minLength': 1, 'maxLength': 180, 'pattern': r'\S'}
TOOLS = (
    {'name': 'search_tools', 'description': 'Search bounded descriptors in the invocation scope.',
     'inputSchema': _object({'query': {'type': 'string', 'maxLength': 200},
                            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                            'cursor': {'type': 'string', 'maxLength': 100}, 'key': KEY}, ('key',))},
    {'name': 'describe_tool', 'description': 'Load one exact scoped operation schema on demand.',
     'inputSchema': _object({'id': ID, 'version': NUMBER, 'key': KEY}, ('id', 'version', 'key'))},
    {'name': 'invoke_tool', 'description': 'Invoke a scoped operation; discovery never grants authority.',
     'inputSchema': _object({'id': ID, 'version': NUMBER, 'schema_sha256': SHA,
                            'arguments': {'type': 'object', 'additionalProperties': True}, 'key': KEY},
                           ('id', 'version', 'schema_sha256', 'arguments', 'key'))},
)
NAMES = tuple(t['name'] for t in TOOLS)
SURFACE_SHA256 = digest({'format': FORMAT, 'tools': TOOLS, 'protocols': PROTOCOLS})


@dataclass(frozen=True)
class Qualification:
    client: str
    version: str
    role: str
    evidence: str
    capabilities: tuple[str, ...] = MC
    provenance: str = 'native'

    def admit(self, client, version, role):
        missing = set(MC) - set(self.capabilities)
        if ((client, version, role) != (self.client, self.version, self.role) or missing
                or self.provenance not in ('native', 'simulated')):
            raise ValueError(tr('bridge.capabilities', missing=','.join(sorted(missing)) or 'client/version/role'))


# Exact historical T002 cells only. No executor, judge, later version or model-quality extrapolation.
NATIVE = tuple(Qualification(client, version, 'reviewer', 'P002-T002-stdio-readonly')
               for client, version in (('claude', '2.1.312'), ('codex', '0.165.0')))


def qualification(cells, client, version, role, evidence=None):
    for cell in cells:
        if (cell.client, cell.version, cell.role) == (client, version, role) and (
                evidence is None or cell.evidence == evidence):
            cell.admit(client, version, role)
            return cell
    raise ValueError(tr('bridge.capabilities', missing='client/version/role'))


def policy(request, refs, cell, *, catalogue=CATALOGUE):
    """Trusted request assembly only, before fenced agent_started; never called with model output.
    The native attempt stores this selection inside its immutable request, without changing old snapshots.
    """
    snapshot = json.loads(request.prompt_snapshot_json or '{}')
    marker = snapshot.get('canonical_context', {})
    role = request.role
    cell.admit(marker.get('client'), cell.version, role)
    if not marker.get('id') or 'scoped_tools' in snapshot:
        raise ValueError(tr('bridge.policy'))
    refs = sorted(set(tuple(r) for r in refs))
    allowed = {e.ref for e in catalogue.scoped('agent', role, frozenset(refs))}
    if len(refs) > 1000 or not refs or set(refs) != allowed:
        raise ValueError(tr('bridge.policy'))
    if role == 'judge':
        from my_harness.core.engine.judge import marker_check
        marker_check(snapshot, role, frozenset(refs))
    snapshot['scoped_tools'] = {'format': FORMAT, 'client': cell.client, 'version': cell.version,
                                'role': role, 'evidence': cell.evidence, 'provenance': cell.provenance,
                                'surface_sha256': SURFACE_SHA256,
                                'tools': [list(r) for r in refs]}
    return replace(request, prompt_snapshot_json=freeze(snapshot))


def selection(request, *, catalogue=CATALOGUE):
    snapshot = json.loads(request['prompt_snapshot_json'] or '{}')
    marker = snapshot.get('scoped_tools')
    if not isinstance(marker, dict) or set(marker) != {
            'format', 'client', 'version', 'role', 'evidence', 'provenance', 'tools', 'surface_sha256'}:
        raise ValueError(tr('bridge.policy'))
    refs = marker['tools']
    role = request['role']
    if (marker['format'] != FORMAT or marker['surface_sha256'] != SURFACE_SHA256 or marker['role'] != role or
            snapshot.get('canonical_context', {}).get('client') != marker['client'] or
            not isinstance(refs, list) or not 1 <= len(refs) <= 1000):
        raise ValueError(tr('bridge.policy'))
    refs = frozenset(tuple(r) for r in refs)
    if refs != frozenset(e.ref for e in catalogue.scoped('agent', role, refs)):
        raise ValueError(tr('bridge.policy'))
    if role == 'judge':
        from my_harness.core.engine.judge import marker_check
        marker_check(snapshot, role, refs)
    return marker, refs


def descriptor(entry):
    return {'id': entry.id, 'version': entry.version, 'schema_sha256': entry.schema_sha256,
            'summary': entry.summary[:240], 'kind': entry.kind}


def measure(entries, selected):
    """Canonical serialized UTF-8 bytes, not native tokens or a latency/quality estimate."""
    size = lambda value: len(freeze(value).encode('utf-8'))
    return {'method': 'canonical-json-utf8-bytes', 'entries': len(entries),
            'initial_surface_bytes': size({'tools': TOOLS}),
            'descriptors_bytes': size([descriptor(e) for e in selected]),
            'selected_schemas_bytes': size([e.document() for e in selected]),
            'full_catalogue_bytes': size([e.document() for e in entries]),
            'logical_exchanges': 3, 'setup_exchanges': 2}
