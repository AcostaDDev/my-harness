"""Deterministic operation identities for graph nodes (D282; INV-02, INV-05, INV-06).

A node re-executes from its start after a resume or a crash. It therefore performs an effect only through an
`OperationPort`: the intent is sealed under a key derived from the thread, the node's position in the run and the
domain references, so a replay finds the same operation. The production journal is P002-T006; T003 defines this
interface and exercises it with a synthetic journal only.
"""
from dataclasses import dataclass, field
import hashlib
import json
from typing import Callable, Mapping, Protocol

from my_harness.i18n import tr


@dataclass(frozen=True)
class OperationRecord:
    key: str
    kind: str
    state: str
    created: bool = False
    result: Mapping = field(default_factory=dict)


class OperationPort(Protocol):
    def seal(self, key: str, kind: str, references: Mapping[str, str]) -> OperationRecord:
        """Seals the intent or returns the existing record for `key` (`created` only on the first seal)."""

    def complete(self, key: str, result: Mapping) -> OperationRecord:
        """Records the outcome of a sealed intent once."""


class OperationUncertain(RuntimeError):
    """A sealed intent has no recorded outcome: the effect may have happened, so it is never reissued."""

    def __init__(self, key: str):
        super().__init__(tr('orchestration.operation_uncertain', operation=key))
        self.key = key


def operation_key(config: Mapping, name: str, references: Mapping[str, str]) -> str:
    """Same thread, step, task path, name and references after a replay; a later loop iteration has another step."""
    metadata = config.get('metadata', {})
    material = {'thread': config['configurable']['thread_id'], 'step': metadata.get('langgraph_step'),
                'node': metadata.get('langgraph_node'), 'path': [str(part) for part in metadata.get('langgraph_path', ())],
                'name': name, 'references': dict(sorted(references.items()))}
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return f'op-{digest[:40]}'


def run_operation(port: OperationPort, config: Mapping, name: str, kind: str, references: Mapping[str, str],
                  effect: Callable[[], Mapping]) -> OperationRecord:
    """Seal, then perform once; a replay reconciles a completed operation and stops on an uncertain one."""
    key = operation_key(config, name, references)
    record = port.seal(key, kind, references)
    if record.state == 'COMPLETED':
        return record
    if not record.created:
        raise OperationUncertain(key)
    return port.complete(key, effect())
