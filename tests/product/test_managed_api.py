"""H2 exit, part 1: local managed API with TestClient, temporary Git/SQLite and fakes.

No provider, agent CLI, network or private run. The opt-in
supervisor runs in the service thread just as under Uvicorn.
"""

import os
from pathlib import Path
import subprocess
import sys
import time

from session_client import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.git import GitWorkspace, GitWorktrees
from my_harness.api.app import create_app
from my_harness.i18n import message
from my_harness.core.engine.commit import GitIdentity
from my_harness.core.engine.context import Command, EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.journal import JournalError
from my_harness.core.managed_mode import MARKER_PATH, digest
from my_harness.services.managed_runtime import CONFIG_ENV, ManagedConfig, ManagedProject, load_config
from my_harness.storage.database import make_engine
from my_harness.storage.models import Base

TASK, PHASE = "P001-T001", "P001"
IDENTITY = GitIdentity("My Harness", "harness@example.invalid")
VERSIONS = {"engine": "h2-exit-1", "agent_adapter": "synthetic-1", "commands": "synthetic-1",
            "evidence": "git-1", "provider_cli": None}
PLAN = """# Synthetic managed API plan
## P001-T001 — HTTP task
**Objective:** Change synthetic content.
**Allowed paths:** `app/**`
**Acceptance criteria:**
- Synthetic behavior is present.
**Validation commands:** `test-runner check`
**Executor:** synthetic-executor / medium — Explicit test selection
"""
RUN = {"task_id": TASK, "phase_id": PHASE, "text": PLAN}
STOPPED = "Usuario confirma que el motor legacy no está en ejecución (prueba sintética)"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Fixture Author", "GIT_AUTHOR_EMAIL": "author@example.invalid",
           "GIT_COMMITTER_NAME": "Fixture Author", "GIT_COMMITTER_EMAIL": "author@example.invalid"}
LOCAL = "http://127.0.0.1:8013"


class SyntheticCrash(BaseException):
    pass


def git(cwd, *args) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=GIT_ENV)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def policy():
    return EnginePolicy(("synthetic-executor",), ("medium",), "synthetic-planner", "medium",
                        "synthetic-reviewer", "high", max_revision_cycles=1)


def make_context(root):
    profile = ProjectProfile("synthetic", validations=(Command(("test-runner", "check")),),
                             allowed_command_prefixes=(("test-runner",),))
    return ProjectContext(Path(root), profile, policy())


def review():
    return {"task_id": TASK, "verdict": "ACCEPT", "findings": [], "blocking_questions": [], "scope_grants": []}


def edit(context, request):
    context.path("app/main.txt").write_text("implemented\n", encoding="utf-8")
    return {"result": "synthetic"}


class Ports:
    """Fake ports shared between jobs; records every invocation and every port request."""

    def __init__(self, responses=(), commands=(), git=True):
        self.agents = ScriptedAgentAdapter(list(responses))
        self.runner = ScriptedCommandRunner(list(commands))
        self.git = git
        self.workspace = None
        self.requested = 0

    def _workspace(self, context):
        if self.workspace is None:
            self.workspace = GitWorkspace(IDENTITY) if self.git else SyntheticWorkspace(context, ("app/main.txt",))
        return self.workspace

    def __call__(self, context, versions):
        assert versions == VERSIONS
        self.requested += 1
        return self.agents, self.runner, self._workspace(context)

    def writer(self, context, versions):
        assert versions == VERSIONS
        return self._workspace(context)

    def roles(self):
        return [request.role for request in self.agents.requests]


def config(context, ports=None, *, project="synthetic", commit=True, supervisor=True):
    return ManagedConfig((ManagedProject(project, context, VERSIONS),), ports_factory=ports,
                         commit_factory=ports.writer if ports is not None and commit else None,
                         supervisor=supervisor and ports is not None, poll_seconds=0.02)


def client(url, tmp_path, managed, **kwargs):
    return TestClient(create_app(url, tmp_path / "ui", managed=managed), base_url=LOCAL,
                      headers={"X-My-Harness": "1"}, **kwargs)


