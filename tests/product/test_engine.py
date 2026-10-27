"""H2.1 characterization in temporary Git checkouts, fake ports only.

The reference is never imported or executed. No provider is called and no
real stacks are validated. Git is only used to create the test repository.
"""

from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess

import pytest

from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.core.engine.acceptance import assess_acceptance
from my_harness.core.engine.context import Command, EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.contracts import AgentResult, ContractError, freeze
from my_harness.core.engine.evidence import check_paths
from my_harness.core.engine.planning import deterministic_task, next_task_id
from my_harness.core.engine.validation import CommandResult, run_validations
from my_harness.core.engine.workflow import OfflineEngine


TASK_ID = "P001-T001"
PHASE_ID = "P001"
SELECTION = {"model": "synthetic-executor", "effort": "medium", "reason": "Synthetic task routing"}
PLAN = """# Synthetic plan
## Shared constraints
Preserve all existing changes.
## P001-T001 — First task
**Objective:** Implement the synthetic behavior.
**Allowed paths:** `app/**`
**Acceptance criteria:**
- New behavior is observable.
- Existing behavior remains valid.
**Validation commands:** `test-runner check`
**Executor:** synthetic-executor / medium — Synthetic task routing
## P001-T002 — Next task
**Objective:** Not part of this run.
"""


@pytest.fixture
def context(tmp_path):
    checkout = tmp_path / "synthetic-checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True, capture_output=True)
    (checkout / "app").mkdir()
    (checkout / "app/main.txt").write_text("baseline", encoding="utf-8")
    profile = ProjectProfile("synthetic", validations=(Command(("test-runner", "check")),),
                             allowed_command_prefixes=(("test-runner",),), protected_paths=("docs/**",),
                             sensitive_paths=(".env*",), sensitive_allowlist=(".env.example",))
    policy = EnginePolicy(("synthetic-executor", "synthetic-other"), ("medium", "high"),
                          "synthetic-planner", "medium", "synthetic-reviewer", "high")
    return ProjectContext(checkout, profile, policy)


def review(default_verdict="ACCEPT", **kwargs):
    data = {"task_id": TASK_ID, "verdict": default_verdict, "findings": [], "blocking_questions": [], "scope_grants": []}
    if default_verdict == "REVISE":
        data.update(next_prompt="Fix the synthetic finding", executor_selection=dict(SELECTION), findings=[{
            "severity": "high", "category": "testing", "file": "app/main.txt", "problem": "Still missing behavior",
        }])
    data.update(kwargs)
    return data


def edit(text="implemented", payload=None):
    def response(context, request):
        context.path("app/main.txt").write_text(text, encoding="utf-8")
        return payload if payload is not None else {"result": "synthetic"}
    return response


def harness(context, responses, commands=(), paths=("app/main.txt", "app/new.txt", "docs/state.txt", ".env", ".env.example")):
    agents = ScriptedAgentAdapter(responses)
    runner = ScriptedCommandRunner(commands)
    workspace = SyntheticWorkspace(context, paths)
    return OfflineEngine(agents, runner, workspace), agents, runner, workspace


def start(engine, context):
    return engine.start(context, TASK_ID, PHASE_ID, PLAN)


def test_deterministic_contract_and_task_selection(context):
    task = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    assert task["acceptance_criteria"] == ["New behavior is observable.", "Existing behavior remains valid."]
    assert task["forbidden_paths"] == ["docs/**"]
    assert "Shared constraints" in task["implementation_constraints"][0]
    assert "deterministic" in task["contract_source"]
    assert task["executor_selection"] == SELECTION
    assert next_task_id(PLAN, None) == TASK_ID
    assert next_task_id(PLAN, TASK_ID) == "P001-T002"
    assert next_task_id(PLAN, "P001-T002") is None
    with pytest.raises(ContractError):
        next_task_id(PLAN, "P999-T999")
    with pytest.raises(ContractError):
        next_task_id(PLAN + "\n## P001-T001 — duplicate", None)


