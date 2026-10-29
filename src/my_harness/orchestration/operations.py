"""Deterministic operation identities for graph nodes (D282; INV-02, INV-05, INV-06).

A node re-executes from its start after a resume or a crash. It therefore performs an effect only through an
`OperationPort`: the intent is sealed under a key derived from the thread, the node's position in the run and the
domain references, so a replay finds the same operation. `JournalPort` binds the production journal of P002-T006
(D287) to one thread and project root; tests may still use a synthetic journal.
"""
from dataclasses import dataclass, field
import hashlib
import json
from typing import Callable, Mapping, Protocol

from my_harness.i18n import tr


TERMINAL = ('COMPLETED', 'FAILED', 'ABANDONED')


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


class JournalPort:
    """`OperationPort` over `storage.operation_journal.OperationJournal` for one thread and project root: it seals and
    completes generic sealed effects only, and every replay or completion is checked against its root."""

    def __init__(self, journal, thread_id: str, root: str, *, origin: Mapping | None = None):
        self.journal, self.thread_id, self.root, self.origin = journal, thread_id, root, origin

    def seal(self, key: str, kind: str, references: Mapping[str, str]) -> OperationRecord:
        return self._record(self.journal.seal(self.thread_id, self.root, key, kind, references, origin=self.origin))

    def complete(self, key: str, result: Mapping) -> OperationRecord:
        return self._record(self.journal.complete(self.thread_id, self.root, key, result))

    @staticmethod
    def _record(plain: Mapping) -> OperationRecord:
        return OperationRecord(plain['key'], plain['kind'], plain['state'], plain['created'], plain['result'])


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
    """Seal, then perform once; a replay reconciles a settled operation and stops on an uncertain one.

    COMPLETED, FAILED and ABANDONED (D287) carry an outcome: the node receives the record and decides, never
    performing the effect again under the same key."""
    key = operation_key(config, name, references)
    record = port.seal(key, kind, references)
    if record.state in TERMINAL:
        return record
    if not record.created:
        raise OperationUncertain(key)
    return port.complete(key, effect())
