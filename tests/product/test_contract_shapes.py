"""D056: agent output shapes match the engine validators.

A real Codex planner (D055) read "argv commands" literally and returned
`validation_commands` as argv arrays, which the engine rejected. Offline only:
scripted agents, or synthetic CLIs through the real adapter.
"""
from dataclasses import replace
import json
import shlex

import pytest

from my_harness.core.engine.contracts import command_text, freeze, task_contract
from my_harness.core.engine.planning import deterministic_task
from my_harness.core.engine.prompts import builtin_catalog, output_schema, render_attempt
from my_harness.services.local_config import load_local_config
from test_agent_roles import journey, v2
from test_engine import PHASE_ID, PLAN, TASK_ID, context, edit, harness, review  # noqa: F401 (fixture)
from test_local_config import launches, setup, write  # noqa: F401 (fixture)
from test_typescript_profile import repository, web  # noqa: F401 (fixtures)

OBSERVED = [["test-runner", "check"]]  # Form returned by the real planner, adapted to this profile.


def agent_plan(context, commands):
    contract = json.loads(deterministic_task(context, TASK_ID, PHASE_ID, PLAN))
    return {**contract, "validation_commands": commands}


@pytest.mark.parametrize("argv", [
    ["npm", "run", "test"],
    ["test-runner", "check", "two words"],
    ["tool", "--flag=$HOME", "&&", "rm", "-rf", "x"],
    ["tool", "it's", '"quoted"', "back\\slash"],
])
def test_argv_arrays_round_trip_exactly_through_the_frozen_string(argv):
    assert shlex.split(command_text(argv)) == argv
    assert command_text("npm run test") == "npm run test"


def test_planner_argv_arrays_are_frozen_as_strings_and_run_once(context):
    context = replace(context, policy=replace(context.policy, planning_mode="agent"))
    plan = agent_plan(context, OBSERVED)
    engine, agents, runner, _ = harness(context, [plan, edit(), review()])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert result.status == "acceptance_ready", result.stop
    assert json.loads(result.task_json)["validation_commands"] == ["test-runner check"]
    # The agent's original output is kept unchanged in its attempt.
    assert json.loads(result.attempts[0].result.payload_json)["validation_commands"] == OBSERVED
    # Same argv as the profile validation: deduplicated, one run.
    assert len(runner.calls) == 1 and runner.calls[0][1].argv == ("test-runner", "check")
    assert [entry.requested for entry in result.cycles[0].validation.entries] == ["test-runner check"]


@pytest.mark.parametrize("commands", [
    [[]], [["test-runner", 3]], [["test-runner", ""]], [[["nested"]]], [{"argv": ["test-runner"]}],
    "test-runner check", [None],
])
def test_other_shapes_still_stop_the_planner_without_retry(context, commands):
    context = replace(context, policy=replace(context.policy, planning_mode="agent"))
    engine, agents, _, _ = harness(context, [agent_plan(context, commands)])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert result.status == "stopped" and result.stop.stage == "planner"
    assert result.stop.reason == "Invalid task validation_commands"
    assert len(result.attempts) == len(agents.requests) == 1


def test_server_contracts_must_already_be_canonical_strings(context):
    contract = agent_plan(context, OBSERVED)
    engine, agents, _, _ = harness(context, [])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN, contract=freeze(contract))
    assert result.stop.stage == "planner" and "canonical" in result.stop.reason
    assert not agents.requests