def test_flow_is_offline_with_fresh_independent_requests(context, monkeypatch):
    engine, agents, runner, workspace = harness(context, [edit(), review()])
    def forbidden(*args, **kwargs):
        raise AssertionError("No process allowed during offline flow")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = start(engine, context)
    assert result.status == "acceptance_ready"
    assert result.acceptance.eligible
    assert [item.role for item in agents.requests] == ["executor", "reviewer"]
    assert len({item.id for item in agents.requests}) == 2
    assert all(item.fresh_session for item in agents.requests)
    assert all(item.task_json == result.task_json and item.context_json == result.context_json for item in agents.requests)
    assert len(runner.calls) == 1  # task/baseline deduplicated
    assert runner.calls[0][0].root == context.root
    prompt = json.loads(json.loads(agents.requests[-1].prompt_snapshot_json)["parts"][0]["variables"]["INPUT_JSON"])
    assert prompt["evidence"]["fingerprint"] == result.cycles[0].evidence.fingerprint
    assert prompt["validation"]["entries"][0]["result"]["exit_code"] == 0
    assert not hasattr(result.acceptance, "commit")
    assert context.path("app/main.txt").read_text() == "implemented"


def test_incomplete_auto_plan_calls_one_fresh_planner(context):
    contract = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    engine, agents, _, _ = harness(context, [contract, edit(), review()])
    result = engine.start(context, TASK_ID, PHASE_ID, "# Incomplete plan")
    assert result.status == "acceptance_ready"
    assert [item.role for item in agents.requests] == ["planner", "executor", "reviewer"]
    assert agents.requests[0].task_json is None
    assert len({item.id for item in agents.requests}) == 3


def test_forced_agent_plan_and_invalid_identity_are_not_retried(context):
    context = replace(context, policy=replace(context.policy, planning_mode="agent"))
    contract = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    contract["task_id"] = "P001-T999"
    engine, agents, _, _ = harness(context, [contract])
    result = start(engine, context)
    assert result.status == "stopped" and result.stop.stage == "planner"
    assert len(result.attempts) == len(agents.requests) == 1
    assert result.attempts[0].result.payload_json == freeze(contract)


def test_deterministic_mode_does_not_call_planner_on_missing_contract(context):
    context = replace(context, policy=replace(context.policy, planning_mode="deterministic"))
    engine, agents, _, _ = harness(context, [])
    result = engine.start(context, TASK_ID, PHASE_ID, "# Incomplete")
    assert result.stop.stage == "planner"
    assert not agents.requests


def test_complete_contract_with_disallowed_model_does_not_fallback(context):
    engine, agents, _, _ = harness(context, [])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN.replace("synthetic-executor /", "disallowed-model /"))
    assert result.stop.stage == "planner"
    assert "policy" in result.stop.reason
    assert not agents.requests


@pytest.mark.parametrize("failure", [
    RuntimeError("Synthetic quota/auth error"),
    AgentResult('{"result":"partial"}', terminal_observed=False, raw_output="partial bytes"),
    AgentResult('{"result":"exit failure"}', terminal_observed=True, exit_code=7),
    AgentResult('{"broken":', terminal_observed=True, exit_code=0, raw_output="invalid bytes"),
    AgentResult('{"is_error":true,"reason":"synthetic auth"}', terminal_observed=True, exit_code=0),
    AgentResult('{"invalid":NaN}', terminal_observed=True, exit_code=0),
    AgentResult('{"result":"exit is not an integer"}', terminal_observed=True, exit_code=False),
])
def test_executor_failure_preserves_attempt_without_retry_or_review(context, failure):
    engine, agents, runner, _ = harness(context, [failure])
    result = start(engine, context)
    assert result.status == "stopped" and result.stop.stage == "executor"
    assert result.cycles == () and result.acceptance is None
    assert len(result.attempts) == len(agents.requests) == 1
    assert result.attempts[0].result.error or result.attempts[0].result.payload_json
    assert not runner.calls


def test_planner_provider_error_has_no_fallback(context):
    engine, agents, _, _ = harness(context, [RuntimeError("Synthetic planner error")])
    result = engine.start(context, TASK_ID, PHASE_ID, "# Incomplete")
    assert result.stop.stage == "planner"
    assert len(result.attempts) == len(agents.requests) == 1


def test_reviewer_error_keeps_validation_and_changes(context):
    engine, agents, _, _ = harness(context, [edit(), RuntimeError("Synthetic reviewer failure")])
    result = start(engine, context)
    assert result.stop.stage == "reviewer"
    assert result.cycles[0].validation.all_passed
    assert result.cycles[0].review_json is None
    assert context.path("app/main.txt").read_text() == "implemented"
    assert len(result.attempts) == 2


