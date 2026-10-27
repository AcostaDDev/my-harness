"""Explicit context; no path derives from the engine location."""

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from my_harness.i18n import tr


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    cwd: str = "."
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: int = 1800

    def __post_init__(self):
        if not self.argv or not all(isinstance(arg, str) and arg for arg in self.argv):
            raise ValueError(tr('context.empty_invalid_command_argv'))
        if self.timeout_seconds <= 0:
            raise ValueError(tr('context.command_timeout_positive'))
        relative_path(self.cwd)


@dataclass(frozen=True)
class JUnitDeclaration:
    command: Command
    path: str
    coverage: str

    def __post_init__(self):
        path = relative_path(self.path)
        if path == PurePosixPath('.') or '.git' in path.parts or not self.coverage.strip():
            raise ValueError(tr('context.junit_requires_report_file'))


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Expected a checkout-relative path")
    return path


@dataclass(frozen=True)
class ProjectProfile:
    name: str
    preparation: tuple[Command, ...] = ()
    validations: tuple[Command, ...] = ()
    allowed_command_prefixes: tuple[tuple[str, ...], ...] = ()
    protected_paths: tuple[str, ...] = ()
    sensitive_paths: tuple[str, ...] = ()
    sensitive_allowlist: tuple[str, ...] = ()
    executor_instructions: str = ""
    # P009-T019 (D133): after each executor attempt, the engine formats with `formatter_argv + paths` the files changed
    # within the contract that match `formatter_paths`. The argv ends in `--`: no path is an option.
    formatter_argv: tuple[str, ...] = ()
    formatter_paths: tuple[str, ...] = ()
    junit_reports: tuple[JUnitDeclaration, ...] = ()
    # D088 point 6 (P008-T003): data model patterns; a diff touching them without the layout's data diagram is not
    # acceptable. Empty: the profile declares no persistence to watch.
    data_model_paths: tuple[str, ...] = ()

    def __post_init__(self):
        if len(self.junit_reports) > 8:
            raise ValueError(tr('context.most_eight_junit_reports'))
        if len({item.path for item in self.junit_reports}) != len(self.junit_reports):
            raise ValueError(tr('context.junit_report_paths_unique'))
        if self.formatter_argv and (self.formatter_argv[-1] != '--' or len(self.formatter_argv) < 2
                                    or not self.formatter_paths):
            raise ValueError(tr('context.formatter_needs_argv_ending'))


@dataclass(frozen=True)
class EnginePolicy:
    executor_models: tuple[str, ...]
    executor_efforts: tuple[str, ...]
    planner_model: str
    planner_effort: str
    reviewer_model: str
    reviewer_effort: str
    max_revision_cycles: int = 3
    planning_mode: str = "auto"
    # D052: `catalog` restricts to the catalog; `open` admits any model with a valid
    # shape and an effort from the executor provider's vocabulary. In `open` the
    # catalog remains the reference selection for server contracts.
    executor_mode: str = "catalog"
    executor_effort_vocabulary: tuple[str, ...] = ()

    def __post_init__(self):
        if self.max_revision_cycles < 0 or self.planning_mode not in {"auto", "deterministic", "agent"}:
            raise ValueError("Invalid engine policy")
        if not self.executor_models or not self.executor_efforts:
            raise ValueError(tr('context.explicit_executor_selections_required'))
        if not all((self.planner_model, self.planner_effort, self.reviewer_model, self.reviewer_effort)):
            raise ValueError(tr('context.explicit_planner_reviewer_selections'))
        if self.executor_mode not in {"catalog", "open"}:
            raise ValueError(tr('context.executor_selection_mode_catalog'))
        if self.executor_mode == "open" and not self.executor_effort_vocabulary:
            raise ValueError(tr('context.open_executor_selection_requires'))
        vocabulary = self.executor_effort_vocabulary
        if vocabulary and not set(self.executor_efforts) <= set(vocabulary):
            raise ValueError(tr('context.executor_efforts_outside_provider'))


def policy_payload(policy: EnginePolicy) -> dict:
    """Frozen shape; omits default D052 settings to preserve earlier snapshots."""
    data = asdict(policy)
    if data["executor_mode"] == "catalog":
        data.pop("executor_mode")
    if not data["executor_effort_vocabulary"]:
        data.pop("executor_effort_vocabulary")
    return data


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    profile: ProjectProfile
    policy: EnginePolicy
    next_steps_file: str = "docs/NEXT_STEPS.md"
    state_file: str = "docs/STATE.md"
    # D072/H6.3 and D088: per-phase document contract. Local configuration always composes "v2" (mandatory
    # unified layout); None only describes earlier frozen contexts, which are still read.
    documents: str | None = None
    # P011-T008 (D167): confirmed work language of the checkout (documentation and code). None in earlier frozen
    # contexts and in projects whose work language is not confirmed yet; it is never inferred.
    work_language: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "root", self.root.resolve(strict=True))
        if not self.root.is_dir():
            raise ValueError(tr('context.project_root_directory'))
        relative_path(self.next_steps_file)
        relative_path(self.state_file)
        if self.documents not in (None, "v2"):
            raise ValueError("Unknown document layout")
        if self.work_language not in (None, "en", "es"):
            raise ValueError(tr('context.unknown_work_language'))
        if self.documents and (PurePosixPath(self.state_file).parent != PurePosixPath(self.next_steps_file).parent
                               or PurePosixPath(self.state_file).parent == PurePosixPath(".")):
            raise ValueError(tr('context.document_layout_v2_keeps'))

    def path(self, relative: str) -> Path:
        candidate = self.root / relative_path(relative)
        # Also rejects inner links even when they point inside the checkout.
        if candidate.resolve() != candidate or not candidate.is_relative_to(self.root):
            raise ValueError(tr('context.checkout_path_contains_symlink'))
        return candidate


@dataclass(frozen=True)
class IntakeContext:
    """Documentary capabilities only (D218); deliberately has no executable profile."""

    root: Path
    policy: EnginePolicy
    next_steps_file: str = "docs/NEXT_STEPS.md"
    state_file: str = "docs/STATE.md"
    documents: str = "v2"
    work_language: str | None = None

    __post_init__ = ProjectContext.__post_init__
    path = ProjectContext.path


def profile_name(context):
    return context.profile.name if isinstance(context, ProjectContext) else None
