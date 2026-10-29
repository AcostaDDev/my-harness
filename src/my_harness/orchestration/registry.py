"""Versioned graph definitions (D283). LangGraph itself ignores graph drift on resume (T002 probe), so every thread
is stamped with the declared version and a structural fingerprint, and the runner compares both before any node.

The fingerprint covers nodes, edges, conditional branches with their declared ends, join edges and state channels.
Changing a node's body or a branch's routing without changing that structure needs a new declared version.
"""
from dataclasses import dataclass
import hashlib
import json
from typing import Callable

from langgraph.graph import StateGraph

from my_harness.i18n import tr

DEFAULT_SEGMENT_LIMIT = 50


@dataclass(frozen=True)
class GraphDefinition:
    graph_id: str
    version: str
    build: Callable[[], StateGraph]
    # LangGraph's recursion limit for one durable segment; it never bounds the length of a whole run.
    segment_limit: int = DEFAULT_SEGMENT_LIMIT

    def __post_init__(self):
        if not self.graph_id or not self.version or self.segment_limit < 1:
            raise ValueError(tr('orchestration.graph_definition', graph=self.graph_id or '?'))


def fingerprint(builder: StateGraph) -> str:
    structure = {
        'nodes': sorted(builder.nodes),
        'edges': sorted(list(edge) for edge in builder.edges),
        'branches': sorted([source, name, sorted((branch.ends or {}).items())]
                           for source, branches in builder.branches.items() for name, branch in branches.items()),
        'joins': sorted([sorted(starts), end] for starts, end in builder.waiting_edges),
        'channels': sorted(builder.channels),
    }
    return hashlib.sha256(json.dumps(structure, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class GraphRegistry:
    def __init__(self, definitions=()):
        self._definitions: dict[str, GraphDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: GraphDefinition) -> None:
        if definition.graph_id in self._definitions:
            raise ValueError(tr('orchestration.graph_duplicate', graph=definition.graph_id))
        self._definitions[definition.graph_id] = definition

    def get(self, graph_id: str) -> GraphDefinition | None:
        return self._definitions.get(graph_id)