def test_revise_uses_explicit_selection_new_session_and_preserves_all_history(context):
    selection = {"model": "synthetic-other", "effort": "high", "reason": "Explicit correction"}
    engine, agents, _, _ = harness(context, [edit("first"), review("REVISE", executor_selection=selection), edit("second"), review()])
    result = start(engine, context)
    assert result.status == "acceptance_ready" and result.revisions == 1
    assert [cycle.verdict for cycle in result.cycles] == ["REVISE", "ACCEPT"]
    assert [item.role for item in agents.requests] == ["executor", "reviewer", "executor", "reviewer"]
    assert asdict(agents.requests[2].selection) == selection
    assert agents.requests[0].selection.model == "synthetic-executor"
    assert len({item.id for item in agents.requests}) == 4
    assert result.cycles[0].evidence.fingerprint != result.cycles[1].evidence.fingerprint
    assert agents.requests[0].task_json == agents.requests[2].task_json


def test_revision_budget_is_not_replenished_by_resume_or_explicit_retry(context):
    context = replace(context, policy=replace(context.policy, max_revision_cycles=1))
    engine, agents, _, _ = harness(context, [edit("first"), review("REVISE"), edit("second"), review("REVISE"), review("REVISE")])
    initial = start(engine, context)
    assert initial.status == "revision_limit" and initial.revisions == 1
    previous_attempts = initial.attempts
    retried = engine.resume(context, initial, retry_executor=True)
    assert retried.attempts == previous_attempts
    resumed = engine.resume(context, initial)
    assert resumed.status == "revision_limit" and resumed.revisions == 1
    assert resumed.attempts[:-1] == previous_attempts
    assert resumed.cycles[:-1] == initial.cycles
    assert initial.cycles[-1].number == 1 and resumed.cycles[-1].number == 2
    assert len([item for item in agents.requests if item.role == "executor"]) == 2


def test_revalidation_is_new_review_without_executor_or_replanning(context):
    engine, agents, _, _ = harness(context, [edit(), review("BLOCKED", blocking_questions=["Synthetic question"]), review()])
    initial = start(engine, context)
    assert initial.status == "blocked" and initial.stop is None
    original_bytes = context.path("app/main.txt").read_bytes()
    resumed = engine.resume(context, initial)
    assert resumed.status == "acceptance_ready"
    assert resumed.revisions == initial.revisions == 0
    assert resumed.attempts[:-1] == initial.attempts and resumed.cycles[:-1] == initial.cycles
    assert [item.role for item in agents.requests] == ["executor", "reviewer", "reviewer"]
    assert context.path("app/main.txt").read_bytes() == original_bytes
    assert initial.status == "blocked" and len(initial.attempts) == 2


def test_explicit_retry_after_error_consumes_budget_and_preserves_failed_attempt(context):
    engine, agents, _, _ = harness(context, [RuntimeError("Synthetic failed execution"), edit(), review()])
    initial = start(engine, context)
    resumed = engine.resume(context, initial, retry_executor=True)
    assert resumed.status == "acceptance_ready" and resumed.revisions == 1
    assert resumed.attempts[0] == initial.attempts[0]
    assert resumed.attempts[1].request.id != initial.attempts[0].request.id
    assert resumed.attempts[1].request.selection == initial.attempts[0].request.selection
    assert resumed.stops == initial.stops == (initial.stop,)
    assert resumed.stop is None


def test_resume_rejects_changed_context_and_unrelated_changes_without_erasing(context):
    engine, agents, _, _ = harness(context, [edit(), review("BLOCKED")])
    initial = start(engine, context)
    modified_context = replace(context, policy=replace(context.policy, max_revision_cycles=99))
    with pytest.raises(ContractError, match="frozen"):
        engine.resume(modified_context, initial)
    context.path("docs").mkdir()
    context.path("docs/state.txt").write_text("external changes", encoding="utf-8")
    resumed = engine.resume(context, initial)
    assert resumed.stop.stage == "resume" and resumed.attempts == initial.attempts
    assert context.path("docs/state.txt").read_text() == "external changes"
    assert context.path("app/main.txt").read_text() == "implemented"


