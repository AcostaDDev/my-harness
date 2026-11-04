"""P002-T016 (D276, D283, D299): the autonomous roadmap graph.

One loop node advances the run by one decided action; a hold node waits (interrupt) for an owner stop or for
harness jobs, holding no process, lease or transaction. Graph state is the run identity and a cycle counter only:
authority, decisions, bounds and evidence stay in SQLite and the service. Every delegated effect runs through
`run_operation` with the deterministic key of its loop step, so a replay reconciles and an uncertain effect stops
the thread `RECOVERY_REQUIRED` (D282). The segment limit bounds one durable segment, never the roadmap length.
"""
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from my_harness.orchestration.operations import JournalPort, operation_key, run_operation
from my_harness.orchestration.registry import DEFAULT_SEGMENT_LIMIT, GraphDefinition, GraphRegistry
from my_harness.orchestration.runner import GraphRunner, wait_for

GRAPH_ID = 'autonomous-roadmap'
GRAPH_VERSION = '1'


class RoadmapState(TypedDict):
    run_id: str
    cycle: int
    route: str


def definition(service, *, segment_limit=DEFAULT_SEGMENT_LIMIT) -> GraphDefinition:
    def advance(state: RoadmapState, config: RunnableConfig):
        thread, root, origin = service.journal_port(state['run_id'])
        port = JournalPort(service.journal, thread, root, origin=origin)
        outcome = service.advance(
            state['run_id'],
            key=lambda name, refs: operation_key(config, name, refs),
            perform=lambda name, kind, refs, effect: run_operation(port, config, name, kind, refs, effect))
        return {'cycle': state['cycle'] + 1, 'route': outcome['route']}

    def hold(state: RoadmapState):
        wait_for('roadmap_hold', {'run_id': state['run_id'], 'cycle': str(state['cycle'])})
        return {'route': 'continue'}

    def build():
        graph = StateGraph(RoadmapState)
        graph.add_node('advance', advance)
        graph.add_node('hold', hold)
        graph.add_edge(START, 'advance')
        graph.add_conditional_edges('advance', lambda state: state['route'],
                                    {'continue': 'advance', 'hold': 'hold', 'end': END})
        graph.add_edge('hold', 'advance')
        return graph

    return GraphDefinition(GRAPH_ID, GRAPH_VERSION, build, segment_limit=segment_limit)


class RoadmapGraphs:
    """Runner operations the service needs, bound to the registered roadmap definition."""

    def __init__(self, engine, service, *, segment_limit=DEFAULT_SEGMENT_LIMIT):
        self.runner = GraphRunner(engine, GraphRegistry([definition(service, segment_limit=segment_limit)]))

    def start_or_status(self, run_id, thread_id):
        try:
            existing = self.runner.status(thread_id)
        except LookupError:
            return self.runner.start(GRAPH_ID, thread_id, {'run_id': run_id, 'cycle': 0, 'route': 'continue'})
        return existing

    def resume(self, thread_id):
        return self.runner.resume(thread_id, {'resumed': True})

    def recover(self, thread_id):
        return self.runner.recover(thread_id, writer_stopped=True)

    def prepare_recovery(self, thread_id):
        """After owner-confirmed reconciliation, a RECOVERY_REQUIRED thread may continue its last checkpoint."""
        if self.runner.status(thread_id).status == 'RECOVERY_REQUIRED':
            self.runner.threads.transition(thread_id, ('RECOVERY_REQUIRED',), 'RUNNING', reason='owner_reconciled')

    def revoke(self, thread_id):
        try:
            if self.runner.status(thread_id).status in ('RUNNING', 'WAITING'):
                return self.runner.revoke(thread_id)
        except LookupError:
            return None
        return None

    def status(self, thread_id):
        return self.runner.status(thread_id)
