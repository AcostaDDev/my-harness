"""Segment runner for versioned graph continuations (D282, D283).

A durable segment runs from a start, resume or recovery until the graph waits, ends or reaches the definition's
segment limit; at the limit the runner opens a new segment from the last synchronous checkpoint, so recursion
never caps the length of a valid run. Before any node of an existing thread runs, its stamped graph identity,
version and fingerprint are compared with the registered definition; a difference quarantines the thread.
A waiting thread holds no process, lease or transaction. Cancellation and revocation are recorded first and an
active segment observes them at the next superstep boundary.
"""
from dataclasses import dataclass, field
from typing import Any, Mapping

from langgraph.errors import GraphRecursionError
from langgraph.types import Command, interrupt

from my_harness.i18n import tr
from my_harness.orchestration.hygiene import disabled_tracing
from my_harness.orchestration.operations import OperationUncertain
from my_harness.orchestration.registry import GraphDefinition, GraphRegistry, fingerprint
from my_harness.orchestration.saver import HarnessCheckpointSaver, require_primitive
from my_harness.storage.graph_continuations import GraphContinuationRepository

STOPPED_BY_OWNER = ('CANCELLED', 'REVOKED')


@dataclass(frozen=True)
class SegmentResult:
    thread_id: str
    status: str
    segments: int
    reason: str | None = None
    detail: Mapping | None = None
    values: Mapping = field(default_factory=dict)


def wait_for(kind: str, payload: Mapping[str, Any]) -> Any:
    """A typed wait inside a node; everything before it in the node runs again on resume (INV-02)."""
    require_primitive(payload, kind)
    return interrupt({'kind': kind, 'payload': dict(payload)})


class GraphRunner:
    def __init__(self, engine, registry: GraphRegistry):
        self.registry = registry
        self.threads = GraphContinuationRepository(engine)
        self.saver = HarnessCheckpointSaver(engine)

    def start(self, graph_id: str, thread_id: str, state: Mapping[str, Any]) -> SegmentResult:
        self._writable()
        definition = self.registry.get(graph_id)
        if definition is None:
            raise LookupError(tr('orchestration.graph_unknown', graph=graph_id))
        require_primitive(dict(state), 'input')
        builder = definition.build()
        self.threads.create(thread_id, graph_id, definition.version, fingerprint(builder))
        return self._run(definition, builder, thread_id, dict(state))

    def resume(self, thread_id: str, value: Any) -> SegmentResult:
        self._writable()
        require_primitive(value, 'resume')
        checked = self._checked(thread_id, ('WAITING',))
        if isinstance(checked, SegmentResult):
            return checked
        definition, builder = checked
        self.threads.transition(thread_id, ('WAITING',), 'RUNNING')
        return self._run(definition, builder, thread_id, Command(resume=value))

    def recover(self, thread_id: str, *, writer_stopped: bool) -> SegmentResult:
        """Continues a RUNNING thread left by a crash; an expired owner is not proof of a stopped writer (INV-06)."""
        self._writable()
        if not writer_stopped:
            raise ValueError(tr('orchestration.writer_unconfirmed', thread=thread_id))
        checked = self._checked(thread_id, ('RUNNING',))
        if isinstance(checked, SegmentResult):
            return checked
        definition, builder = checked
        return self._run(definition, builder, thread_id, None)

    def cancel(self, thread_id: str, reason: str = 'owner_cancelled') -> SegmentResult:
        return self._stop(thread_id, 'CANCELLED', reason)

    def revoke(self, thread_id: str, reason: str = 'authority_revoked') -> SegmentResult:
        return self._stop(thread_id, 'REVOKED', reason)

    def status(self, thread_id: str) -> SegmentResult:
        row = self.threads.get(thread_id)
        return SegmentResult(row.id, row.status, row.segments, row.reason, row.detail)

    def _writable(self) -> None:
        if self.threads.query_only():
            raise PermissionError(tr('orchestration.read_only'))

    def _stop(self, thread_id: str, status: str, reason: str) -> SegmentResult:
        self._writable()
        self.threads.transition(thread_id, ('RUNNING', 'WAITING'), status, reason=reason)
        return self.status(thread_id)

    def _checked(self, thread_id: str, expected: tuple[str, ...]):
        """The registered definition and a fresh builder, or the quarantine result; no node has run yet."""
        row = self.threads.get(thread_id)
        if row.status not in expected:
            raise ValueError(tr('orchestration.thread_state', thread=thread_id, status=row.status,
                                expected=', '.join(expected)))
        stamped = {'graph_id': row.graph_id, 'version': row.graph_version, 'fingerprint': row.fingerprint}
        definition = self.registry.get(row.graph_id)
        if definition is None:
            return self._quarantine(row, 'graph_unknown', {'stamped': stamped, 'registered': None})
        builder = definition.build()
        registered = {'graph_id': definition.graph_id, 'version': definition.version,
                      'fingerprint': fingerprint(builder)}
        if registered != stamped:
            return self._quarantine(row, 'graph_version_mismatch', {'stamped': stamped, 'registered': registered})
        return definition, builder

    def _quarantine(self, row, reason: str, detail: dict) -> SegmentResult:
        self.threads.transition(row.id, (row.status,), 'QUARANTINED', reason=reason, detail=detail)
        return self.status(row.id)

    def _settle(self, thread_id: str, status: str, reason=None, detail=None, values=None) -> SegmentResult:
        """Ends the segment unless the owner stopped the thread meanwhile; that stop is kept as recorded."""
        try:
            self.threads.transition(thread_id, ('RUNNING',), status, reason=reason, detail=detail)
        except ValueError:
            if self.threads.get(thread_id).status not in STOPPED_BY_OWNER:
                raise
        result = self.status(thread_id)
        return SegmentResult(result.thread_id, result.status, result.segments, result.reason, result.detail,
                             values or {})

    def _run(self, definition: GraphDefinition, builder, thread_id: str, payload) -> SegmentResult:
        graph = builder.compile(checkpointer=self.saver)
        config = {'configurable': {'thread_id': thread_id}, 'recursion_limit': definition.segment_limit}
        with disabled_tracing():
            while True:
                self.threads.add_segment(thread_id)
                stream = graph.stream(payload, config, durability='sync', stream_mode='updates')
                try:
                    for _update in stream:
                        if self.threads.get(thread_id).status != 'RUNNING':
                            return self.status(thread_id)
                    break
                except GraphRecursionError:
                    payload = None
                except OperationUncertain as error:
                    return self._settle(thread_id, 'RECOVERY_REQUIRED', 'operation_uncertain',
                                        {'operation': error.key})
                except Exception as error:
                    return self._settle(thread_id, 'FAILED', 'node_failed', {'error': type(error).__name__})
                finally:
                    stream.close()
            snapshot = graph.get_state(config)
        if snapshot.interrupts:
            return self._settle(thread_id, 'WAITING', 'waiting',
                                {'waiting': [item.value for item in snapshot.interrupts]}, snapshot.values)
        if snapshot.next:
            return self._settle(thread_id, 'FAILED', 'unexpected_stop', {'next': list(snapshot.next)},
                                snapshot.values)
        return self._settle(thread_id, 'COMPLETED', values=snapshot.values)