def test_no_progress_loop_stops_before_another_executor(context):
    engine, agents, _, _ = harness(context, [edit(), review("REVISE"), {"result": "no changes"}, review("REVISE")])
    result = start(engine, context)
    assert result.stop.stage == "revision"
    assert result.revisions == 1 and len(agents.requests) == 4
    assert "same findings" in result.stop.reason


def test_changed_validation_allows_correction_despite_unchanged_files(context):
    engine, agents, _, _ = harness(context, [edit(), review("REVISE"), {"result": "no edits"},
                                             review("REVISE"), edit("corrected"), review()],
                                  [CommandResult(1), CommandResult(0), CommandResult(0)])
    result = start(engine, context)
    assert result.status == "acceptance_ready" and result.revisions == 2
    assert result.cycles[0].evidence == result.cycles[1].evidence
    assert not result.cycles[0].validation.all_passed and result.cycles[1].validation.all_passed
    assert len(agents.requests) == 6


def test_incidental_denial_does_not_override_accept_review(context):
    engine, agents, _, _ = harness(context, [{"permission_denials": [{"tool": "incidental"}]}, review()])
    result = start(engine, context)
    assert result.status == "acceptance_ready" and result.acceptance.eligible
    assert result.revisions == 0 and len(agents.requests) == 2


def test_revalidation_after_malformed_review_requires_explicit_correction(context):
    engine, agents, _, _ = harness(context, [edit(), {"task_id": TASK_ID}, review("REVISE"), edit("corrected"), review()])
    initial = start(engine, context)
    assert initial.stop.stage == "reviewer" and initial.cycles[0].verdict is None
    resumed = engine.resume(context, initial)
    assert resumed.status == 'stopped' and resumed.revisions == 0
    assert resumed.stop.stage == 'revision'
    assert resumed.cycles[0] == initial.cycles[0]
    assert resumed.attempts[:2] == initial.attempts
    assert resumed.stops[0] == initial.stop
    assert len(agents.requests) == 3
    corrected = engine.resume(context, resumed, retry_executor=True)
    assert corrected.status == 'acceptance_ready' and corrected.revisions == 1
    assert corrected.attempts[:3] == resumed.attempts
    assert len(agents.requests) == 5


def test_denied_no_change_revision_stops_without_fallback(context):
    engine, agents, _, _ = harness(context, [{"permission_denials": [{"tool": "synthetic-tool"}]}, review("REVISE")])
    result = start(engine, context)
    assert result.stop.stage == "permissions" and result.revisions == 0
    assert json.loads(result.cycles[0].permission_denials_json)[0]["tool"] == "synthetic-tool"
    assert len(agents.requests) == 2


@pytest.mark.parametrize("fields", [
    {"blocking_questions": ["Decision needed"]}, {"scope_grants": [{"path": "other/**"}]},
])
def test_scope_and_product_decisions_do_not_start_automatic_revisions(context, fields):
    engine, agents, _, _ = harness(context, [edit(), review("REVISE", **fields)])
    result = start(engine, context)
    assert result.stop.stage == "permissions" and result.revisions == 0
    assert json.loads(result.task_json)["allowed_paths"] == ["app/**"]
    assert len(agents.requests) == 2


@pytest.mark.parametrize("fields", [
    {"task_id": "wrong-task"}, {"verdict": "unknown"}, {"verdict": []}, {"executor_selection": None}, {"next_prompt": ""},
])
def test_invalid_review_is_retained_without_new_call(context, fields):
    engine, agents, _, _ = harness(context, [edit(), review("REVISE", **fields)])
    result = start(engine, context)
    assert result.stop.stage == "reviewer"
    assert result.cycles[0].review_json is not None
    assert len(agents.requests) == 2


@pytest.mark.parametrize("command_result", [CommandResult(1), CommandResult(None, timed_out=True), RuntimeError("Synthetic validation error")])
def test_accept_review_cannot_override_failed_validation(context, command_result):
    engine, agents, _, _ = harness(context, [edit(), review()], [command_result])
    result = start(engine, context)
    assert result.stop.stage == "acceptance" and not result.acceptance.eligible
    assert result.cycles[0].verdict == "ACCEPT"
    assert not result.cycles[0].validation.all_passed
    assert len(agents.requests) == 2


