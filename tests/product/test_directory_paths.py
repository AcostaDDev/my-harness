"""P009-T017 (D129): a directory entry of a task contract (`core/`) covers its files.

T008 froze `allowed_paths = ["core/", ...]` from the child's NEXT_STEPS; fnmatch never matched a file against it, so
the path policy flagged every executor file after execution and review. Offline only: scripted agents.
"""
from dataclasses import replace
import json

import pytest

from my_harness.core.engine.contracts import ContractError, freeze, task_contract
from my_harness.core.engine.evidence import ContentEvidence, check_paths
from test_contract_shapes import agent_plan
from test_engine import PHASE_ID, PLAN, TASK_ID, context, edit, harness, review  # noqa: F401 (fixture)
from test_git import make_context

# Contract and changed paths of run fc340afb (T008), without its prose.
T008_ALLOWED = ['core/', 'docs/DDBB-DIAGRAM.md', 'docs/flows/tasks.md']
T008_CHANGED = ('core/forms.py', 'core/migrations/0001_initial.py', 'core/models.py', 'core/templates/core/tasks.html',
                'core/tests.py', 'core/views.py', 'docs/DDBB-DIAGRAM.md', 'docs/flows/tasks.md')
SELECTION = {'model': 'synthetic-executor', 'effort': 'medium', 'reason': 'Synthetic reviewer choice'}


def contract(allowed, forbidden=()):
    return {'task_id': 'P001-T001', 'phase_id': 'P001', 'title': 't', 'objective': 'o', 'executor_prompt': 'p',
            'allowed_paths': list(allowed), 'forbidden_paths': list(forbidden), 'acceptance_criteria': ['c'],
            'validation_commands': [], 'executor_selection': SELECTION}


def evidence(*paths):
    return ContentEvidence('base', 'fingerprint', paths, 'diff')


@pytest.fixture
def child(tmp_path):
    return replace(make_context(tmp_path), documents='v2')


def test_t008_directory_allowlist_is_frozen_as_a_glob_and_covers_its_files(child):
    frozen = task_contract(child, contract(T008_ALLOWED), 'P001-T001', 'P001')
    task = json.loads(frozen)
    assert task['allowed_paths'] == ['core/**', 'docs/DDBB-DIAGRAM.md', 'docs/flows/tasks.md']
    assert task_contract(child, task, 'P001-T001', 'P001') == frozen  # idempotent
    assert check_paths(child, task, evidence(*T008_CHANGED)).violations == ()
    assert check_paths(child, task, evidence('config/urls.py', 'docs/STATE.md')).violations == (
        'config/urls.py', 'docs/STATE.md')


def test_contracts_frozen_before_keep_their_bytes_and_literal_reading(child):
    """Already frozen contracts are read as stored: fc340afb stays blocked, never reinterpreted."""
    frozen = task_contract(child, contract(T008_ALLOWED), 'P001-T001', 'P001')
    old = {**json.loads(frozen), 'allowed_paths': T008_ALLOWED}
    stored = freeze(old)
    assert json.loads(stored)['allowed_paths'] == T008_ALLOWED
    assert check_paths(child, json.loads(stored), evidence(*T008_CHANGED)).violations == T008_CHANGED[:6]


def test_directory_in_forbidden_paths_is_frozen_as_a_glob_and_takes_precedence(child):
    task = json.loads(task_contract(child, contract(['core/'], ['core/private/']), 'P001-T001', 'P001'))
    assert task['allowed_paths'] == ['core/**'] and task['forbidden_paths'][0] == 'core/private/**'
    assert check_paths(child, task, evidence('core/models.py', 'core/private/key.py')).violations == (
        'core/private/key.py',)
    with pytest.raises(ContractError, match='also forbidden: core/private/key.py'):
        task_contract(child, contract(['core/private/key.py'], ['core/private/']), 'P001-T001', 'P001')


def test_exact_paths_and_globs_are_frozen_unchanged(child):
    allowed = ['core/models.py', 'core/*.py', 'core/**', 'templates/**/*.html', 'core']
    task = json.loads(task_contract(child, contract(allowed, ['core/private/**']), 'P001-T001', 'P001'))
    assert task['allowed_paths'] == allowed and task['forbidden_paths'][0] == 'core/private/**'


def test_agent_planner_directory_entry_reaches_acceptance_without_a_policy_violation(context):
    context = replace(context, policy=replace(context.policy, planning_mode='agent'))
    plan = {**agent_plan(context, []), 'allowed_paths': ['app/']}
    engine, agents, runner, _ = harness(context, [plan, edit(), review()])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert result.status == 'acceptance_ready', result.stop
    assert json.loads(result.task_json)['allowed_paths'] == ['app/**']
    assert json.loads(result.attempts[0].result.payload_json)['allowed_paths'] == ['app/']  # agent output kept
    assert result.cycles[0].policy.violations == ()
    # The executor and the reviewer receive the same frozen scope that the path policy checks.
    assert all(json.loads(request.task_json)['allowed_paths'] == ['app/**'] for request in agents.requests[1:])
