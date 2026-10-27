"""H4.3: real Node/npm/tsc, temporary Git/SQLite and fake agents.

The runner is a test port for this trusted fixture, not a product process
supervisor or a sandbox. The harness is not run on this repository.
"""

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from my_harness.adapters.engine_fake import ScriptedAgentAdapter
from my_harness.adapters.git import GitWorkspace, GitWorktrees
from my_harness.core.engine.commit import GitIdentity
from my_harness.core.engine.context import EnginePolicy, ProjectContext
from my_harness.core.engine.contracts import AgentResult, context_snapshot
from my_harness.core.engine.permissions import snapshot_entries, snapshot_payload
from my_harness.core.engine.serialization import dump_history, load_history, restore_context
from my_harness.core.engine.validation import CommandResult, run_command, run_validations
from my_harness.profiles.typescript_web import typescript_web_profile
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.permissions import PermissionRepository
from test_git import git


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/typescript_web"
CACHE = ROOT / ".local/npm-cache"
TASK, PHASE = "P001-T001", "P001"
IDENTITY = GitIdentity("Fixture Writer", "fixture@example.invalid")
VERSIONS = {"engine": "h4.3-test", "agent_adapter": "synthetic-1", "commands": "fixture-subprocess-1",
            "evidence": "git-1", "provider_cli": None,
            "node": "24.15.0", "npm": "11.12.1", "typescript": "5.9.3"}
PLAN = """# Synthetic web task
## P001-T001 — Correct the estimate
**Objective:** Calculate thirty minutes per task.
**Allowed paths:** `src/estimate.ts`
**Acceptance criteria:**
- Three tasks take ninety minutes and invalid inputs are rejected.
**Validation commands:**
**Executor:** synthetic-executor / medium — Explicit offline selection
"""


class FixtureCommandRunner:
    """Runs argv without a shell, with a checked cwd and an explicit environment without credentials.

    npm runs scripts of the trusted fixture. Its cache is configured apart from the
    profile; an empty cache fails, without downloading or replacing the result.
    """

    def __init__(self, temporary, cache=CACHE):
        temporary.mkdir()
        for name in ("user.npmrc", "global.npmrc"):
            (temporary / name).write_text("")
        self.calls = []
        self.executables = {name: shutil.which(name) for name in ("node", "npm")}
        assert all(self.executables.values()), "H4.3 requires installed Node and npm"
        self.environment = {
            "PATH": os.pathsep.join(dict.fromkeys(str(Path(p).parent) for p in self.executables.values())) + os.pathsep + os.defpath,
            "HOME": str(temporary), "TMPDIR": str(temporary), "LANG": "C.UTF-8", "CI": "true",
            "npm_config_cache": str(cache), "npm_config_userconfig": str(temporary / "user.npmrc"),
            "npm_config_globalconfig": str(temporary / "global.npmrc"), "npm_config_update_notifier": "false",
        }

    def run(self, context, command):
        self.calls.append(command)
        started = time.monotonic()
        result = subprocess.run((self.executables[command.argv[0]], *command.argv[1:]),
                                cwd=context.path(command.cwd),
                                env={**self.environment, **dict(command.environment)},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=command.timeout_seconds, check=False)
        return CommandResult(result.returncode, result.stdout, result.stderr, time.monotonic() - started)


