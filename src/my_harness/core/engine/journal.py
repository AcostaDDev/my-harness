"""Optional persistence port; writes precede effects."""

from typing import Protocol, TYPE_CHECKING

from my_harness.core.engine.contracts import AgentRequest, RunHistory
from my_harness.core.engine.context import Command
if TYPE_CHECKING:
    from my_harness.core.engine.validation import CommandResult


class JournalError(RuntimeError):
    """A failed write stops the flow without further external calls."""


class EngineJournal(Protocol):
    def checkpoint(self, history: RunHistory, stage: str) -> None: ...
    def agent_started(self, history: RunHistory, request: AgentRequest) -> AgentRequest | None: ...
    def command_started(self, command: Command) -> str: ...
    def command_finished(self, identity: str, result: "CommandResult") -> None: ...