@pytest.mark.parametrize("path", ["docs/state.txt", ".env"])
def test_accept_review_cannot_override_file_policy_and_does_not_restore(context, path):
    def out_of_scope(context, request):
        context.path(path).parent.mkdir(parents=True, exist_ok=True)
        context.path(path).write_text("preserved synthetic bytes", encoding="utf-8")
        return {"result": "done"}
    engine, agents, _, _ = harness(context, [out_of_scope, review()])
    result = start(engine, context)
    assert result.stop.stage == "acceptance" and not result.acceptance.eligible
    assert result.cycles[0].policy.violations == (path,)
    assert context.path(path).read_text() == "preserved synthetic bytes"


@pytest.mark.parametrize("fields", [{"blocking_questions": ["Still unresolved"]}, {"scope_grants": [{"path": "app/**"}]}])
def test_accept_cannot_leave_questions_or_grants(context, fields):
    engine, _, _, _ = harness(context, [edit(), review(**fields)])
    result = start(engine, context)
    assert result.stop.stage == "acceptance" and not result.acceptance.eligible


def test_content_change_during_validation_requires_revalidation(context):
    def mutating_command(context, command):
        context.path("app/main.txt").write_text("changed by validation", encoding="utf-8")
        return CommandResult(0)
    engine, agents, _, _ = harness(context, [edit()], [mutating_command])
    result = start(engine, context)
    assert result.stop.stage == "validation"
    assert result.cycles[0].validation.all_passed and result.cycles[0].review_json is None
    assert len(agents.requests) == 1


def test_content_change_during_review_invalidates_acceptance(context):
    def external_edit(context, request):
        context.path("app/new.txt").write_text("new untracked synthetic file", encoding="utf-8")
        return review()
    engine, _, _, workspace = harness(context, [edit(), external_edit])
    result = start(engine, context)
    assert result.stop.stage == "acceptance" and not result.acceptance.eligible
    assert "Content changed" in result.stop.reason
    assert not assess_acceptance(result.cycles[0], workspace.capture(context), context).eligible


def test_validation_argv_order_dedup_errors_empty_and_missing_duration(context):
    _, _, runner, workspace = harness(context, [])
    task = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    task["validation_commands"] = ["test-runner focused", "test-runner check", "test-runner focused", "unknown check"]
    report = run_validations(context, task, workspace.capture(context), runner)
    assert [entry.requested for entry in report.entries] == ["test-runner focused", "test-runner check", "unknown check"]
    assert [command.argv for _, command in runner.calls] == [("test-runner", "focused"), ("test-runner", "check")]
    assert report.entries[-1].result.exit_code is None and not report.all_passed
    assert report.entries[0].result.duration_seconds is None
    empty_context = replace(context, profile=replace(context.profile, validations=()))
    task["validation_commands"] = []
    empty = run_validations(empty_context, task, workspace.capture(context), runner)
    assert empty.entries == () and empty.all_passed


def test_task_command_equal_to_profile_validation_reuses_its_authorized_timeout(context):
    # The profile authorizes its validation with a non-default timeout; the task names the same argv.
    profile = replace(context.profile, validations=(Command(("test-runner", "check"), timeout_seconds=600),))
    context = replace(context, profile=profile)
    _, _, runner, workspace = harness(context, [])
    task = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    task["validation_commands"] = ["test-runner check", "test-runner focused"]
    report = run_validations(context, task, workspace.capture(context), runner)
    assert [entry.requested for entry in report.entries] == ["test-runner check", "test-runner focused"]
    assert [command for _, command in runner.calls] == [profile.validations[0], Command(("test-runner", "focused"))]
    assert report.all_passed


def test_preparation_failure_is_operational_and_preserves_result_without_agents(context):
    profile = replace(context.profile, preparation=(Command(("prepare", "first")), Command(("prepare", "second"))))
    context = replace(context, profile=profile)
    engine, agents, runner, _ = harness(context, [], [CommandResult(2, stderr="synthetic environment unavailable")])
    result = start(engine, context)
    assert result.stop.stage == "preparation" and result.task_json is None
    assert len(result.preparation_json) == len(runner.calls) == 1
    assert json.loads(result.preparation_json[0])["result"]["stderr"] == "synthetic environment unavailable"
    assert not agents.requests and not result.cycles