@pytest.fixture
def web(tmp_path):
    root = tmp_path / "web-main"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("node_modules", ".build", "dist", ".local"))
    (root / "docs").mkdir()
    (root / "docs/STATE.md").write_text("Synthetic web state\n")
    (root / "docs/NEXT_STEPS.md").write_text(PLAN)
    # P008-T007: the local composition uses the unified layout and every attempt requires AGENTS.md.
    (root / "AGENTS.md").write_text("# Synthetic web\n\nInstrucciones sintéticas para agentes.\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "synthetic web baseline")
    policy = EnginePolicy(("synthetic-executor",), ("medium",), "synthetic-planner", "medium",
                          "synthetic-reviewer", "high", max_revision_cycles=1)
    context = ProjectContext(root, typescript_web_profile(), policy)
    return context, FixtureCommandRunner(tmp_path / "command-home")


@pytest.fixture
def repository(migrated_database):
    engine = make_engine(migrated_database[0])
    yield SQLiteManagedRepository(engine)
    engine.dispose()


def review():
    return {"task_id": TASK, "verdict": "ACCEPT", "findings": [], "blocking_questions": [], "scope_grants": []}


def edit(mode="correct"):
    def response(context, request):
        path = context.path("src/estimate.ts")
        content = path.read_text()
        if mode in ("correct", "protected", "build-failure"):
            content = content.replace("tasks * 45", "tasks * 30")
        elif mode == "failed-tests":
            content = content.replace("tasks * 45", "tasks * 60")
        elif mode == "type-error":
            content = content.replace("return tasks * 45;", 'return "wrong type";')
        path.write_text(content)
        if mode == "protected":
            context.path("tests/estimate.test.mjs").write_text("// weakened test\n")
        if mode == "build-failure":
            context.path("index.html").unlink()
        return {"result": "synthetic change"}
    return response


def task_checkout(web, tmp_path):
    context, runner = web
    # The healthy fixture is not changed: a regression is introduced in the synthetic checkout.
    path = context.path("src/estimate.ts")
    path.write_text(path.read_text().replace("tasks * 30", "tasks * 45"))
    git(context.root, "add", "src/estimate.ts")
    git(context.root, "commit", "-q", "-m", "synthetic regression")
    info = GitWorktrees().prepare(context.root, tmp_path / "web-task", branch="harness/P001-T001")
    return replace(context, root=info.path), runner


def worker(repository, context, runner, responses):
    agents = ScriptedAgentAdapter(responses)
    workspace = GitWorkspace(IDENTITY)

    def ports(frozen, versions):
        assert frozen == context and versions == VERSIONS
        return agents, runner, workspace

    return LocalSupervisor(repository, ports, commit_factory=lambda *_: workspace), agents, workspace


def test_real_preparation_typecheck_node_tests_and_build_preserve_git(web):
    context, runner = web
    workspace = GitWorkspace(IDENTITY)
    before = workspace.capture(context)
    for command in context.profile.preparation:
        result = run_command(context, runner, command)
        assert result.passed, result.stderr
    report = run_validations(context, {"validation_commands": []}, before, runner)
    assert report.all_passed, report
    assert all(entry.result.duration_seconds > 0 for entry in report.entries)
    assert "pass 3" in report.entries[1].result.stdout
    junit = report.entries[1].reports[0]
    assert junit.status == 'complete' and junit.freshness == 'created'
    assert len(junit.cases) == 3 and all(case.result == 'passed' for case in junit.cases)
    assert all(case.duration_seconds is not None for case in junit.cases)
    assert context.path("dist/main.js").is_file()
    assert 'src="./main.js"' in context.path("dist/index.html").read_text()
    assert json.loads(context.path("node_modules/typescript/package.json").read_text())["version"] == "5.9.3"
    assert workspace.capture(context) == before
    assert git(context.root, "status", "--porcelain") == ""


def test_managed_real_validations_frozen_snapshots_restart_and_exact_commit(web, repository, tmp_path):
    context, runner = task_checkout(web, tmp_path)
    original = git(web[0].root, "rev-parse", "HEAD")
    source_bytes = web[0].path("src/estimate.ts").read_bytes()
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="web-start")
    supervisor, agents, workspace = worker(repository, context, runner, [edit(), review()])
    assert supervisor.run_once().status == "DONE"
    record = repository.get_run(job.run_id)
    assert record.status == "ACCEPTANCE_READY", record.history.stop
    history = record.history
    assert restore_context(history.context_json) == context
    assert load_history(dump_history(history)) == history
    assert json.loads(history.task_json)["allowed_paths"] == ["src/estimate.ts"]
    assert tuple(runner.calls) == context.profile.preparation + context.profile.validations
    assert history.acceptance.evidence == history.cycles[0].validation.evidence == workspace.capture(context)
    assert history.acceptance.evidence.changed_paths == ("src/estimate.ts",)
    for request in agents.requests:
        assert request.context_json == history.context_json and request.task_json == history.task_json
        assert request.prompt_snapshot_json and request.permission_snapshot_json
        assert snapshot_payload(request)["grants"] == snapshot_payload(request)["denials"] == []
    assert "typescript-web" in agents.requests[0].context_json
    preparation = [json.loads(entry) for entry in history.preparation_json]
    assert all(item["result"]["exit_code"] == 0 for item in preparation)
    events = repository.events(job.run_id)
    assert sum(e["kind"] == "command_started" for e in events) == 6
    assert sum(e["kind"] == "command_finished" for e in events) == 6
    # Configuring a different profile afterwards does not rewrite the queued context.
    altered = replace(context, profile=replace(context.profile, executor_instructions="changed later"))
    assert context_snapshot(altered) != history.context_json
    restarted = SQLiteManagedRepository(repository.engine)
    assert restarted.get_run(job.run_id) == record
    restarted.submit_commit(job.run_id, key="web-commit", expected_version=record.version)
    assert supervisor.run_once().status == "DONE"
    committed = restarted.get_run(job.run_id)
    assert committed.status == "COMMITTED"
    assert git(context.root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == "src/estimate.ts"
    assert git(context.root, "status", "--porcelain") == ""
    assert git(web[0].root, "rev-parse", "HEAD") == original
    assert web[0].path("src/estimate.ts").read_bytes() == source_bytes
    assert len(agents.requests) == 2 and supervisor.run_once() is None


@pytest.mark.parametrize("mode", ["failed-tests", "type-error", "build-failure", "protected"])
def test_accept_review_cannot_override_real_tests_typecheck_or_path_policy(web, repository, tmp_path, mode):
    context, runner = task_checkout(web, tmp_path)
    plan = PLAN.replace("`src/estimate.ts`", "`src/estimate.ts`, `index.html`") if mode == "build-failure" else PLAN
    job = repository.submit(context, TASK, PHASE, plan, VERSIONS, key="web-failure")
    supervisor, agents, _ = worker(repository, context, runner, [edit(mode), review()])
    supervisor.run_once()
    record = repository.get_run(job.run_id)
    assert record.status == "STOPPED" and not record.history.acceptance.eligible
    assert record.history.cycles[0].verdict == "ACCEPT"
    if mode == "protected":
        assert "tests/estimate.test.mjs" in record.history.cycles[0].policy.violations
        assert record.history.cycles[0].validation.all_passed
    else:
        assert not record.history.cycles[0].validation.all_passed
        assert any(entry.result.exit_code != 0 for entry in record.history.cycles[0].validation.entries)
    with pytest.raises(Conflict):
        repository.submit_commit(job.run_id, key="bad-commit", expected_version=record.version)
    assert len(agents.requests) == 2 and supervisor.run_once() is None


def test_cache_miss_stops_preparation_without_agents_or_network(web, repository, tmp_path):
    context, _ = web
    runner = FixtureCommandRunner(tmp_path / "empty-home", cache=tmp_path / "empty-cache")
    lock = context.path("package-lock.json").read_bytes()
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="empty-cache")
    supervisor, agents, _ = worker(repository, context, runner, [])
    supervisor.run_once()
    record = repository.get_run(job.run_id)
    assert record.status == "STOPPED" and record.history.stop.stage == "preparation"
    result = json.loads(record.history.preparation_json[-1])["result"]
    assert result["exit_code"] != 0 and "ENOTCACHED" in result["stderr"]
    assert not agents.requests and not record.history.cycles
    assert context.path("package-lock.json").read_bytes() == lock
    assert all("--offline" in c.argv for c in runner.calls if "ci" in c.argv)


