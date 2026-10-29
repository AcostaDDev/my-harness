"""P002-T005 (D286): deterministic graph nodes call typed domain commands directly (D275).

The idempotency key is the node's deterministic operation key (D282), so a node replayed after a resume or a crash
receives the stored outcome of its command instead of performing it again. A domain command is committed or absent
in one transaction (FL13), so there is no sealed-but-uncertain state to reconcile. The harness caller is bound here
from the thread, never from node state.
"""
from typing import Any, Mapping

from my_harness.orchestration.operations import operation_key


def domain_command(config: Mapping, operations, root: str, operation_id: str, arguments: Mapping[str, Any],
                   references: Mapping[str, str] | None = None) -> dict:
    """Runs the current catalogue version of `operation_id` for the thread's project root; returns primitives."""
    from my_harness.services.domain_operations import harness_caller
    entry = operations.catalogue.current(operation_id)
    key = operation_key(config, f'domain:{entry.id}@{entry.version}', references or {})
    caller = harness_caller(root, channel='graph', thread_id=config['configurable']['thread_id'], operation_key=key)
    outcome = operations.execute(caller, entry.ref, dict(arguments), key)
    return outcome.body()
