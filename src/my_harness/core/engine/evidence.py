"""Evidence supplied through a port; policy without file restorations."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Protocol

from my_harness.core.engine.context import ProjectContext, relative_path


@dataclass(frozen=True)
class ContentEvidence:
    base_revision: str
    fingerprint: str
    changed_paths: tuple[str, ...]
    diff: str
    # Frozen provenance from the capturer (e.g. Git trees). None: synthetic or
    # legacy evidence, never certifiable as the content of a commit.
    provenance_json: str | None = None


def strip_empty_provenance(value):
    """Keeps the earlier serialized/prompt shape when there is no provenance."""
    if isinstance(value, dict):
        return {key: strip_empty_provenance(item) for key, item in value.items()
                if not (key == "provenance_json" and item is None)}
    if isinstance(value, (list, tuple)):
        return [strip_empty_provenance(item) for item in value]
    return value


class EvidenceCapture(Protocol):
    def capture(self, context: ProjectContext) -> ContentEvidence: ...


@dataclass(frozen=True)
class PathPolicyResult:
    violations: tuple[str, ...]

    @property
    def hard_failure(self) -> bool:
        return bool(self.violations)


def matches(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def check_paths(context: ProjectContext, task: dict, evidence: ContentEvidence) -> PathPolicyResult:
    from my_harness.core.engine.documents import executor_protected
    violations = []
    for path in evidence.changed_paths:
        try:
            relative_path(path)
            context.path(path)
        except ValueError:
            violations.append(path)
            continue
        sensitive = (matches(path, context.profile.sensitive_paths)
                     and not matches(path, context.profile.sensitive_allowlist))
        if (sensitive or executor_protected(context, task["task_id"], path)
                or matches(path, task["forbidden_paths"]) or not matches(path, task["allowed_paths"])):
            violations.append(path)
    return PathPolicyResult(tuple(sorted(set(violations))))