# A lock mismatch needs the registry metadata of the package to be reported as EUSAGE; a cache filled only by
# `npm ci` holds tarballs, so npm stops with ENOTCACHED instead. Both refuse before any effect or agent.
@pytest.mark.parametrize("mode,errors", [("lock-mismatch", ("EUSAGE", "ENOTCACHED")),
                                         ("engine-mismatch", ("EBADENGINE",))])
def test_incompatible_lock_or_runtime_stops_preparation(web, repository, mode, errors):
    context, runner = web
    manifest = json.loads(context.path("package.json").read_text())
    if mode == "lock-mismatch":
        manifest["devDependencies"]["typescript"] = "5.8.3"
    else:
        manifest["engines"]["node"] = "0.0.0"
    context.path("package.json").write_text(json.dumps(manifest))
    before = context.path("package.json").read_bytes(), context.path("package-lock.json").read_bytes()
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="incompatible")
    supervisor, agents, _ = worker(repository, context, runner, [])
    supervisor.run_once()
    record = repository.get_run(job.run_id)
    assert record.history.stop.stage == "preparation" and not agents.requests
    assert any(error in json.loads(record.history.preparation_json[-1])["result"]["stderr"] for error in errors)
    assert (context.path("package.json").read_bytes(), context.path("package-lock.json").read_bytes()) == before


