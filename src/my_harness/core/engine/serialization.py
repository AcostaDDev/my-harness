"""Versioned JSON codec, without pickle or storage dependencies."""

from dataclasses import asdict
import json
from pathlib import Path

from my_harness.core.engine.acceptance import AcceptanceDecision
from my_harness.core.engine.context import Command, EnginePolicy, JUnitDeclaration, ProjectContext, ProjectProfile
from my_harness.core.engine.contracts import (
    AgentRequest, AgentResult, Attempt, OperationalStop, RunHistory, Selection, freeze,
)
from my_harness.core.engine.evidence import ContentEvidence, PathPolicyResult, strip_empty_provenance
from my_harness.core.engine.review import ReviewCycle
from my_harness.core.engine.validation import CommandResult, ValidationEntry, ValidationReport
from my_harness.core.engine.junit import JUnitReport, TestCase


def restore_command(data: dict) -> Command:
    return Command(tuple(data["argv"]), data["cwd"], tuple(tuple(item) for item in data["environment"]),
                   data["timeout_seconds"])


def restore_context(snapshot: str) -> ProjectContext:
    data = json.loads(snapshot)
    if data.get('capabilities') == 'project-intake-1':
        from my_harness.core.engine.context import IntakeContext
        policy = data['policy']
        for key in ('executor_models', 'executor_efforts', 'executor_effort_vocabulary'):
            if key in policy:
                policy[key] = tuple(policy[key])
        return IntakeContext(Path(data['root']), EnginePolicy(**policy), data['next_steps_file'],
                             data['state_file'], data['documents'], data.get('work_language'))
    profile = data["profile"]
    for key in ("preparation", "validations"):
        profile[key] = tuple(restore_command(item) for item in profile[key])
    profile['junit_reports'] = tuple(JUnitDeclaration(restore_command(item['command']), item['path'], item['coverage'])
                                     for item in profile.get('junit_reports', []))
    profile["allowed_command_prefixes"] = tuple(tuple(item) for item in profile["allowed_command_prefixes"])
    for key in ("protected_paths", "sensitive_paths", "sensitive_allowlist", "formatter_argv", "formatter_paths"):
        profile[key] = tuple(profile[key])
    profile["data_model_paths"] = tuple(profile.get("data_model_paths", ()))
    policy = data["policy"]
    for key in ("executor_models", "executor_efforts", "executor_effort_vocabulary"):
        if key in policy:
            policy[key] = tuple(policy[key])
    return ProjectContext(Path(data["root"]), ProjectProfile(**profile), EnginePolicy(**policy),
                          data["next_steps_file"], data["state_file"], data.get("documents"),
                          data.get("work_language"))


def restore_request(data: dict) -> AgentRequest:
    return AgentRequest(**{**data, "selection": Selection(**data["selection"])})


def _evidence(data: dict) -> ContentEvidence:
    return ContentEvidence(**{**data, "changed_paths": tuple(data["changed_paths"])})


def _has_provenance(history: RunHistory) -> bool:
    evidence = [cycle.evidence for cycle in history.cycles]
    evidence += [cycle.validation.evidence for cycle in history.cycles]
    evidence += [cycle.before_execution for cycle in history.cycles if cycle.before_execution]
    if history.acceptance:
        evidence.append(history.acceptance.evidence)
    return any(item.provenance_json is not None for item in evidence)


def dump_history(history: RunHistory) -> str:
    # Without provenance or CLI data the exact format 1 shape is kept (H2.2).
    data = strip_empty_provenance(asdict(history))
    has_cli = any(attempt.result.status is not None or attempt.result.metadata_json is not None
                  for attempt in history.attempts)
    version = 3 if _has_provenance(history) else 2 if has_cli else 1
    has_prompts = history.prompt_catalog_json is not None or any(a.request.prompt_snapshot_json for a in history.attempts)
    if has_prompts:
        version = 4
    else:
        data.pop("prompt_catalog_json")
        for attempt in data["attempts"]:
            attempt["request"].pop("prompt_snapshot_json", None)
    has_permissions = any(a.request.permission_snapshot_json is not None for a in history.attempts)
    if has_permissions:
        version = 5
    else:
        for attempt in data['attempts']:
            attempt['request'].pop('permission_snapshot_json', None)
    has_reports = any(entry.reports for cycle in history.cycles for entry in cycle.validation.entries)
    if has_reports:
        version = 6
    else:
        for cycle in data['cycles']:
            cycle['validation'].pop('run_id', None)
            cycle['validation'].pop('source_attempt_id', None)
            for entry in cycle['validation']['entries']:
                entry.pop('reports', None)
                entry.pop('command_id', None)
    has_capture = any(entry.result.capture_json is not None
                      for cycle in history.cycles for entry in cycle.validation.entries)
    has_capture |= any(json.loads(item).get('result', {}).get('capture_json') is not None
                       for item in history.preparation_json)
    if has_capture:
        version = 7
    if any(cycle.formatting_json is not None for cycle in history.cycles):
        version = 8
    else:
        for cycle in data['cycles']:
            cycle.pop('formatting_json')
    for cycle in data['cycles']:
        for entry in cycle['validation']['entries']:
            if entry['result']['capture_json'] is None:
                entry['result'].pop('capture_json')
    if not has_cli:
        for attempt in data["attempts"]:
            attempt["result"].pop("status")
            attempt["result"].pop("metadata_json")
    return freeze({"format": version, "history": data})


def load_history(snapshot: str) -> RunHistory:
    value = json.loads(snapshot)
    if value["format"] not in {1, 2, 3, 4, 5, 6, 7, 8}:
        raise ValueError("Unknown managed history format")
    data = value["history"]
    data["attempts"] = tuple(Attempt(restore_request(item["request"]), AgentResult(**item["result"]))
                             for item in data["attempts"])
    cycles = []
    for item in data["cycles"]:
        report = item["validation"]
        def restore_report(data):
            cases = tuple(TestCase(**{**case, 'suite': tuple(case['suite'])}) for case in data['cases'])
            return JUnitReport(**{**data, 'cases': cases, 'diagnostics': tuple(data['diagnostics'])})
        entries = tuple(ValidationEntry(restore_command(entry["command"]) if entry["command"] else None,
                                       entry["requested"], CommandResult(**entry["result"]), entry.get('command_id'),
                                       tuple(restore_report(r) for r in entry.get('reports', [])))
                        for entry in report["entries"])
        cycles.append(ReviewCycle(item["number"], _evidence(item["evidence"]),
                                  PathPolicyResult(tuple(item["policy"]["violations"])),
                                  ValidationReport(_evidence(report["evidence"]), entries, report.get('run_id'),
                                                   report.get('source_attempt_id')), item["review_json"],
                                  _evidence(item["before_execution"]) if item["before_execution"] else None,
                                  item["permission_denials_json"], item.get("formatting_json")))
    data["cycles"] = tuple(cycles)
    data["preparation_json"] = tuple(data["preparation_json"])
    data["stop"] = OperationalStop(**data["stop"]) if data["stop"] else None
    data["stops"] = tuple(OperationalStop(**item) for item in data["stops"])
    if data["acceptance"]:
        item = data["acceptance"]
        data["acceptance"] = AcceptanceDecision(item["eligible"], tuple(item["reasons"]), _evidence(item["evidence"]))
    return RunHistory(**data)
