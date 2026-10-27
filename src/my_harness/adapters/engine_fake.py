"""Fake H2.1 ports; synthetic data only, no processes or network."""

from collections import deque
import hashlib

from my_harness.core.engine.context import Command, ProjectContext
from my_harness.core.engine.contracts import AgentRequest, AgentResult, freeze
from my_harness.core.engine.evidence import ContentEvidence
from my_harness.core.engine.validation import CommandResult
from my_harness.i18n import tr


class ScriptedAgentAdapter:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests: list[AgentRequest] = []

    def invoke(self, context: ProjectContext, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected agent invocation")
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(context, request)
        if isinstance(response, AgentResult):
            return response
        return AgentResult(freeze(response), terminal_observed=True, exit_code=0)


class ScriptedCommandRunner:
    def __init__(self, responses=()):
        self.responses = deque(responses)
        self.calls: list[tuple[ProjectContext, Command]] = []

    def run(self, context: ProjectContext, command: Command) -> CommandResult:
        self.calls.append((context, command))
        if not self.responses:
            return CommandResult(0)
        result = self.responses.popleft()
        if isinstance(result, Exception):
            raise result
        return result(context, command) if callable(result) else result


class SyntheticWorkspace:
    """Captures only explicit fixture paths. It is neither a Git capture nor a certificate.

    The synthetic baseline and the paths are supplied by the test. A real checkout
    will require an H2.4 Git adapter that discovers everything staged/untracked and the base.
    """

    def __init__(self, context: ProjectContext, paths: tuple[str, ...], base_revision: str = "synthetic-base"):
        self.root = context.root
        self.paths = paths
        self.base_revision = base_revision
        self.baseline = self._read(context)

    def _read(self, context: ProjectContext) -> dict[str, str | None]:
        if context.root != self.root:
            raise ValueError(tr('simulation.synthetic_workspace_belongs_different'))
        result = {}
        for path in self.paths:
            item = context.path(path)
            if item.exists() and not item.is_file():
                raise ValueError(tr('simulation.synthetic_evidence_regular_files'))
            result[path] = hashlib.sha256(item.read_bytes()).hexdigest() if item.exists() else None
        return result

    def capture(self, context: ProjectContext) -> ContentEvidence:
        current = self._read(context)
        changed = tuple(sorted(path for path in self.paths if current[path] != self.baseline[path]))
        fingerprint = hashlib.sha256(freeze([self.base_revision, current]).encode()).hexdigest()
        diff = freeze({path: {"before": self.baseline[path], "after": current[path]} for path in changed})
        return ContentEvidence(self.base_revision, fingerprint, changed, diff)
