"""D280 runtime hygiene: no hosted tracing inherited from the environment, never imports LangGraph itself.

LangSmith reads `LANGSMITH_*`/`LANGCHAIN_*` from the process environment and would post graph inputs and outputs
(T002 tracing probe). The variables are removed before the first LangGraph import, and every graph call also runs
inside a disabled tracing context. Agent CLIs receive their own explicit environment, so nothing else depends on them.
"""
import os

TRACING_PREFIXES = ('LANGSMITH_', 'LANGCHAIN_')


def scrub_environment(environ=os.environ) -> list[str]:
    removed = sorted(name for name in environ if name.startswith(TRACING_PREFIXES))
    for name in removed:
        del environ[name]
    return removed


def disabled_tracing():
    from langsmith import tracing_context
    return tracing_context(enabled=False)
