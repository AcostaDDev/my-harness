"""Route a claimed chat job through the versioned graph and the managed invocation ledger."""
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from my_harness.i18n import tr
from my_harness.orchestration.operations import operation_key
from my_harness.orchestration.registry import GraphDefinition, GraphRegistry
from my_harness.orchestration.runner import GraphRunner
from my_harness.storage.operation_journal import InvocationOperation


class ChatState(TypedDict):
    run_id: str


def execute_chat_job(repository, claim, journal, work):
    """The scheduler retains ownership. The graph persists routing and the run journal owns chat result history."""
    thread_id = f'chat-turn-{claim.id}'
    history = None
    failure = None

    def chat(state: ChatState, config: RunnableConfig):
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
        graph = StateGraph(ChatState)
        graph.add_node('chat', chat)
        graph.add_edge(START, 'chat')
        graph.add_edge('chat', END)
        return graph

    registry = GraphRegistry([GraphDefinition('chat-turn', '1', build)])
    result = GraphRunner(repository.engine, registry).start('chat-turn', thread_id, {'run_id': claim.run_id})
    if result.status != 'COMPLETED' or history is None:
        raise RuntimeError(tr('orchestration.chat_graph_failed', thread=thread_id, status=result.status,
                              reason=result.reason)) from failure
    return history