def test_context_rejects_traversal_and_symlinks_and_isolated_projects(context, tmp_path):
    other_root = tmp_path / "second"
    other_root.mkdir()
    other = replace(context, root=other_root)
    for path in ("../external", "/external", "app/../../external"):
        with pytest.raises(ValueError):
            context.path(path)
    context.path("app/link").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        context.path("app/link/external")
    assert other.path("app/main.txt") != context.path("app/main.txt")
    workspace = SyntheticWorkspace(context, ("app/main.txt",))
    with pytest.raises(ValueError):
        workspace.capture(other)
    evidence = replace(workspace.capture(context), changed_paths=("../external",))
    task = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    assert check_paths(context, task, evidence).hard_failure


def test_read_only_task_can_revalidate_but_cannot_retry_execution(context):
    engine, agents, _, _ = harness(context, [{"result": "assessment"}, review("BLOCKED"), review()])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN.replace("`app/**`", "none"))
    with pytest.raises(ContractError, match="Read-only"):
        engine.resume(context, result, retry_executor=True)
    resumed = engine.resume(context, result)
    assert resumed.status == "acceptance_ready" and resumed.cycles[-1].evidence.changed_paths == ()
    assert len(agents.requests) == 3


def stack_profile():
    """Synthetic Django/Docker stack profile: its rules live in data, never in the core."""
    web = ("docker", "compose", "exec", "-T", "web", "python")
    return ProjectProfile(
        "synthetic-stack",
        preparation=(Command(("docker", "info", "--format", "{{.ServerVersion}}")),),
        validations=(Command(("python", "-m", "ruff", "check", "src")),
                     Command((*web, "manage.py", "check")),
                     Command((*web, "manage.py", "test", "--noinput"))),
        allowed_command_prefixes=(("python",), ("docker", "compose")),
        formatter_argv=("python", "-m", "ruff", "format", "--"),
        formatter_paths=("src/**/*.py",),
        executor_instructions="Run the Django tests on PostgreSQL via Docker.",
    )


def test_stack_rules_are_in_declarative_profile_not_core(context, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Profiles must not launch processes")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    profile = stack_profile()
    assert any("docker" in command.argv for command in profile.preparation)
    assert any("manage.py" in command.argv for command in profile.validations)
    assert "PostgreSQL" in profile.executor_instructions
    assert profile.formatter_argv == ("python", "-m", "ruff", "format", "--")
    core = Path(__file__).resolve().parents[2] / "src/my_harness/core/engine"
    assert not any(word in path.read_text() for path in core.glob("*.py")
                   for word in ("Django", "docker", "PostgreSQL", "manage.py", "ruff"))
    # The generic profile already walks the same flow without stack exceptions.
    engine, _, _, _ = harness(context, [edit(), review()])
    assert start(engine, context).status == "acceptance_ready"
    stack = replace(context, profile=profile)
    engine, agents, runner, _ = harness(stack, [edit(), review()])
    result = engine.start(stack, TASK_ID, PHASE_ID, PLAN.replace("`test-runner check`", ""))
    assert result.status == "acceptance_ready"
    assert tuple(command for _, command in runner.calls) == profile.preparation + profile.validations
    assert len(agents.requests) == 2


def test_snapshots_do_not_share_mutable_adapter_payloads(context):
    original_review = review("BLOCKED")
    engine, agents, _, _ = harness(context, [edit(), original_review])
    result = start(engine, context)
    original_review["verdict"] = "ACCEPT"
    original_review["blocking_questions"].append("Changed later")
    assert result.cycles[0].verdict == "BLOCKED"
    assert json.loads(result.cycles[0].review_json)["blocking_questions"] == []
    task_copy = json.loads(result.task_json)
    task_copy["allowed_paths"].append("external/**")
    assert json.loads(result.task_json)["allowed_paths"] == ["app/**"]
    assert agents.requests[0].task_json == result.task_json


def test_zero_revision_budget_keeps_initial_execution_and_review(context):
    context = replace(context, policy=replace(context.policy, max_revision_cycles=0))
    engine, agents, _, _ = harness(context, [edit(), review("REVISE")])
    result = start(engine, context)
    assert result.status == "revision_limit" and result.revisions == 0
    assert [request.role for request in agents.requests] == ["executor", "reviewer"]
