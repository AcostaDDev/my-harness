"""H2.4: real Git in temporary repositories, SQLite and fake agents.

No provider or agent CLI. The `reference-transaction` hook installed in the
repositories is used to check that hooks are never executed.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import subprocess

from alembic import command
import pytest
from sqlalchemy import inspect

from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.git import EvidenceCaptureError, Git, GitError, GitWorkspace, GitWorktrees
from my_harness.core.engine.commit import CommitUncertain, GitIdentity, MechanicalUpdate, git_provenance
from my_harness.core.engine.context import Command, EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, SQLiteManagedRepository

TASK, PHASE = "P001-T001", "P001"
IDENTITY = GitIdentity("My Harness", "harness@example.invalid")
VERSIONS = {"engine": "h2.4", "agent_adapter": "synthetic-1", "commands": "synthetic-1",
            "evidence": "git-1", "provider_cli": None}
PLAN = """# Synthetic H2.4 plan
## P001-T001 — Git task
**Objective:** Change synthetic content.
**Allowed paths:** `app/**`
**Acceptance criteria:**
- Synthetic behavior is present.
**Validation commands:** `test-runner check`
**Executor:** synthetic-executor / medium — Explicit test selection
"""
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Fixture Author", "GIT_AUTHOR_EMAIL": "author@example.invalid",
           "GIT_COMMITTER_NAME": "Fixture Author", "GIT_COMMITTER_EMAIL": "author@example.invalid"}


class SyntheticCrash(BaseException):
    pass


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def git(cwd, *args, input=None, check=True) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, input=input,
                            env=GIT_ENV, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def write(root, relative, text):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "main-checkout"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for name, text in {"app/main.txt": "baseline\n", "app/keep.txt": "keep\n", "app/tool.sh": "#!/bin/sh\n",
                       "docs/STATE.md": "state\n", ".gitignore": "ignored/\n"}.items():
        write(root, name, text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "baseline")
    marker = tmp_path / "hook-ran"
    hook = root / ".git/hooks/reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return root


def make_context(root, **policy):
    profile = ProjectProfile("synthetic", validations=(Command(("test-runner", "check")),),
                             allowed_command_prefixes=(("test-runner",),), sensitive_paths=(".env*",))
    return ProjectContext(root, profile, EnginePolicy(
        ("synthetic-executor",), ("medium",), "synthetic-planner", "medium", "synthetic-reviewer", "high",
        max_revision_cycles=1, **policy))


@pytest.fixture
def repository(migrated_database):
    engine = make_engine(migrated_database[0])
    repo = SQLiteManagedRepository(engine, clock=Clock())
    yield repo
    engine.dispose()


@pytest.fixture
def task(tmp_path, repo):
    (tmp_path / "worktrees").mkdir()
    info = GitWorktrees().prepare(repo, tmp_path / "worktrees" / "task", branch="harness/P001-T001")
    return make_context(info.path), info


def review(verdict="ACCEPT"):
    return {"task_id": TASK, "verdict": verdict, "findings": [], "blocking_questions": [], "scope_grants": []}


def edit(context_files=None):
    files = context_files or {"app/main.txt": "implemented\n"}

    def call(context, request):
        for name, text in files.items():
            write(context.root, name, text)
        return {"result": "synthetic"}
    return call


def supervisor(repository, context, responses, *, workspace=None, **kwargs):
    agents = ScriptedAgentAdapter(responses)
    runner = ScriptedCommandRunner()
    workspace = workspace or GitWorkspace(IDENTITY)

    def factory(frozen, versions):
        assert frozen == context
        return agents, runner, workspace

    return LocalSupervisor(repository, factory, commit_factory=lambda frozen, versions: workspace,
                           **kwargs), agents


def accept(repository, context, files=None, *, key="start", workspace=None):
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key=key)
    worker, agents = supervisor(repository, context, [edit(files), review()], workspace=workspace)
    assert worker.run_once().status == "DONE"
    record = repository.get_run(job.run_id)
    assert record.history.status == "acceptance_ready", record.history.stop
    return job, record


def run_commit(repository, job, key="commit", mechanical=(), context=None, **kwargs):
    record = repository.get_run(job.run_id)
    context = context or load_context(record)
    queued = repository.submit_commit(job.run_id, key=key, expected_version=record.version, mechanical=mechanical)
    worker, _ = supervisor(repository, context, [], **kwargs)
    return queued, worker


def load_context(record):
    from my_harness.core.engine.serialization import restore_context
    return restore_context(record.history.context_json)


def commits_after(root, base):
    return git(root, "rev-list", "--count", f"{base}..HEAD")


def snapshot(root):
    """Observable state of the main checkout: HEAD, index, content and status."""
    index = Path(git(root, "rev-parse", "--absolute-git-dir")) / "index"
    files = {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
             if p.is_file() and ".git" not in p.relative_to(root).parts}
    return {"head": git(root, "rev-parse", "HEAD"), "index": index.read_bytes(), "files": files,
            "status": git(root, "status", "--porcelain=v1", "-uall")}


# --- capture --------------------------------------------------------------------

def test_capture_covers_staged_unstaged_untracked_deleted_and_modes_without_side_effects(task):
    context, info = task
    root = context.root
    write(root, "app/main.txt", "unstaged\n")
    write(root, "app/staged.txt", "staged\n")
    git(root, "add", "app/staged.txt")
    write(root, "app/new.txt", "untracked\n")
    write(root, "ignored/secret.txt", "ignored\n")
    (root / "app/keep.txt").unlink()
    (root / "app/tool.sh").chmod(0o755)
    before = snapshot(root)

    workspace = GitWorkspace(IDENTITY)
    evidence = workspace.capture(context)

    assert evidence.base_revision == info.base_revision
    assert evidence.changed_paths == ("app/keep.txt", "app/main.txt", "app/new.txt", "app/staged.txt", "app/tool.sh")
    provenance = json.loads(evidence.provenance_json)
    assert provenance["staged_paths"] == ["app/staged.txt"]
    assert provenance["untracked_paths"] == ["app/new.txt"]
    assert provenance["deleted_paths"] == ["app/keep.txt"]
    for expected in ("+unstaged", "+staged", "+untracked", "deleted file mode", "new file mode", "new mode 100755"):
        assert expected in evidence.diff
    assert "secret" not in evidence.diff
    assert provenance["worktree_tree"] != provenance["index_tree"]
    assert git_provenance(evidence).worktree_tree == provenance["worktree_tree"]
    # Deterministic and without effects on HEAD, the real index, files or status.
    assert workspace.capture(context) == evidence
    assert snapshot(root) == before
    assert not (context.root.parent.parent / "hook-ran").exists()


@pytest.mark.parametrize("mutation", ["content", "untracked", "delete", "mode", "unstage"])
def test_any_change_to_reviewed_state_changes_the_fingerprint(task, mutation):
    context, _ = task
    root = context.root
    write(root, "app/main.txt", "reviewed\n")
    git(root, "add", "app/main.txt")
    workspace = GitWorkspace(IDENTITY)
    reviewed = workspace.capture(context)
    if mutation == "content":
        write(root, "app/main.txt", "other\n")
    elif mutation == "untracked":
        write(root, "app/extra.txt", "x\n")
    elif mutation == "delete":
        (root / "app/keep.txt").unlink()
    elif mutation == "mode":
        (root / "app/tool.sh").chmod(0o755)
    else:
        git(root, "reset", "-q", "app/main.txt")
    assert workspace.capture(context).fingerprint != reviewed.fingerprint


def test_capture_fails_safe_for_unsupported_states(tmp_path, repo, task):
    context, _ = task
    workspace = GitWorkspace(IDENTITY)
    with pytest.raises(EvidenceCaptureError, match="top level"):
        workspace.capture(make_context(repo / "app"))
    tiny = GitWorkspace(IDENTITY, max_diff_bytes=64)
    write(context.root, "app/big.txt", "x" * 500)
    with pytest.raises(EvidenceCaptureError, match="not truncated"):
        tiny.capture(context)
    (context.root / "app/big.txt").unlink()
    nested = context.root / "vendor/lib"
    nested.mkdir(parents=True)
    git(nested, "init", "-q")
    write(nested, "a.txt", "a")
    git(nested, "add", "-A")
    git(nested, "commit", "-q", "-m", "nested")
    with pytest.raises(EvidenceCaptureError, match="gitlink"):
        workspace.capture(context)
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    git(unborn, "init", "-q")
    with pytest.raises(EvidenceCaptureError):
        workspace.capture(make_context(unborn))


def test_unreachable_directory_is_a_launch_error_not_a_git_answer(tmp_path, repo):
    # D125: `-C` replaces cwd; a missing directory cannot turn into a boolean code.
    missing = Git(tmp_path / "missing")
    with pytest.raises(GitError, match="could not run"):
        missing.code("cat-file", "-e", "HEAD")
    with pytest.raises(GitError, match="could not run"):
        missing.run("rev-parse", "HEAD")
    assert Git(repo).code("cat-file", "-e", "HEAD") == 0
    assert Git(repo).code("cat-file", "-e", "0" * 40) == 1


def test_conflicted_index_is_never_resolved_implicitly(task):
    context, _ = task
    root = context.root
    git(root, "checkout", "-q", "-b", "side")
    write(root, "app/main.txt", "side\n")
    git(root, "commit", "-qam", "side")
    git(root, "checkout", "-q", "harness/P001-T001")
    write(root, "app/main.txt", "task\n")
    git(root, "commit", "-qam", "task")
    git(root, "merge", "side", check=False)
    assert "UU" in git(root, "status", "--porcelain")
    with pytest.raises(EvidenceCaptureError):
        GitWorkspace(IDENTITY).capture(context)


# --- worktrees ----------------------------------------------------------------------

def test_worktree_is_isolated_idempotent_and_preserves_main_checkout(tmp_path, repo):
    write(repo, "app/main.txt", "foreign unstaged\n")
    write(repo, "app/foreign.txt", "foreign staged\n")
    git(repo, "add", "app/foreign.txt")
    write(repo, "app/untracked.txt", "foreign untracked\n")
    before = snapshot(repo)
    worktrees = GitWorktrees()
    (tmp_path / "worktrees").mkdir()
    destination = tmp_path / "worktrees" / "task"
    first = worktrees.prepare(repo, destination, branch="harness/P001-T001")
    assert first.created and first.head == first.base_revision == before["head"]
    assert "harness/P001-T001" in git(repo, "branch", "--list")
    assert snapshot(repo) == before  # no stash/clean/reset/checkout
    assert git(first.path, "status", "--porcelain") == ""
    assert (first.path / "app/main.txt").read_text() == "baseline\n"
    write(first.path, "app/main.txt", "task work in progress\n")
    second = worktrees.prepare(repo, destination, branch="harness/P001-T001")
    assert not second.created and second.path == first.path
    assert (second.path / "app/main.txt").read_text() == "task work in progress\n"  # does not clean
    assert snapshot(repo) == before


def test_worktree_refuses_to_overwrite_or_reuse_silently(tmp_path, repo):
    worktrees = GitWorktrees()
    ok = tmp_path / "worktrees"
    ok.mkdir()
    with pytest.raises(GitError, match="outside"):
        worktrees.prepare(repo, repo / "inside", branch="harness/x")
    with pytest.raises(GitError, match="absolute"):
        worktrees.prepare(repo, Path("relative"), branch="harness/x")
    with pytest.raises(GitError):
        worktrees.prepare(repo, ok / "a", branch="bad..name")
    (ok / "occupied").mkdir()
    write(ok / "occupied", "file", "mine")
    with pytest.raises(GitError, match="exists"):
        worktrees.prepare(repo, ok / "occupied", branch="harness/y")
    assert (ok / "occupied/file").read_text() == "mine"
    git(repo, "branch", "harness/taken")
    with pytest.raises(GitError, match="already exists"):
        worktrees.prepare(repo, ok / "b", branch="harness/taken")
    worktrees.prepare(repo, ok / "c", branch="harness/c")
    with pytest.raises(GitError, match="different branch"):
        worktrees.prepare(repo, ok / "c", branch="harness/other")


# --- acceptance and commit ------------------------------------------------------------

def test_accepted_task_creates_exactly_the_reviewed_commit(tmp_path, repo, task, repository):
    context, info = task
    before_main = snapshot(repo)
    write(context.root, "ignored/ignored.txt", "never reviewed\n")
    job, record = accept(repository, context, {"app/main.txt": "implemented\n", "app/new.txt": "new\n"})
    evidence = record.history.acceptance.evidence
    assert evidence.provenance_json and evidence.changed_paths == ("app/main.txt", "app/new.txt")
    assert git(context.root, "rev-parse", "HEAD") == info.base_revision  # accepting is not committing
    assert repository.commit_record(job.run_id) is None

    _, worker = run_commit(repository, job)
    assert worker.run_once().status == "DONE"

    head = git(context.root, "rev-parse", "HEAD")
    record = repository.get_run(job.run_id)
    commit = repository.commit_record(job.run_id)
    assert record.status == "COMMITTED" and commit.status == "COMMITTED" and commit.commit == head
    assert git(context.root, "rev-parse", "HEAD^") == info.base_revision
    assert commits_after(context.root, info.base_revision) == "1"
    assert git(context.root, "rev-parse", "HEAD^{tree}") == git_provenance(evidence).worktree_tree
    assert git(context.root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split() == [
        "app/main.txt", "app/new.txt"]
    message = git(context.root, "log", "-1", "--format=%B")
    assert f"Harness-Operation: {commit.intent.operation_id}" in message
    assert f"Harness-Run: {job.run_id}" in message
    assert f"Harness-Reviewed-Fingerprint: {evidence.fingerprint}" in message
    assert git(context.root, "log", "-1", "--format=%an <%ae>|%cn <%ce>") == (
        "My Harness <harness@example.invalid>|My Harness <harness@example.invalid>")
    # Index refreshed, unreviewed content kept, nothing done outside the worktree.
    assert git(context.root, "status", "--porcelain") == ""
    assert (context.root / "ignored/ignored.txt").read_text() == "never reviewed\n"
    assert snapshot(repo) == before_main
    assert not (tmp_path / "hook-ran").exists()
    kinds = [event["kind"] for event in repository.events(job.run_id)]
    assert kinds.count("commit_intent") == kinds.count("commit_recorded") == 1
    last_finish = len(kinds) - 1 - kinds[::-1].index("job_finished")
    assert kinds.index("commit_intent") < kinds.index("commit_recorded") < last_finish
    # No retry and no second operation.
    with pytest.raises(Conflict, match="recorded commit"):
        repository.submit_commit(job.run_id, key="again", expected_version=record.version)


def test_committed_run_cannot_be_resumed_and_idempotent_key_returns_same_job(task, repository):
    context, _ = task
    job, _ = accept(repository, context)
    queued, worker = run_commit(repository, job)
    version = repository.get_run(job.run_id).version
    again = repository.submit_commit(job.run_id, key="commit", expected_version=version - 1)
    assert again.id == queued.id
    worker.run_once()
    final = repository.get_run(job.run_id)
    with pytest.raises(Conflict, match="commit"):
        repository.resume(job.run_id, key="revalidate", expected_version=final.version)


def test_staged_untracked_and_deleted_content_is_committed_but_ignored_is_not(task, repository):
    context, info = task
    root = context.root

    def work(ctx, request):
        write(ctx.root, "app/staged.txt", "staged\n")
        git(ctx.root, "add", "app/staged.txt")
        write(ctx.root, "app/untracked.txt", "untracked\n")
        write(ctx.root, "ignored/skip.txt", "ignored\n")
        (ctx.root / "app/keep.txt").unlink()
        (ctx.root / "app/tool.sh").chmod(0o755)
        return {"result": "synthetic"}

    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="start")
    worker, _ = supervisor(repository, context, [work, review()])
    worker.run_once()
    _, committer = run_commit(repository, job)
    committer.run_once()
    changes = dict(line.split("\t")[::-1] for line in git(root, "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD").splitlines())
    assert changes == {"app/staged.txt": "A", "app/untracked.txt": "A", "app/keep.txt": "D", "app/tool.sh": "M"}
    assert "ignored/skip.txt" not in git(root, "ls-tree", "-r", "--name-only", "HEAD")
    assert git(root, "ls-tree", "HEAD", "app/tool.sh").startswith("100755")
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("mutation", ["content", "untracked", "delete", "stage"])
def test_external_modification_after_review_invalidates_acceptance(task, repository, mutation):
    context, info = task
    root = context.root
    job, record = accept(repository, context)
    reviewed = record.history.acceptance.evidence
    if mutation == "content":
        write(root, "app/main.txt", "changed after review\n")
    elif mutation == "untracked":
        write(root, "app/surprise.txt", "late\n")
    elif mutation == "delete":
        (root / "app/keep.txt").unlink()
    else:
        git(root, "add", "app/main.txt")  # same content, different staged state
    _, worker = run_commit(repository, job)
    assert worker.run_once().status == "DONE"
    run = repository.get_run(job.run_id)
    assert run.status == "STOPPED" and run.history.stop.stage == "commit"
    assert reviewed.fingerprint in run.history.stop.reason
    assert repository.commit_record(job.run_id) is None
    assert git(root, "rev-parse", "HEAD") == info.base_revision
    assert any(e["kind"] == "commit_invalidated" for e in repository.events(job.run_id))
    # Revalidating produces new evidence; the commit contains what was reviewed again.
    repository.resume(job.run_id, key="revalidate", expected_version=run.version)
    revalidate, _ = supervisor(repository, context, [review()])
    revalidate.run_once()
    again = repository.get_run(job.run_id)
    assert again.history.status == "acceptance_ready"
    assert again.history.acceptance.evidence.fingerprint != reviewed.fingerprint
    _, committer = run_commit(repository, job, key="commit-2")
    committer.run_once()
    assert git(root, "rev-parse", "HEAD^{tree}") == git_provenance(again.history.acceptance.evidence).worktree_tree
    assert git(root, "status", "--porcelain") == ""


def test_base_moved_after_review_invalidates_even_with_identical_tree(task, repository):
    context, info = task
    job, _ = accept(repository, context)
    git(context.root, "commit", "-q", "--allow-empty", "-m", "someone else")
    moved = git(context.root, "rev-parse", "HEAD")
    _, worker = run_commit(repository, job)
    worker.run_once()
    assert repository.get_run(job.run_id).status == "STOPPED"
    assert git(context.root, "rev-parse", "HEAD") == moved and repository.commit_record(job.run_id) is None


def test_synthetic_evidence_cannot_be_committed(tmp_path, repo, repository, migrated_database):
    context = make_context(repo)
    job = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key="synthetic")
    agents = ScriptedAgentAdapter([edit(), review()])
    worker = LocalSupervisor(repository, lambda c, v: (agents, ScriptedCommandRunner(),
                                                      SyntheticWorkspace(c, ("app/main.txt",))))
    worker.run_once()
    record = repository.get_run(job.run_id)
    assert record.history.status == "acceptance_ready"
    assert record.history.acceptance.evidence.provenance_json is None
    with pytest.raises(Conflict, match="Git provenance"):
        repository.submit_commit(job.run_id, key="commit", expected_version=record.version)


def test_unreviewed_changes_in_main_checkout_survive_the_whole_flow(tmp_path, repo, task, repository):
    write(repo, "app/main.txt", "owner's unstaged work\n")
    write(repo, "app/owner.txt", "owner's untracked\n")
    before = snapshot(repo)
    context, _ = task
    job, _ = accept(repository, context)
    _, worker = run_commit(repository, job)
    worker.run_once()
    assert repository.get_run(job.run_id).status == "COMMITTED"
    assert snapshot(repo) == before
    assert (context.root / "app/main.txt").read_text() == "implemented\n"


# --- mechanics ----------------------------------------------------------------------------

def test_mechanical_updates_join_the_commit_explicitly(task, repository):
    context, info = task
    job, record = accept(repository, context)
    update = MechanicalUpdate("docs/STATE.md", "state\naccepted P001-T001\n", "Record accepted task")
    _, worker = run_commit(repository, job, mechanical=(update,))
    worker.run_once()
    commit = repository.commit_record(job.run_id)
    assert commit.status == "COMMITTED"
    assert git(context.root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split() == [
        "app/main.txt", "docs/STATE.md"]
    assert git(context.root, "show", "HEAD:docs/STATE.md") == "state\naccepted P001-T001\n".strip()
    assert (context.root / "docs/STATE.md").read_text() == "state\naccepted P001-T001\n"
    assert "Harness-Mechanical: docs/STATE.md" in git(context.root, "log", "-1", "--format=%B")
    assert commit.intent.mechanical == (update,)
    assert git(context.root, "status", "--porcelain") == ""
    assert git_provenance(record.history.acceptance.evidence).worktree_tree != commit.intent.expected_tree


def test_mechanical_updates_are_validated_before_any_effect(task, repository):
    context, info = task
    job, record = accept(repository, context)
    version = record.version
    for update in (MechanicalUpdate("app/main.txt", "overlap\n", "Overlaps reviewed content"),
                   MechanicalUpdate(".env.local", "SECRET=1\n", "Sensitive")):
        with pytest.raises(Conflict):
            repository.submit_commit(job.run_id, key="bad", expected_version=version, mechanical=(update,))
    with pytest.raises(Conflict, match="Duplicate"):
        repository.submit_commit(job.run_id, key="dup", expected_version=version, mechanical=(
            MechanicalUpdate("docs/a.md", "a", "x"), MechanicalUpdate("docs/a.md", "b", "y")))
    with pytest.raises(ValueError):
        MechanicalUpdate("../escape", "x", "Escapes")
    with pytest.raises(ValueError):
        MechanicalUpdate(".git/config", "x", "Git metadata")
    with pytest.raises(ValueError):
        MechanicalUpdate("docs/a.md", "x", " ")
    assert git(context.root, "rev-parse", "HEAD") == info.base_revision
    assert repository.get_run(job.run_id).version == version


# --- crashes ----------------------------------------------------------------------------------

def crash_on(monkeypatch, predicate, *, after=False):
    original = Git.run

    def run(self, *args, **kwargs):
        if not after and predicate(args):
            raise SyntheticCrash()
        result = original(self, *args, **kwargs)
        if after and predicate(args):
            raise SyntheticCrash()
        return result

    monkeypatch.setattr(Git, "run", run)
    return lambda: monkeypatch.setattr(Git, "run", original)


def written_commit(args):
    return args[:2] == ("hash-object", "-t") and "-w" in args


def ref_update(args):
    return args[:1] == ("update-ref",)


def recover(repository, job, crashed_job):
    """Expired lease → explicit confirmation → new commit job (reconciliation)."""
    repository.clock.now += timedelta(seconds=31)
    assert repository.recover_expired() == [crashed_job.id]
    quarantined = repository.get_run(job.run_id)
    owner = repository.get_job(crashed_job.id).owner_token
    repository.confirm_stopped(crashed_job.id, owner_token=owner, expected_version=quarantined.version,
                               reason="Synthetic supervisor ended; no Git process remains")


@pytest.mark.parametrize("point,after", [("before-object", False), ("before-ref", False), ("after-ref", True)])
def test_crash_around_the_git_effect_recovers_without_duplicate_commit(task, repository, monkeypatch, point, after):
    context, info = task
    job, record = accept(repository, context)
    predicate = written_commit if point == "before-object" else ref_update
    restore = crash_on(monkeypatch, predicate, after=after)
    queued, worker = run_commit(repository, job)
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    restore()
    intent = repository.commit_record(job.run_id)
    assert intent.status == "INTENT" and intent.outcome is None  # durable intention, no result
    head = git(context.root, "rev-parse", "HEAD")
    assert (head == intent.intent.expected_commit) is after and (head == info.base_revision) is not after
    assert commits_after(context.root, info.base_revision) == ("1" if after else "0")
    object_exists = subprocess.run(["git", "-C", str(context.root), "cat-file", "-e", intent.intent.expected_commit],
                                   env=GIT_ENV).returncode == 0
    assert object_exists is (point != "before-object")
    # Restart: reconciliation needs neither another review nor rebuilding the intention.
    recover(repository, job, queued)
    assert repository.get_run(job.run_id).status == "INTERRUPTED"
    _, fresh = run_commit(repository, job, key="reconcile")
    assert fresh.run_once().status == "DONE"
    record = repository.commit_record(job.run_id)
    assert record.status == "COMMITTED" and record.commit == intent.intent.expected_commit
    assert record.intent.operation_id == intent.intent.operation_id
    assert record.outcome.status == ("reconciled" if after else "committed")
    assert commits_after(context.root, info.base_revision) == "1"
    assert git(context.root, "rev-parse", "HEAD") == intent.intent.expected_commit
    assert git(context.root, "status", "--porcelain") == ""
    assert [e["kind"] for e in repository.events(job.run_id)].count("commit_intent") == 1
    assert repository.get_run(job.run_id).status == "COMMITTED"
    assert not (context.root.parent.parent / "hook-ran").exists()


def test_crash_after_the_recorded_commit_recovers_as_committed_without_another_commit(task, repository, monkeypatch):
    """P011-T013: RECOVERY_REQUIRED → COMMITTED in flows/task-run.md; the recorded commit decides the run status."""
    context, info = task
    job, _ = accept(repository, context)
    queued, worker = run_commit(repository, job)

    def finish(*args, **kwargs):
        raise SyntheticCrash()

    monkeypatch.setattr(repository, "finish", finish)
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    monkeypatch.undo()
    record = repository.commit_record(job.run_id)
    assert record.status == "COMMITTED" and repository.get_job(queued.id).status == "ACTIVE"
    recover(repository, job, queued)
    run = repository.get_run(job.run_id)
    assert run.status == "COMMITTED" and repository.get_job(queued.id).status == "INTERRUPTED"
    assert commits_after(context.root, info.base_revision) == "1"
    with pytest.raises(Conflict):
        repository.submit_commit(job.run_id, key="again", expected_version=run.version, mechanical=())
    with pytest.raises(Conflict):
        repository.resume(job.run_id, key="revalidate", expected_version=run.version)


def test_reconciliation_does_not_rewrite_history_after_later_commits_or_edits(task, repository, monkeypatch):
    context, info = task
    job, _ = accept(repository, context)
    crash_on(monkeypatch, ref_update, after=True)
    queued, worker = run_commit(repository, job)
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    monkeypatch.undo()
    intent = repository.commit_record(job.run_id).intent
    # The user keeps working on top of the commit already created before reconciliation.
    write(context.root, "app/main.txt", "user continued\n")
    git(context.root, "commit", "-qam", "user follow-up")
    write(context.root, "app/main.txt", "and again\n")
    follow_up = git(context.root, "rev-parse", "HEAD")
    recover(repository, job, queued)
    _, fresh = run_commit(repository, job, key="reconcile")
    fresh.run_once()
    record = repository.commit_record(job.run_id)
    assert record.status == "COMMITTED" and record.outcome.status == "reconciled"
    assert record.commit == intent.expected_commit
    assert git(context.root, "rev-parse", "HEAD") == follow_up  # history intact
    assert (context.root / "app/main.txt").read_text() == "and again\n"  # edit kept
    assert record.outcome.index == "left_untouched" or record.outcome.index == "already_current"


def test_content_changed_between_intent_and_effect_never_commits(task, repository, monkeypatch):
    context, info = task
    job, _ = accept(repository, context)
    original = GitWorkspace.execute

    def execute(self, ctx, intent):
        write(ctx.root, "app/main.txt", "modified after the intent was persisted\n")
        return original(self, ctx, intent)

    monkeypatch.setattr(GitWorkspace, "execute", execute)
    _, worker = run_commit(repository, job)
    assert worker.run_once().status == "DONE"
    commit = repository.commit_record(job.run_id)
    run = repository.get_run(job.run_id)
    assert commit.status == "INVALIDATED" and commit.commit is None
    assert commit.outcome.status == "invalidated" and "Content changed" in commit.outcome.diagnostic
    assert run.status == "STOPPED" and run.history.stop.stage == "commit"
    assert git(context.root, "rev-parse", "HEAD") == info.base_revision
    assert (context.root / "app/main.txt").read_text() == "modified after the intent was persisted\n"
    # An invalidated operation does not block a new explicit revalidation.
    repository.resume(job.run_id, key="revalidate", expected_version=run.version)


def test_head_moved_before_the_commit_object_exists_invalidates(task, repository, monkeypatch):
    context, info = task
    job, _ = accept(repository, context)
    # Crash before creating the object: nothing exists; moving HEAD invalidates it determinably.
    restore = crash_on(monkeypatch, written_commit)
    queued, worker = run_commit(repository, job)
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    restore()
    git(context.root, "commit", "-q", "--allow-empty", "-m", "someone else")
    recover(repository, job, queued)
    _, fresh = run_commit(repository, job, key="reconcile")
    fresh.run_once()
    assert repository.commit_record(job.run_id).status == "INVALIDATED"
    assert repository.get_run(job.run_id).status == "STOPPED"


def test_head_moving_during_the_effect_is_caught_by_compare_and_swap(task, repository, monkeypatch):
    context, info = task
    job, _ = accept(repository, context)
    original = Git.run

    def racing(self, *args, **kwargs):
        if ref_update(args):
            git(context.root, "commit", "-q", "--allow-empty", "-m", "racing writer")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Git, "run", racing)
    _, worker = run_commit(repository, job)
    assert worker.run_once().status == "DONE"
    commit = repository.commit_record(job.run_id)
    assert commit.status == "INVALIDATED" and "moved" in commit.outcome.diagnostic
    racing_head = git(context.root, "rev-parse", "HEAD")
    assert racing_head != commit.intent.expected_commit
    assert git(context.root, "rev-parse", "HEAD^") == info.base_revision  # nobody was overwritten
    assert repository.get_run(job.run_id).status == "STOPPED"


def test_unreachable_commit_object_is_quarantined_with_evidence(task, repository, monkeypatch):
    context, info = task
    job, _ = accept(repository, context)
    restore = crash_on(monkeypatch, ref_update)  # object written, reference not moved
    queued, worker = run_commit(repository, job)
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    restore()
    git(context.root, "commit", "-q", "--allow-empty", "-m", "someone else")
    moved = git(context.root, "rev-parse", "HEAD")
    recover(repository, job, queued)
    follow, fresh = run_commit(repository, job, key="reconcile")
    with pytest.raises(CommitUncertain, match="not reachable"):
        fresh.run_once()
    assert repository.get_job(follow.id).status == "RECOVERY_REQUIRED"
    assert repository.commit_record(job.run_id).status == "INTENT"
    assert git(context.root, "rev-parse", "HEAD") == moved
    assert repository.get_run(job.run_id).status == "RECOVERY_REQUIRED"


def test_crash_after_mechanical_write_resumes_the_same_sealed_tree(task, repository, monkeypatch):
    context, info = task
    job, _ = accept(repository, context)
    update = MechanicalUpdate("docs/STATE.md", "state\naccepted\n", "Record acceptance")
    original = GitWorkspace._write_mechanical

    def write_then_crash(self, ctx, intent):
        original(self, ctx, intent)
        raise SyntheticCrash()

    monkeypatch.setattr(GitWorkspace, "_write_mechanical", write_then_crash)
    queued, worker = run_commit(repository, job, mechanical=(update,))
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    monkeypatch.setattr(GitWorkspace, "_write_mechanical", original)
    assert (context.root / "docs/STATE.md").read_text() == "state\naccepted\n"
    assert git(context.root, "rev-parse", "HEAD") == info.base_revision
    recover(repository, job, queued)
    _, fresh = run_commit(repository, job, key="reconcile")
    fresh.run_once()
    commit = repository.commit_record(job.run_id)
    assert commit.status == "COMMITTED"
    assert git(context.root, "rev-parse", "HEAD^{tree}") == commit.intent.expected_tree
    assert commits_after(context.root, info.base_revision) == "1"
    assert git(context.root, "status", "--porcelain") == ""


# --- exclusion, serialization and migration ---------------------------------------------------

def test_commit_job_holds_the_checkout_writer_lock(task, repository):
    context, _ = task
    job, record = accept(repository, context)
    commit_job = repository.submit_commit(job.run_id, key="commit", expected_version=record.version)
    other = repository.submit(context, "P001-T002", PHASE, PLAN.replace("P001-T001", "P001-T002"), VERSIONS,
                              key="other-run-same-root")
    claim = repository.claim()
    assert claim.id == commit_job.id
    assert repository.claim() is None  # same canonical root: a single writer
    assert repository.get_job(other.id).status == "QUEUED"


def test_history_round_trip_preserves_provenance_and_old_shape(task, repository):
    context, _ = task
    _, record = accept(repository, context)
    dumped = dump_history(record.history)
    assert json.loads(dumped)["format"] == 5
    assert load_history(dumped) == record.history
    bare = replace(record.history, cycles=(), acceptance=None, attempts=(), prompt_catalog_json=None)
    assert json.loads(dump_history(bare))["format"] == 1
    assert "provenance_json" not in dump_history(bare)


def test_commit_migration_round_trip_keeps_managed_history(task, repository, migrated_database):
    context, _ = task
    job, _ = accept(repository, context)
    before = repository.get_run(job.run_id)
    command.check(migrated_database[1])
    command.downgrade(migrated_database[1], "0005_cli_processes")
    assert "managed_commits" not in inspect(repository.engine).get_table_names()
    command.upgrade(migrated_database[1], "head")
    assert "managed_commits" in inspect(repository.engine).get_table_names()
    assert repository.get_run(job.run_id) == before
    command.check(migrated_database[1])