def settle(http, run_id, timeout=20.0):
    """Waits until no job of the run is queued or active; the supervisor runs in another thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = http.get(f"/api/managed/runs/{run_id}/jobs?limit=100").json()["items"]
        if jobs and all(job["status"] not in {"QUEUED", "ACTIVE"} for job in jobs):
            return http.get(f"/api/managed/runs/{run_id}").json()
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not settle")


def submit(http, key="start", project="synthetic", body=RUN):
    return http.post(f"/api/managed/projects/{project}/runs", json=body, headers={"Idempotency-Key": key})


def action(http, run_id, name, version, key):
    return http.post(f"/api/managed/runs/{run_id}/actions", json={"action": name, "expected_version": version},
                     headers={"Idempotency-Key": key})


def all_events(http, run_id, limit=4):
    events, cursor = [], 0
    while True:
        page = http.get(f"/api/managed/runs/{run_id}/events", params={"after": cursor, "limit": limit}).json()
        events += page["items"]
        cursor = page["cursor"]
        if not page["has_more"]:
            return events


def table_counts(engine):
    with Session(engine) as session:
        return {table.name: session.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.sorted_tables}


def tree(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(Path(root).rglob("*")) if path.is_file() and not path.is_symlink()}


@pytest.fixture
def engine(migrated_database):
    engine = make_engine(migrated_database[0])
    yield engine
    engine.dispose()


@pytest.fixture
def url(migrated_database, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    return migrated_database[0]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "main-checkout"
    (root / "app").mkdir(parents=True)
    (root / "app/main.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "baseline")
    return root


@pytest.fixture
def task(tmp_path, repo):
    (tmp_path / "worktrees").mkdir()
    info = GitWorktrees().prepare(repo, tmp_path / "worktrees" / "task", branch="harness/P001-T001")
    return make_context(info.path)


@pytest.fixture
def plain(tmp_path):
    root = tmp_path / "plain-checkout"
    (root / "app").mkdir(parents=True)
    (root / "app/main.txt").write_text("baseline\n", encoding="utf-8")
    return make_context(root)




def main_snapshot(root):
    index = Path(git(root, "rev-parse", "--absolute-git-dir")) / "index"
    return {"head": git(root, "rev-parse", "HEAD"), "index": index.read_bytes(), "files": tree(root / "app"),
            "status": git(root, "status", "--porcelain=v1", "-uall")}


# --- full journey ---------------------------------------------------------------------


def test_http_flow_executes_reviews_and_commits_once_across_double_submit_and_restart(
        tmp_path, url, engine, repo, task):
    base = git(task.root, "rev-parse", "HEAD")
    before_main = main_snapshot(repo)
    ports = Ports([edit, review()])
    with client(url, tmp_path, config(task, ports)) as http:
        [listed] = http.get("/api/managed/projects").json()
        # D167: the synthetic `en` confirmation of tests/product/conftest.py, written when the project is installed.
        work = listed.pop("work_language")
        assert (work["work_language"], work["source"], work["format"]) == ("en", "migration", "work-language-1")
        assert [listed] == [{
            "id": "synthetic", "root": str(task.root), "profile": "synthetic", "configuration_state": "ACTIVE",
            "versions": VERSIONS,
            "tag_kind": "lightweight", "documents": None, "bootstrap_enabled": False,
            # D076: declared by the server composition, not registered from the UI.
            "source": "operator", "registry_version": None, "agents": {
                # Injected synthetic ports: no local-config-2 CLI composition, so providers stay undeclared.
                "planning_mode": task.policy.planning_mode,
                "reviewer": {"provider": None, "model": task.policy.reviewer_model,
                             "effort": task.policy.reviewer_effort},
                "planner": {"model": task.policy.planner_model, "effort": task.policy.planner_effort},
                "executor": {"provider": None, "selection_mode": "catalog",
                             "models": list(task.policy.executor_models),
                             "efforts": list(task.policy.executor_efforts), "effort_vocabulary": []}}}]
        assert http.get("/api/managed/supervisor").json() == {
            "read_only_archive": False, "enabled": True, "alive": True, "last_error": None, "ports_configured": True,
            "commit_writer_configured": True, "configuration_mode": None}
        first = submit(http, "start-1")
        assert first.status_code == 202, first.text
        job = first.json()
        assert job["action"] == "start" and job["idempotency_key"] == "start-1"
        run = settle(http, job["run_id"])
        again = submit(http, "start-1")
        assert again.status_code == 202 and again.json()["id"] == job["id"]
        assert run["status"] == "ACCEPTANCE_READY" and run["project_id"] == "synthetic"
        assert run["history"]["acceptance"]["eligible"] is True
        assert run["history"]["acceptance"]["changed_paths"] == ["app/main.txt"]
        assert run["versions"] == VERSIONS and run["locked_by_job"] is None
        cycle = run["history"]["latest_cycle"]
        assert "diff" not in cycle  # D085: the run carries the summary; the content is paginated
        page = http.get(f"/api/managed/runs/{job['run_id']}/cycles/0/diff",
                        params={"sha256": cycle["diff_sha256"]}).json()
        assert page["size_bytes"] == cycle["diff_bytes"] and page["next_offset"] is None
        assert "-baseline" in page["text"] and "+implemented" in page["text"]
        assert cycle["review"] == review()
        assert cycle["provenance"] is not None
        assert cycle["validation"]["evidence"]["fingerprint"] == cycle["fingerprint"]
        assert cycle["validation"]["entries"][0]["result"]["exit_code"] == 0
        attempts = http.get(f"/api/managed/runs/{job['run_id']}/attempts").json()
        assert [(a["number"], a["role"], a["status"], a["fresh_session"]) for a in attempts["items"]] == [
            (1, "executor", "COMPLETED", True), (2, "reviewer", "COMPLETED", True)]

        commit = action(http, job["run_id"], "commit", run["version"], "commit-1")
        assert commit.status_code == 202, commit.text
        final = settle(http, job["run_id"])
        repeat = action(http, job["run_id"], "commit", run["version"], "commit-1")
        assert repeat.status_code == 202 and repeat.json()["id"] == commit.json()["id"]
        assert final["status"] == "COMMITTED" and final["stage"] == "committed"
        assert final["commit"]["status"] == "COMMITTED"
        assert final["commit"]["commit"] == final["commit"]["expected_commit"] == git(task.root, "rev-parse", "HEAD")
        assert git(task.root, "rev-list", "--count", f"{base}..HEAD") == "1"
        jobs = http.get(f"/api/managed/runs/{job['run_id']}/jobs").json()
        assert [j["action"] for j in jobs["items"]] == ["commit", "start"] and jobs["next_offset"] is None
        assert final["active_job"] is None

        events = all_events(http, job["run_id"])
        assert [event["sequence"] for event in events] == list(range(1, final["version"] + 1))
        assert len({event["id"] for event in events}) == len(events)
        kinds = [event["kind"] for event in events]
        assert kinds.count("job_queued") == 2 and kinds.count("commit_recorded") == 1
        assert kinds[-1] == "job_finished"
        page = http.get(f"/api/managed/runs/{job['run_id']}/events", params={"limit": 100}).json()
        assert page["items"] == events and page["cursor"] == final["version"] and not page["has_more"]
    assert ports.roles() == ["executor", "reviewer"]
    assert main_snapshot(repo) == before_main  # the main checkout does not change

    idle = Ports([])
    with client(url, tmp_path, config(task, idle)) as http:
        assert submit(http, "start-1").json()["id"] == job["id"]
        assert action(http, job["run_id"], "commit", run["version"], "commit-1").json()["id"] == commit.json()["id"]
        time.sleep(0.2)  # the restarted supervisor gets a chance to claim something
        assert http.get(f"/api/managed/runs/{job['run_id']}").json() == final
        assert all_events(http, job["run_id"]) == events
    assert idle.requested == 0 and idle.roles() == []
    assert git(task.root, "rev-list", "--count", f"{base}..HEAD") == "1"
    counts = table_counts(engine)
    assert (counts["managed_runs"], counts["managed_jobs"], counts["managed_commits"]) == (1, 2, 1)


def test_queued_job_survives_restart_and_runs_once_when_the_supervisor_is_enabled(tmp_path, url, engine, plain):
    with client(url, tmp_path, config(plain)) as http:
        assert http.get("/api/managed/supervisor").json() == {
            "read_only_archive": False, "enabled": False, "alive": False, "last_error": None, "ports_configured": False,
            "commit_writer_configured": False, "configuration_mode": None}
        job = submit(http, "queued").json()
        assert submit(http, "queued").json() == job
        time.sleep(0.1)
        assert http.get(f"/api/managed/jobs/{job['id']}").json()["status"] == "QUEUED"
    ports = Ports([edit, review()], git=False)
    with client(url, tmp_path, config(plain, ports, commit=False)) as http:
        assert submit(http, "queued").json()["id"] == job["id"]
        run = settle(http, job["run_id"])
    assert run["status"] == "ACCEPTANCE_READY" and ports.roles() == ["executor", "reviewer"]
    counts = table_counts(engine)
    assert (counts["managed_runs"], counts["managed_jobs"]) == (1, 1)


def test_recovery_over_http_requires_explicit_confirmation_and_never_repeats_the_executor(
        tmp_path, url, engine, task):
    # Persistence lost during the reviewer invocation: uncertain result, quarantine.
    ports = Ports([edit, JournalError("Synthetic persistence failure during review"), review()])
    with client(url, tmp_path, config(task, ports)) as http:
        job = submit(http).json()
        quarantined = settle(http, job["run_id"])
        assert quarantined["status"] == "RECOVERY_REQUIRED" and quarantined["locked_by_job"] == job["id"]
        assert "Synthetic persistence failure" in http.get("/api/managed/supervisor").json()["last_error"]
        held = http.get(f"/api/managed/jobs/{job['id']}").json()
        assert held["status"] == "RECOVERY_REQUIRED" and held["owner_token"] and held["owner_closed"]
        counts = table_counts(engine)

        busy = action(http, job["run_id"], "revalidate", quarantined["version"], "too-early")
        assert busy.status_code == 409 and busy.json()["detail"]["code"] == "conflict"
        for token, version in ((held["owner_token"], quarantined["version"] - 1), ("stale", quarantined["version"])):
            refused = http.post(f"/api/managed/jobs/{job['id']}/confirm-stopped", json={
                "owner_token": token, "expected_version": version, "reason": "Sintético"})
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "conflict"
        assert table_counts(engine) == counts

        stopped = http.post(f"/api/managed/jobs/{job['id']}/confirm-stopped", json={
            "owner_token": held["owner_token"], "expected_version": quarantined["version"],
            "reason": "Hilo sintético terminado; ningún proceso queda vivo"})
        assert stopped.status_code == 200, stopped.text
        stopped = stopped.json()
        assert stopped["status"] == "INTERRUPTED" and stopped["locked_by_job"] is None
        duplicate = http.post(f"/api/managed/jobs/{job['id']}/confirm-stopped", json={
            "owner_token": held["owner_token"], "expected_version": quarantined["version"], "reason": "Duplicado"})
        assert duplicate.status_code == 409

        assert action(http, job["run_id"], "revalidate", stopped["version"], "revalidate").status_code == 202
        ready = settle(http, job["run_id"])
        assert ready["status"] == "ACCEPTANCE_READY"
        assert action(http, job["run_id"], "commit", ready["version"], "commit").status_code == 202
        assert settle(http, job["run_id"])["status"] == "COMMITTED"
        attempts = http.get(f"/api/managed/runs/{job['run_id']}/attempts").json()["items"]
        assert [(a["role"], a["status"]) for a in attempts] == [
            ("executor", "COMPLETED"), ("reviewer", "INTERRUPTED"), ("reviewer", "COMPLETED")]
        assert "outcome unknown" in attempts[1]["result"]["error"]
    # Revalidating only validates and reviews: the executor is not repeated and the uncertain reviewer is not resumed.
    assert ports.roles() == ["executor", "reviewer", "reviewer"]
    assert len(ports.runner.calls) == 2


# --- conflicts and validation -----------------------------------------------------------


def test_version_and_idempotency_conflicts_return_409_without_effects(tmp_path, url, engine, plain):
    ports = Ports([edit, review()], git=False)
    with client(url, tmp_path, config(plain, ports, commit=False)) as http:
        job = submit(http, "start").json()
        run = settle(http, job["run_id"])
        counts, before = table_counts(engine), tree(plain.root)
        stale = action(http, job["run_id"], "revalidate", run["version"] - 1, "stale")
        assert stale.status_code == 409 and "reload" in stale.json()["detail"]["diagnostic"]
        reused = action(http, job["run_id"], "revalidate", run["version"], "start")
        assert reused.status_code == 409 and "different action" in reused.json()["detail"]["diagnostic"]
        not_stopped = action(http, job["run_id"], "retry_executor", run["version"], "retry")
        assert not_stopped.status_code == 409 and "stopped run" in not_stopped.json()["detail"]["diagnostic"]
        no_writer = action(http, job["run_id"], "commit", run["version"], "commit")
        assert no_writer.status_code == 409 and no_writer.json()["detail"]["code"] == "commit_writer_unavailable"
        changed = submit(http, "start", body={**RUN, "text": PLAN + "\n"})
        assert changed.status_code == 409
        assert table_counts(engine) == counts and tree(plain.root) == before
        assert http.get(f"/api/managed/runs/{job['run_id']}").json() == run


@pytest.mark.parametrize("request_kwargs", [
    {"json": RUN},  # without Idempotency-Key
    {"json": {**RUN, "model": "real"}, "headers": {"Idempotency-Key": "extra"}},
    {"json": {**RUN, "text": ""}, "headers": {"Idempotency-Key": "empty"}},
    {"json": {**RUN, "task_id": 7}, "headers": {"Idempotency-Key": "type"}},
    {"json": RUN, "headers": {"Idempotency-Key": "x" * 201}},
])
def test_invalid_requests_are_rejected_before_any_row(tmp_path, url, engine, plain, request_kwargs):
    with client(url, tmp_path, config(plain)) as http:
        counts = table_counts(engine)
        response = http.post("/api/managed/projects/synthetic/runs", **request_kwargs)
        assert response.status_code == 422
        assert table_counts(engine) == counts
        bad = http.post("/api/managed/runs/unknown/actions", json={"action": "revalidate", "expected_version": "1"},
                        headers={"Idempotency-Key": "k"})
        assert bad.status_code == 422
        assert submit(http, project="unknown").status_code == 404
        assert http.get("/api/managed/runs/unknown").status_code == 404
        assert http.get("/api/managed/runs/unknown/events").status_code == 404
        assert action(http, "unknown", "revalidate", 0, "k").status_code == 404
        assert table_counts(engine) == counts


def test_runs_of_unregistered_checkouts_are_readable_but_not_actionable(tmp_path, url, engine, plain):
    from my_harness.storage.managed import SQLiteManagedRepository
    other = tmp_path / "unregistered"
    (other / "app").mkdir(parents=True)
    (other / "app/main.txt").write_text("baseline\n", encoding="utf-8")
    job = SQLiteManagedRepository(engine).submit(make_context(other), TASK, PHASE, PLAN, VERSIONS, key="library")
    with client(url, tmp_path, config(plain)) as http:
        run = http.get(f"/api/managed/runs/{job.run_id}").json()
        assert run["project_id"] is None and run["status"] == "QUEUED"
        counts = table_counts(engine)
        refused = action(http, job.run_id, "revalidate", run["version"], "foreign")
        assert refused.status_code == 404
        assert refused.json()["detail"] == {"code": "not_found", "diagnostic": message("api.run_unregistered", "en")}
        confirm = http.post(f"/api/managed/jobs/{job.id}/confirm-stopped", json={
            "owner_token": "none", "expected_version": run["version"], "reason": "Ajeno"})
        assert confirm.status_code == 404
        assert table_counts(engine) == counts


# --- mode and migration -----------------------------------------------------------------


def test_mode_refusals_return_409_with_diagnostic_and_no_partial_effects(tmp_path, url, engine):
    root = tmp_path / "old-checkout"
    (root / ".harness/runs").mkdir(parents=True)
    legacy = make_context(root)
    marked = tmp_path / "marked"
    (marked / ".harness").mkdir(parents=True)
    (marked / MARKER_PATH).write_text("{}", encoding="utf-8")
    projects = (ManagedProject("legacy", legacy, VERSIONS), ManagedProject("marked", make_context(marked), VERSIONS))
    ports = Ports([])
    managed = ManagedConfig(projects, ports_factory=ports, supervisor=True, poll_seconds=0.02)
    with client(url, tmp_path, managed) as http:
        counts, before = table_counts(engine), tree(legacy.root)
        for project, text in (("legacy", "non-activated legacy state"), ("marked", "without a live activation")):
            refused = submit(http, project=project)
            assert refused.status_code == 409
            assert refused.json()["detail"]["code"] == "mode_refused" and text in refused.json()["detail"]["diagnostic"]
        assert table_counts(engine) == counts and tree(legacy.root) == before


def test_host_origin_and_csrf_header_are_enforced_without_effects(tmp_path, url, engine, plain):
    app = create_app(url, tmp_path / "ui", managed=config(plain))
    with TestClient(app, base_url="http://evil.example") as foreign:
        assert foreign.get("/api/managed/projects").status_code == 403
        assert foreign.get("/api/managed/projects").json()["detail"]["code"] == "host_rejected"
        assert foreign.post("/api/managed/projects/synthetic/runs", json=RUN, headers={
            "Idempotency-Key": "k", "X-My-Harness": "1"}).status_code == 403
    with TestClient(app, base_url="http://127.0.0.1.evil.example") as lookalike:
        assert lookalike.get("/api/managed/projects").status_code == 403
    with TestClient(app, base_url=LOCAL) as http:
        counts = table_counts(engine)
        missing = http.post("/api/managed/projects/synthetic/runs", json=RUN, headers={"Idempotency-Key": "k"})
        assert missing.status_code == 403 and missing.json()["detail"]["code"] == "csrf_header_required"
        for origin in ("http://evil.example", "null", "file:///tmp/page.html"):
            cross = http.post("/api/managed/projects/synthetic/runs", json=RUN, headers={
                "Idempotency-Key": "k", "X-My-Harness": "1", "Origin": origin})
            assert cross.status_code == 403 and cross.json()["detail"]["code"] == "origin_rejected"
        assert table_counts(engine) == counts
        assert http.get("/api/managed/projects").status_code == 200  # reads without their own header
        local = http.post("/api/managed/projects/synthetic/runs", json=RUN, headers={
            "Idempotency-Key": "k", "X-My-Harness": "1", "Origin": LOCAL})
        assert local.status_code == 202


def test_default_service_registers_nothing_and_never_launches_processes(tmp_path, url, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No process may be launched by the default service")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with TestClient(create_app(url, tmp_path / "ui"), base_url=LOCAL, headers={"X-My-Harness": "1"}) as http:
        assert http.get("/api/managed/projects").json() == []
        assert http.get("/api/managed/supervisor").json() == {
            "read_only_archive": False, "enabled": False, "alive": False, "last_error": None, "ports_configured": False,
            "commit_writer_configured": False, "configuration_mode": None}
        assert submit(http).status_code == 404
        assert http.get("/api/legacy/projects").status_code == 404


def test_configuration_is_validated_at_startup(tmp_path, url, plain):
    inside = make_context(Path(url.removeprefix("sqlite:///")).parent)
    for managed, message in (
            (ManagedConfig((ManagedProject("db", inside, VERSIONS),)), "outside the checkout"),
            (ManagedConfig((ManagedProject("a", plain, VERSIONS), ManagedProject("a", plain, VERSIONS))), "Duplicate project"),
            (ManagedConfig((ManagedProject("Bad/Id", plain, VERSIONS),)), "Invalid project identifier"),
            (ManagedConfig((ManagedProject("p", plain, {"engine": "x"}),)), "Incomplete explicit versions"),
            (ManagedConfig(supervisor=True), "ports_factory")):
        with pytest.raises(ValueError, match=message):
            with TestClient(create_app(url, tmp_path / "ui", managed=managed)):
                pass


def test_configuration_is_loaded_explicitly_from_the_environment(tmp_path, monkeypatch, plain):
    module = tmp_path / "synthetic_managed_config.py"
    module.write_text(
        "from pathlib import Path\n"
        "from my_harness.services.managed_runtime import ManagedConfig, ManagedProject\n"
        "from my_harness.core.engine.context import EnginePolicy, ProjectContext, ProjectProfile\n"
        f"ROOT = Path({str(plain.root)!r})\n"
        "def build():\n"
        "    policy = EnginePolicy(('e',), ('m',), 'p', 'm', 'r', 'h')\n"
        "    return ManagedConfig((ManagedProject('env', ProjectContext(ROOT, ProjectProfile('x'), policy),\n"
        "        {'engine': 'x', 'agent_adapter': None, 'commands': None, 'evidence': None}),))\n",
        encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert load_config() == ManagedConfig()
    monkeypatch.setenv(CONFIG_ENV, "synthetic_managed_config:build")
    assert [project.id for project in load_config().projects] == ["env"]
    for spec in ("synthetic_managed_config", "synthetic_managed_config:ROOT"):
        with pytest.raises((ValueError, TypeError)):
            load_config(spec)
    sys.modules.pop("synthetic_managed_config", None)


def demo_module():
    import runpy
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "examples/managed_demo.py"))


def test_ui_demo_preparation_is_explicit_and_never_replaces_existing_data(tmp_path, monkeypatch):
    demo = demo_module()
    area = demo["prepare"](tmp_path / "demo")
    before = tree(area / "source")
    with pytest.raises(FileExistsError):
        demo["prepare"](area)
    monkeypatch.setenv("HARNESS_DEMO_ROOT", str(area))
    configured = demo["build"]()
    assert [p.id for p in configured.projects] == ["task", "recovery"]
    assert tree(area / "source") == before
    assert not (area / "calls.jsonl").exists()  # loading alone never invokes anything
    (area / "demo-marker").write_text("not a prepared fixture")
    with pytest.raises(ValueError, match="Not a prepared"):
        demo["build"]()


def test_ui_demo_recovers_after_service_restart_without_repeating_executor(tmp_path, url, monkeypatch):
    import json
    demo = demo_module()
    area = demo["prepare"](tmp_path / "demo")
    monkeypatch.setenv("HARNESS_DEMO_ROOT", str(area))
    with client(url, tmp_path, demo["build"]()) as http:
        job = submit(http, project="recovery", body={**RUN, "text": demo["PLAN"]}).json()
        stopped = settle(http, job["run_id"])
        assert stopped["status"] == "RECOVERY_REQUIRED"
    with client(url, tmp_path, demo["build"]()) as http:
        held = http.get(f"/api/managed/jobs/{job['id']}").json()
        confirmation = http.post(f"/api/managed/jobs/{job['id']}/confirm-stopped", json={
            "owner_token": held["owner_token"], "expected_version": stopped["version"],
            "reason": "Synthetic failure returned; closed owner and no process"})
        assert confirmation.status_code == 200
        resumed = action(http, job["run_id"], "revalidate", confirmation.json()["version"], "demo-revalidate")
        assert resumed.status_code == 202
        ready = settle(http, job["run_id"])
        assert ready["status"] == "ACCEPTANCE_READY"
        assert action(http, job["run_id"], "commit", ready["version"], "demo-commit").status_code == 202
        assert settle(http, job["run_id"])["status"] == "COMMITTED"
    calls = [json.loads(line) for line in (area / "calls.jsonl").read_text().splitlines()]
    assert [item["role"] for item in calls] == ["executor", "reviewer", "reviewer"]
    assert git(area / "recovery", "rev-list", "--count", "HEAD") == "2"
    assert git(area / "source", "status", "--porcelain") == ""


def test_ordinary_service_without_supervisor_is_not_an_archive(tmp_path, url):
    managed = ManagedConfig(ports_factory=lambda *_: pytest.fail('No invocation'), supervisor=False)
    with client(url, tmp_path, managed) as http:
        status = http.get('/api/managed/supervisor').json()
        assert status['read_only_archive'] is False
        assert status['enabled'] is False
        assert status['ports_configured'] is True
