"""Structured commands and results kept apart from the reviewer's judgement."""

from dataclasses import asdict, dataclass
import json
import shlex
from typing import Protocol
from uuid import uuid4

from my_harness.core.engine.context import Command, ProjectContext
from my_harness.core.engine.evidence import ContentEvidence
from my_harness.core.engine.journal import EngineJournal, JournalError
from my_harness.core.engine.junit import JUnitReport, capture_junit, observe_report


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float | None = None
    error: str | None = None
    timed_out: bool = False
    capture_json: str | None = None

    @property
    def passed(self) -> bool:
        if self.capture_json is not None:
            try:
                capture = json.loads(self.capture_json)
                if capture['group_state'] != 'dead' or any(
                        capture['streams'][name]['complete'] is not True for name in ('stdout', 'stderr')):
                    return False
            except (ValueError, KeyError, TypeError):
                return False
        return type(self.exit_code) is int and self.exit_code == 0 and not self.error and not self.timed_out


def command_result_payload(result: CommandResult) -> dict:
    data = asdict(result)
    if result.capture_json is None:
        data.pop('capture_json')
    return data


class CommandRunner(Protocol):
    def run(self, context: ProjectContext, command: Command) -> CommandResult: ...


@dataclass(frozen=True)
class ValidationEntry:
    command: Command | None
    requested: str
    result: CommandResult
    command_id: str | None = None
    reports: tuple[JUnitReport, ...] = ()


@dataclass(frozen=True)
class ValidationReport:
    evidence: ContentEvidence
    entries: tuple[ValidationEntry, ...]
    run_id: str | None = None
    source_attempt_id: str | None = None

    @property
    def all_passed(self) -> bool:
        # A report never proves the command succeeded. Failures observed in a
        # new report are an additional gate, without rewriting exit/stdout/stderr.
        return all(entry.result.passed and not any(
            report.freshness in ('created', 'changed') and report.status in ('complete', 'partial')
            and any(case.result in ('failed', 'error') for case in report.cases)
            for report in entry.reports) for entry in self.entries)


def validation_payload(report: ValidationReport, *, include_cases: bool = True) -> dict:
    """The binary original is only delivered by download, never in prompts/polling."""
    data = asdict(report)
    for entry, source in zip(data['entries'], report.entries):
        entry['result'] = command_result_payload(source.result)
    if include_cases and not any(entry.reports for entry in report.entries):
        data.pop('run_id')
        data.pop('source_attempt_id')
        for entry in data['entries']:
            entry.pop('command_id')
            entry.pop('reports')
        return data
    for entry in data['entries']:
        for imported in entry['reports']:
            imported['original_available'] = imported.pop('original_base64') is not None
            imported['case_count'] = len(imported['cases'])
            if not include_cases:
                imported.pop('cases')
    return data


def run_command(context: ProjectContext, runner: CommandRunner, command: Command,
                journal: EngineJournal | None = None) -> CommandResult:
    return run_identified_command(context, runner, command, journal)[0]


def run_identified_command(context, runner, command, journal):
    identity = journal.command_started(command) if journal else str(uuid4())
    try:
        context.path(command.cwd)
        if hasattr(runner, 'run_managed'):
            if journal is None:
                raise JournalError("Managed commands require a durable journal")
            result = runner.run_managed(context, command, identity)
        else:
            result = runner.run(context, command)
    except JournalError:
        raise
    except Exception as exc:
        result = CommandResult(None, error=f"{type(exc).__name__}: {exc}")
    if journal:
        journal.command_finished(identity, result)
    return result, identity


def run_validations(context: ProjectContext, task: dict, evidence: ContentEvidence,
                    runner: CommandRunner, journal: EngineJournal | None = None, *,
                    run_id: str | None = None, source_attempt_id: str | None = None) -> ValidationReport:
    # The profile baseline is trusted configuration; the contract does not authorize a shell.
    commands: list[tuple[str, Command | None, str | None]] = []
    seen: set[Command] = set()
    # A task command differs from a profile validation run at the root without extra environment only by the
    # default timeout: it is that authorized validation and runs once, instead of being refused as another command.
    # A validation with its own cwd or environment is never adopted silently.
    profile = {command.argv: command for command in context.profile.validations
               if command.cwd == '.' and not command.environment}
    for text in task["validation_commands"]:
        try:
            argv = tuple(shlex.split(text))
            if not any(argv[:len(prefix)] == prefix for prefix in context.profile.allowed_command_prefixes if prefix):
                raise ValueError("Validation argv outside profile command policy")
            command = profile.get(argv) or Command(argv)
        except ValueError as exc:
            commands.append((text, None, str(exc)))
            continue
        if command not in seen:
            seen.add(command)
            commands.append((text, command, None))
    for command in context.profile.validations:
        if command not in seen:
            seen.add(command)
            commands.append((shlex.join(command.argv), command, None))
    entries = []
    for text, command, error in commands:
        declarations = tuple(d for d in context.profile.junit_reports if d.command == command)
        before = tuple(observe_report(context, d.path) for d in declarations)
        result, identity = ((CommandResult(None, error=error), None) if error
                            else run_identified_command(context, runner, command, journal))
        reports = tuple(capture_junit(context, d, observation) for d, observation in zip(declarations, before))
        entries.append(ValidationEntry(command, text, result, identity if declarations else None, reports))
    # Only commands selected exactly by argv/cwd/environment/timeout import reports.
    has_reports = any(entry.reports for entry in entries)
    return ValidationReport(evidence, tuple(entries), run_id if has_reports else None,
                            source_attempt_id if has_reports else None)
