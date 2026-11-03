"""Route a claimed phase job through the versioned graph and the managed invocation ledger."""
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from my_harness.i18n import tr
from my_harness.orchestration.operations import operation_key
from my_harness.orchestration.registry import GraphDefinition, GraphRegistry
from my_harness.orchestration.runner import GraphRunner
from my_harness.storage.operation_journal import InvocationOperation


class PhaseState(TypedDict):
    run_id: str


def execute_phase_job(repository, claim, journal, work):
    """The scheduler retains ownership. The graph persists routing and the run journal owns phase result history."""
    thread_id = f'phase-job-{claim.id}'
    history = None
    failure = None

    def phase(state: PhaseState, config: RunnableConfig):
        nonlocal history, failure

        def invocation(current):
            refs = {'run_id': state['run_id'], 'attempt_number': str(len(current.attempts) + 1)}
            key = operation_key(config, 'agent_invocation', refs)
            return InvocationOperation(thread_id, key, refs, origin={'kind': 'managed_job', 'id': str(claim.id)})

        journal.invocation_operation = invocation
        try:
            history = work()
        except Exception as exc:
            failure = exc
            raise
        finally:
            journal.invocation_operation = None
        return {}

    def build():
        graph = StateGraph(PhaseState)
        graph.add_node('phase', phase)
        graph.add_edge(START, 'phase')
        graph.add_edge('phase', END)
        return graph

    registry = GraphRegistry([GraphDefinition('managed-phase', '1', build)])
    result = GraphRunner(repository.engine, registry).start('managed-phase', thread_id, {'run_id': claim.run_id})
    if result.status != 'COMPLETED' or history is None:
        raise RuntimeError(tr('orchestration.phase_graph_failed', thread=thread_id, status=result.status,
                              reason=result.reason)) from failure
    return history