def test_changed_content_after_real_validation_cannot_commit(web, repository, tmp_path):
    context, runner = task_checkout(web, tmp_path)
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="changed")
    supervisor, _, _ = worker(repository, context, runner, [edit(), review()])
    supervisor.run_once()
    record = repository.get_run(job.run_id)
    context.path("src/estimate.ts").write_text("// external edit\n")
    repository.submit_commit(job.run_id, key="stale-commit", expected_version=record.version)
    supervisor.run_once()
    assert repository.get_run(job.run_id).status == "STOPPED"
    assert repository.commit_record(job.run_id) is None  # Rejected before manufacturing an intention.
    assert context.path("src/estimate.ts").read_text() == "// external edit\n"


def test_permission_denial_is_preserved_by_the_second_profile(web, repository, tmp_path):
    context, runner = task_checkout(web, tmp_path)
    failure = AgentResult(None, True, 1, error="Synthetic permission stop")
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="permission-stop")
    supervisor, agents, _ = worker(repository, context, runner, [failure])
    supervisor.run_once()
    record = repository.get_run(job.run_id)
    permissions = PermissionRepository(repository)
    row = permissions.create(job.run_id, record.version, kind="tools", target="Bash(npm run test)",
                             operation="use", arguments=[], requested_by="synthetic executor",
                             source_attempt_id=record.history.attempts[0].request.id,
                             reason="Synthetic separate tool request", ttl_seconds=3600)
    permissions.decide(job.run_id, row["id"], repository.get_run(job.run_id).version,
                       expected_request_version=row["version"], fingerprint=row["fingerprint"],
                       decision="deny", scope="once", reason="Synthetic explicit denial")
    repository.resume(job.run_id, key="denied-retry", expected_version=repository.get_run(job.run_id).version,
                      retry_executor=True)
    supervisor.run_once()
    after = repository.get_run(job.run_id)
    assert len(agents.requests) == 1
    assert len(after.history.attempts) == 2 and after.status == "STOPPED"
    request = after.history.attempts[-1].request
    assert snapshot_entries(request) == [] and snapshot_payload(request)["denials"][0]["id"] == row["id"]
    assert permissions.list(job.run_id)[0]["status"] == "DENIED_CONSUMED"
    assert after.history.task_json == record.history.task_json


def test_profile_import_is_declarative_and_core_has_no_new_stack_conditions(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A profile must not launch a process")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert typescript_web_profile().name == 'typescript-web'
    for path in (ROOT / "src/my_harness/core").rglob("*.py"):
        assert not any(word in path.read_text() for word in ("typescript-web", "typescript_web", '"npm"', '"tsc"'))


@pytest.mark.parametrize("command", ["npm install", "npm exec something", "node external.mjs", "sh -c true"])
def test_task_cannot_add_unapproved_command_prefixes(web, command):
    context, runner = web
    # The real validations of the baseline are tested in the full journey.
    context = replace(context, profile=replace(context.profile, validations=()))
    report = run_validations(context, {"validation_commands": [command]}, GitWorkspace(IDENTITY).capture(context), runner)
    assert not report.all_passed and not runner.calls
    assert "outside profile" in report.entries[0].result.error