def test_output_schemas_declare_element_types_without_new_required_fields():
    planner = output_schema("planner")
    for field in ("allowed_paths", "forbidden_paths", "acceptance_criteria", "validation_commands"):
        assert planner["properties"][field]["items"] == {"type": "string"}
    assert "shell-free" in planner["properties"]["validation_commands"]["description"]
    assert planner["properties"]["executor_selection"]["required"] == ["model", "effort", "reason"]
    reviewer = output_schema("reviewer")
    assert reviewer["required"] == ["task_id", "verdict"]
    finding = reviewer["properties"]["findings"]["items"]
    assert finding["type"] == "object" and finding["required"] == ["severity", "category", "file", "problem"]
    assert reviewer["properties"]["executor_selection"]["type"] == ["object", "null"]
    phase = output_schema("phase")
    assert phase["required"] == ["phase_id", "verdict", "summary", "exit_criteria_results",
                                 "required_actions", "blocking_questions"]
    result = phase["properties"]["exit_criteria_results"]["items"]
    assert result["properties"]["passed"] == {"type": "boolean"}
    assert output_schema("chat")["properties"]["proposals"]["items"]["properties"]["validation"]["items"] == {
        "type": "string"}
    assert all(output_schema("bootstrap")["properties"][field]["items"] == {"type": "string"}
               for field in ("requirements", "alternatives", "pending_decisions"))


def test_rendered_planner_prompt_asks_for_command_strings(context):
    text, snapshot = render_attempt(builtin_catalog(), "plan-task", {"INPUT_JSON": "{}"}, context)
    assert "one shell-free string per command (never argv arrays)" in text
    assert '"validation_commands":{"description":' in text and '"items":{"type":"string"}' in text
    assert json.loads(snapshot)["output_schema"] == output_schema("planner")


@pytest.mark.parametrize('forbidden', ['**', '*', 'src/**', 'src/estimate.ts'])
def test_contradictory_planner_scope_stops_before_writer_or_validation(context, forbidden):
    context = replace(context, policy=replace(context.policy, planning_mode='agent'))
    plan = {**agent_plan(context, []), 'allowed_paths': ['src/estimate.ts'], 'forbidden_paths': [forbidden]}
    engine, agents, runner, _ = harness(context, [plan])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert result.status == 'stopped' and result.stop.stage == 'planner'
    assert result.stop.reason == 'Task allowed path is also forbidden: src/estimate.ts'
    assert len(result.attempts) == len(agents.requests) == 1 and not runner.calls and not result.cycles
    assert json.loads(result.attempts[0].result.payload_json)['forbidden_paths'] == [forbidden]


def test_scope_exceptions_remain_valid_and_planner_prompt_explains_precedence(context):
    plan = {**agent_plan(context, []), 'allowed_paths': ['src/**'], 'forbidden_paths': ['src/private/**']}
    assert json.loads(task_contract(context, plan, TASK_ID, PHASE_ID))['forbidden_paths'] == ['src/private/**']
    text, snapshot = render_attempt(builtin_catalog(), 'plan-task', {'INPUT_JSON': '{}'}, context)
    assert 'forbidden patterns take precedence' in text
    assert 'never use * or **' in json.loads(snapshot)['output_schema']['properties']['forbidden_paths']['description']


def test_claude_planner_returning_argv_arrays_reaches_acceptance_through_the_real_adapter(setup, repository):
    """D055 regression: Claude reviewer → Codex executor, the planner answers with argv arrays."""
    context, data, folder, tmp_path = setup
    changed = v2(data, "claude", "codex")
    changed["agents"]["reviewer"]["environment"]["PROBE_VALIDATION"] = json.dumps([["npm", "run", "test"]])
    changed["projects"][0]["commands"]["authorized"] = [{"argv": ["npm", "run", "test"], "timeout_seconds": 1800}]
    config = load_local_config(write(folder, changed))
    job, record = journey(repository, config, "argv-arrays")
    assert record.status == "ACCEPTANCE_READY", record.history.stop
    assert json.loads(record.history.task_json)["validation_commands"] == ["npm run test"]
    entries = record.history.cycles[0].validation.entries
    # The planned command is the profile validation with the same argv: it runs once, with the profile timeout.
    planned = [entry for entry in entries if entry.command.argv == ("npm", "run", "test")]
    assert len(planned) == 1 and planned[0].requested == "npm run test" and planned[0].result.exit_code == 0
    assert [json.loads(line)["provider"] for line in launches(tmp_path)] == ["claude", "codex", "claude"]
