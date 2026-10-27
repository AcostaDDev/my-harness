"""H2.2: synthetic SQLite and checkouts; no agent CLI or network."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Event

from alembic import command
import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.fake import FakeSimulationAdapter
from my_harness.core.engine.context import Command, EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.contracts import AgentResult, freeze, stop_history
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.serialization import dump_history, load_history, restore_context
from my_harness.core.engine.validation import CommandResult
from my_harness.core.simulation import SimulationService
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, OwnershipLost, SQLiteManagedRepository
from my_harness.storage.models import (
    CheckoutLockRow, ManagedAttemptRow, ManagedEventRow, ManagedJobRow, ManagedRunRow,
)
from my_harness.storage.repository import SQLiteSimulationRepository
from my_harness.storage.schema import require_schema


VERSIONS = {"engine": "h2.2", "agent_adapter": "synthetic-1", "commands": "synthetic-1",
            "evidence": "synthetic-1", "provider_cli": None}
PLAN = """# Synthetic H2.2 plan
## P001-T001 — Persistent task
**Objective:** Change synthetic content.
**Allowed paths:** `app/**`
**Acceptance criteria:**
- Synthetic behavior is present.
**Validation commands:** `test-runner check`
**Executor:** synthetic-executor / medium — Explicit test selection
"""


def review(verdict="ACCEPT"):
    data = {"task_id": "P001-T001", "verdict": verdict, "findings": [], "blocking_questions": [], "scope_grants": []}
    if verdict == "REVISE":
        data.update(next_prompt="Correct synthetic content", executor_selection={
            "model": "synthetic-executor", "effort": "medium", "reason": "Explicit correction"})
    return data


def edit(text="implemented"):
    def call(context, request):
        context.path("app/main.txt").write_text(text, encoding="utf-8")
        return {"result": "synthetic"}
    return call


@pytest.fixture
def context(tmp_path):
    root = tmp_path / "managed-checkout"
    root.mkdir()
    # A repository, as every live checkout is: the synthetic Codex refuses anything else (D124).
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    (root / "app").mkdir()
    (root / "app/main.txt").write_text("baseline", encoding="utf-8")
    return ProjectContext(root, ProjectProfile("synthetic", validations=(Command(("test-runner", "check")),),
                                              allowed_command_prefixes=(("test-runner",),)),
                          EnginePolicy(("synthetic-executor",), ("medium",), "synthetic-planner", "medium",
                                       "synthetic-reviewer", "high", max_revision_cycles=1))


@pytest.fixture
def repository(migrated_database):
    engine = make_engine(migrated_database[0])
    yield SQLiteManagedRepository(engine)
    engine.dispose()


def submit(repository, context, key="start", **kwargs):
    return repository.submit(context, "P001-T001", "P001", PLAN, VERSIONS, key=key, **kwargs)


def worker(repository, context, responses, commands=(), workspace=None, **kwargs):
    agents = ScriptedAgentAdapter(responses)
    runner = ScriptedCommandRunner(commands)
    evidence = workspace or SyntheticWorkspace(context, ("app/main.txt",))

    def factory(frozen, versions):
        assert frozen == context and versions == VERSIONS
        return agents, runner, evidence

    return LocalSupervisor(repository, factory, **kwargs), agents, runner, evidence


def rows(repository, model):
    with Session(repository.engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def attempts(repository, run_id):
    with Session(repository.engine) as session:
        return [{"number": row.number, "status": row.status, "request": json.loads(row.request_json),
                 "versions": json.loads(row.versions_json), "result": json.loads(row.result_json) if row.result_json else None}
                for row in session.scalars(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id == run_id)
                                           .order_by(ManagedAttemptRow.number))]


def test_persisted_history_snapshots_results_events_survive_restart(repository, context, migrated_database):
    job = submit(repository, context)
    assert repository.get_run(job.run_id).status == "QUEUED"
    supervisor, agents, runner, _ = worker(repository, context, [edit(), review()])
    assert supervisor.run_once().status == "DONE"
    initial = repository.get_run(job.run_id)
    assert initial.status == "ACCEPTANCE_READY" and initial.history.acceptance.eligible
    assert load_history(dump_history(initial.history)) == initial.history
    assert restore_context(initial.history.context_json) == context
    ledger = attempts(repository, job.run_id)
    assert [a["number"] for a in ledger] == [1, 2]
    assert [a["request"]["role"] for a in ledger] == ["executor", "reviewer"]
    assert all(a["versions"] == VERSIONS and a["status"] == "COMPLETED" for a in ledger)
    assert all(a["request"]["fresh_session"] for a in ledger)
    assert all(a["request"]["task_json"] == initial.history.task_json for a in ledger)
    assert initial.history.cycles[0].validation.entries[0].result.duration_seconds is None
    assert ledger[0]["versions"]["provider_cli"] is None
    assert rows(repository, CheckoutLockRow) == 0
    events = repository.events(job.run_id)
    assert [e["sequence"] for e in events] == list(range(1, initial.version + 1))
    assert len({e["id"] for e in events}) == len(events)
    assert events[-1]["kind"] == "job_finished" and events[-1]["payload"]["status"] == initial.status
    assert all(datetime.fromisoformat(e["recorded_at"]).utcoffset() == timedelta(0) for e in events)
    assert sum(e["kind"] == "command_started" for e in events) == len(runner.calls) == 1
    assert sum(e["kind"] == "command_finished" for e in events) == 1
    engine = make_engine(migrated_database[0])
    try:
        restarted = SQLiteManagedRepository(engine)
        assert restarted.get_run(job.run_id) == initial
        assert restarted.events(job.run_id) == events
        assert submit(restarted, context) == restarted.get_job(job.id)
        assert LocalSupervisor(restarted, lambda *_: pytest.fail("No restart invocation")).run_once() is None
        assert len(agents.requests) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", [RuntimeError("Synthetic quota error"),
    AgentResult('{"partial":', terminal_observed=False, raw_output="partial raw bytes"),
    AgentResult('{"malformed":', terminal_observed=True, exit_code=0)])
def test_agent_failures_persist_without_fallback(repository, context, failure):
    job = submit(repository, context)
    supervisor, agents, runner, _ = worker(repository, context, [failure])
    assert supervisor.run_once().status == "DONE"
    history = repository.get_run(job.run_id).history
    assert history.status == "stopped" and history.stop.stage == "executor"
    assert len(history.attempts) == len(agents.requests) == 1 and not runner.calls
    assert attempts(repository, job.run_id)[0]["result"] == asdict(history.attempts[0].result)
    assert rows(repository, CheckoutLockRow) == 0
    assert supervisor.run_once() is None


def test_revalidation_restart_keeps_budget_and_history(repository, context, migrated_database):
    job = submit(repository, context)
    supervisor, _, _, workspace = worker(repository, context, [edit(), review("REVISE"), edit("corrected"), review("BLOCKED")])
    supervisor.run_once()
    old = repository.get_run(job.run_id)
    assert old.history.revisions == old.revisions == 1
    engine = make_engine(migrated_database[0])
    try:
        restarted = SQLiteManagedRepository(engine)
        retry = restarted.resume(job.run_id, key="retry", expected_version=old.version, retry_executor=True)
        assert restarted.resume(job.run_id, key="retry", expected_version=old.version, retry_executor=True) == retry
        exhausted, agents, _, _ = worker(restarted, context, [], workspace=workspace)
        exhausted.run_once()
        limited = restarted.get_run(job.run_id)
        assert limited.history.status == "revision_limit" and not agents.requests
        assert limited.history.attempts == old.history.attempts
        restarted.resume(job.run_id, key="revalidate", expected_version=limited.version)
        revalidate, agents, _, _ = worker(restarted, context, [review()], workspace=workspace)
        revalidate.run_once()
        result = restarted.get_run(job.run_id)
        assert result.history.status == "acceptance_ready" and result.revisions == 1
        assert [r.role for r in agents.requests] == ["reviewer"]
        assert result.history.cycles[:len(old.history.cycles)] == old.history.cycles
        assert result.history.attempts[:len(old.history.attempts)] == old.history.attempts
        assert len({a.request.id for a in result.history.attempts}) == 5
    finally:
        engine.dispose()


def test_explicit_retry_after_failed_execution_uses_new_attempt(repository, context):
    job = submit(repository, context)
    first, _, _, workspace = worker(repository, context, [RuntimeError("Synthetic failure")])
    first.run_once()
    before = repository.get_run(job.run_id)
    repository.resume(job.run_id, key="retry", expected_version=before.version, retry_executor=True)
    retry, agents, _, _ = worker(repository, context, [edit(), review()], workspace=workspace)
    retry.run_once()
    after = repository.get_run(job.run_id)
    assert after.history.status == "acceptance_ready" and after.revisions == 1
    assert after.history.attempts[0] == before.history.attempts[0]
    assert after.history.stops == before.history.stops
    assert agents.requests[0].id != before.history.attempts[0].request.id
    assert agents.requests[0].selection == before.history.attempts[0].request.selection


def test_threaded_double_requests_and_claims_invoke_once(repository, context, migrated_database):
    barrier = Barrier(8)

    def request(_):
        engine = make_engine(migrated_database[0])
        try:
            local = SQLiteManagedRepository(engine)
            barrier.wait(timeout=10)
            return submit(local, context)
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=8) as pool:
        requested = list(pool.map(request, range(8)))
    assert len({j.id for j in requested}) == len({j.run_id for j in requested}) == 1
    supervisor, agents, _, _ = worker(repository, context, [edit(), review()])
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: supervisor.run_once(), range(8)))
    assert sum(result is not None for result in outcomes) == 1
    assert [r.role for r in agents.requests] == ["executor", "reviewer"]
    assert rows(repository, ManagedRunRow) == rows(repository, ManagedJobRow) == 1


def test_processes_share_idempotency_and_writer_lock(repository, context, migrated_database):
    probe = Path(__file__).with_name("managed_process_probe.py")
    payload = {"database": migrated_database[0], "context": json.loads(
        # Use the real snapshot of the canonical context, never private data.
        submit(repository, context).request_json)["context_json"], "plan": PLAN, "versions": VERSIONS}

    def run(action):
        result = subprocess.run([sys.executable, str(probe)], input=freeze({**payload, "action": action}),
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    with ThreadPoolExecutor(max_workers=6) as pool:
        submitted = list(pool.map(run, ["submit"] * 6))
    assert len({item["job_id"] for item in submitted}) == 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        executed = list(pool.map(run, ["run"] * 6))
    assert sum(item["executed"] for item in executed) == 1
    assert context.path("app/invocations.txt").read_text().splitlines() == ["executor"]
    assert rows(repository, ManagedRunRow) == rows(repository, ManagedJobRow) == 1
    assert rows(repository, CheckoutLockRow) == 0


def test_canonical_roots_share_lock_and_other_checkout_progresses(repository, context, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(context.root, target_is_directory=True)
    equivalent = replace(context, root=alias)
    first = submit(repository, context)
    assert submit(repository, equivalent) == first
    second = submit(repository, equivalent, key="second")
    other_root = tmp_path / "other-checkout"
    other_root.mkdir()
    other = replace(context, root=other_root)
    third = submit(repository, other, key="other")
    claimed = repository.claim()
    assert claimed.id == first.id
    assert repository.claim().id == third.id
    assert repository.claim() is None  # the second waits for the same root
    history = repository.get_run(first.run_id).history
    repository.finish(claimed, stop_history(history, "start", "Synthetic explicit stop before effects"))
    assert repository.claim().id == second.id


def test_different_checkouts_execute_concurrently_while_same_checkout_waits(repository, context, tmp_path):
    other_root = tmp_path / "other-concurrent-checkout"
    (other_root / "app").mkdir(parents=True)
    (other_root / "app/main.txt").write_text("baseline", encoding="utf-8")
    other = replace(context, root=other_root)
    submit(repository, context)
    waiting = submit(repository, context, key="same-root-waiting")
    submit(repository, other, key="different-root")
    release = Event()
    entered = {context.root: Event(), other.root: Event()}
    workspaces = {item.root: SyntheticWorkspace(item, ("app/main.txt",)) for item in (context, other)}

    def factory(frozen, versions):
        assert versions == VERSIONS

        def execute(context, request):
            entered[context.root].set()
            assert release.wait(timeout=5)
            return edit()(context, request)

        return ScriptedAgentAdapter([execute, review()]), ScriptedCommandRunner(), workspaces[frozen.root]

    supervisor = LocalSupervisor(repository, factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(supervisor.run_once) for _ in range(2)]
        try:
            assert all(item.wait(timeout=5) for item in entered.values())
            assert rows(repository, CheckoutLockRow) == 2
            assert repository.claim() is None
            assert repository.get_job(waiting.id).status == "QUEUED"
        finally:
            release.set()
        assert all(future.result(timeout=5).status == "DONE" for future in futures)
    assert repository.claim().id == waiting.id


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def test_expired_lease_never_unlocks_or_requeues(repository, context):
    clock = Clock()
    repository.clock = clock
    job = submit(repository, context)
    following = submit(repository, context, key="following")
    owner = repository.claim(lease_seconds=5)
    clock.now += timedelta(seconds=4)
    repository.heartbeat(owner, lease_seconds=5)
    clock.now += timedelta(seconds=4)
    assert repository.recover_expired() == []
    clock.now += timedelta(seconds=2)
    assert repository.recover_expired() == [job.id]
    assert repository.recover_expired() == []
    assert repository.get_job(job.id).status == "RECOVERY_REQUIRED"
    assert rows(repository, CheckoutLockRow) == 1 and repository.claim() is None
    for action in (lambda: repository.heartbeat(owner),
                   lambda: repository.checkpoint(owner, repository.get_run(job.run_id).history, "executor"),
                   lambda: repository.finish(owner, repository.get_run(job.run_id).history)):
        with pytest.raises(OwnershipLost):
            action()
    record = repository.get_run(job.run_id)
    with pytest.raises(Conflict):
        repository.confirm_stopped(job.id, owner_token="stale", expected_version=record.version, reason="Stopped")
    with pytest.raises(Conflict):
        repository.confirm_stopped(job.id, owner_token=owner.owner_token, expected_version=record.version - 1, reason="Stopped")
    repository.confirm_stopped(job.id, owner_token=owner.owner_token, expected_version=record.version,
                               reason="Synthetic owner joined; no process remains")
    assert repository.get_run(job.run_id).status == "INTERRUPTED"
    assert repository.claim().id == following.id
    with pytest.raises(Conflict):
        repository.confirm_stopped(job.id, owner_token=owner.owner_token, expected_version=record.version, reason="Duplicate")


class SyntheticCrash(BaseException):
    pass


def test_crash_during_correction_reserves_budget_and_needs_explicit_recovery(repository, context):
    clock = Clock()
    repository.clock = clock
    job = submit(repository, context)

    def crash(context, request):
        context.path("app/main.txt").write_text("partial correction", encoding="utf-8")
        raise SyntheticCrash()

    supervisor, agents, _, workspace = worker(repository, context, [edit(), review("REVISE"), crash])
    with pytest.raises(SyntheticCrash):
        supervisor.run_once()
    during = repository.get_run(job.run_id)
    assert during.revisions == 1 and during.history.revisions == 0  # intention reserved, still without result
    assert attempts(repository, job.run_id)[-1]["result"] is None
    assert len(agents.requests) == 3
    clock.now += timedelta(seconds=31)
    assert repository.recover_expired() == [job.id]
    assert supervisor.run_once() is None
    quarantined = repository.get_run(job.run_id)
    owner = repository.get_job(job.id).owner_token
    repository.confirm_stopped(job.id, owner_token=owner, expected_version=quarantined.version,
                               reason="Synthetic call unwound and its heartbeat thread joined")
    stopped = repository.get_run(job.run_id)
    assert stopped.history.revisions == stopped.revisions == 1
    assert attempts(repository, job.run_id)[-1]["status"] == "INTERRUPTED"
    assert stopped.history.attempts[-1].result.exit_code is None
    assert context.path("app/main.txt").read_text() == "partial correction"
    repository.resume(job.run_id, key="retry", expected_version=stopped.version, retry_executor=True)
    limited, fresh, _, _ = worker(repository, context, [], workspace=workspace)
    limited.run_once()
    assert not fresh.requests and repository.get_run(job.run_id).history.status == "revision_limit"
    latest = repository.get_run(job.run_id)
    repository.resume(job.run_id, key="revalidate", expected_version=latest.version)
    revalidate, fresh, _, _ = worker(repository, context, [review()], workspace=workspace)
    revalidate.run_once()
    assert [r.role for r in fresh.requests] == ["reviewer"]
    assert repository.get_run(job.run_id).history.status == "acceptance_ready"


@pytest.mark.parametrize("kind", ["job_queued", "job_claimed", "attempt_started", "job_finished"])
def test_transition_failure_rolls_back_states_results_events(repository, context, monkeypatch, kind):
    original = repository._event

    def fail(session, run, event_kind, payload):
        original(session, run, event_kind, payload)
        if event_kind == kind:
            raise RuntimeError("Synthetic transactional failure")

    if kind == "job_queued":
        monkeypatch.setattr(repository, "_event", fail)
        with pytest.raises(RuntimeError):
            submit(repository, context)
        assert rows(repository, ManagedRunRow) == rows(repository, ManagedJobRow) == rows(repository, ManagedEventRow) == 0
        return
    job = submit(repository, context)
    monkeypatch.setattr(repository, "_event", fail)
    supervisor, agents, _, _ = worker(repository, context, [edit(), review()])
    with pytest.raises((RuntimeError, JournalError)):
        supervisor.run_once()
    kinds = [e["kind"] for e in repository.events(job.run_id)]
    assert kind not in kinds
    if kind == "job_claimed":
        assert repository.get_job(job.id).status == "QUEUED" and rows(repository, CheckoutLockRow) == 0
    else:
        assert repository.get_job(job.id).status == "RECOVERY_REQUIRED" and rows(repository, CheckoutLockRow) == 1
    if kind == "attempt_started":
        assert not agents.requests and rows(repository, ManagedAttemptRow) == 0
        assert context.path("app/main.txt").read_text() == "baseline"
    if kind == "job_finished":
        assert len(agents.requests) == 2 and repository.get_run(job.run_id).history.acceptance is None
        assert repository.get_run(job.run_id).history.cycles[-1].verdict == "ACCEPT"


def test_result_write_failure_preserves_unknown_intent_and_stops_next_effect(repository, context, monkeypatch):
    job = submit(repository, context)
    original = repository._event

    def fail(session, run, kind, payload):
        original(session, run, kind, payload)
        if kind == "checkpoint" and load_history(run.history_json).attempts:
            raise RuntimeError("Synthetic failure after invocation before confirmation")

    monkeypatch.setattr(repository, "_event", fail)
    supervisor, agents, runner, _ = worker(repository, context, [edit()])
    with pytest.raises(JournalError):
        supervisor.run_once()
    assert len(agents.requests) == 1 and not runner.calls
    assert repository.get_run(job.run_id).history.attempts == ()
    assert attempts(repository, job.run_id)[0]["result"] is None
    assert context.path("app/main.txt").read_text() == "implemented"
    assert repository.get_job(job.id).status == "RECOVERY_REQUIRED"
    assert rows(repository, CheckoutLockRow) == 1


@pytest.mark.parametrize("failure_kind", ["command_started", "command_finished"])
def test_command_persistence_failure_does_not_continue_to_review(repository, context, monkeypatch, failure_kind):
    job = submit(repository, context)
    original = repository._event

    def fail(session, run, kind, payload):
        original(session, run, kind, payload)
        if kind == failure_kind:
            raise RuntimeError("Synthetic command persistence failure")

    monkeypatch.setattr(repository, "_event", fail)
    supervisor, agents, runner, _ = worker(repository, context, [edit()])
    with pytest.raises(JournalError):
        supervisor.run_once()
    assert [request.role for request in agents.requests] == ["executor"]
    assert len(runner.calls) == (1 if failure_kind == "command_finished" else 0)
    assert failure_kind not in [event["kind"] for event in repository.events(job.run_id)]
    assert repository.get_run(job.run_id).history.cycles == ()
    assert repository.get_job(job.id).status == "RECOVERY_REQUIRED"
    assert rows(repository, CheckoutLockRow) == 1


def test_ports_factory_failure_never_reselects_versions_or_requeues(repository, context):
    job = submit(repository, context)

    def unsupported(frozen, versions):
        assert versions == VERSIONS
        raise ValueError("Synthetic version unavailable")

    supervisor = LocalSupervisor(repository, unsupported)
    with pytest.raises(ValueError, match="unavailable"):
        supervisor.run_once()
    assert repository.get_job(job.id).status == "RECOVERY_REQUIRED"
    assert repository.get_run(job.run_id).versions_json == freeze(VERSIONS)
    assert supervisor.run_once() is None and rows(repository, ManagedAttemptRow) == 0


def test_work_has_no_open_sqlite_transaction_and_heartbeat_runs(repository, context):
    job = submit(repository, context)
    entered, release, heartbeat = Event(), Event(), Event()
    original = repository.heartbeat

    def observed(*args, **kwargs):
        original(*args, **kwargs)
        heartbeat.set()

    repository.heartbeat = observed

    def long_call(context, request):
        # Another writing transaction finishes while the adapter waits.
        submit(repository, context, key="while-running")
        entered.set()
        assert release.wait(timeout=5)
        return edit()(context, request)

    supervisor, _, _, _ = worker(repository, context, [long_call, review()], lease_seconds=1.5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(supervisor.run_once)
        try:
            assert entered.wait(timeout=5)
            assert heartbeat.wait(timeout=5)
            assert repository.claim() is None
        finally:
            release.set()
        assert future.result(timeout=5).id == job.id
    assert repository.get_run(job.run_id).history.status == "acceptance_ready"


def test_transient_heartbeat_failure_is_retried_without_stopping_work(repository, context, monkeypatch):
    from sqlalchemy.exc import OperationalError
    job = submit(repository, context)
    renewed = Event()
    original, calls = repository.heartbeat, []

    def transient(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise OperationalError('UPDATE', {}, Exception('database is locked'))
        original(*args, **kwargs)
        renewed.set()

    monkeypatch.setattr(repository, 'heartbeat', transient)

    def slow(context, request):
        assert renewed.wait(timeout=5)
        return edit()(context, request)

    supervisor, _, _, _ = worker(repository, context, [slow, review()], lease_seconds=1.5)
    assert supervisor.run_once().status == 'DONE'
    assert len(calls) >= 2
    assert repository.get_run(job.run_id).status == 'ACCEPTANCE_READY'
    closed = next(e for e in repository.events(job.run_id) if e['kind'] == 'process_owner_closed')
    assert closed['payload']['heartbeat'] == {'failures': 1, 'last_error': 'OperationalError', 'lost': False}


def test_heartbeat_ownership_loss_prevents_later_calls_and_retains_lock(repository, context, monkeypatch):
    job = submit(repository, context)
    failed = Event()

    def broken(*args, **kwargs):
        failed.set()
        raise OwnershipLost("Synthetic ownership loss")

    monkeypatch.setattr(repository, "heartbeat", broken)

    def slow(context, request):
        assert failed.wait(timeout=5)
        return {"result": "synthetic"}

    supervisor, agents, runner, _ = worker(repository, context, [slow], lease_seconds=1.5)
    with pytest.raises(JournalError, match="Heartbeat"):
        supervisor.run_once()
    assert len(agents.requests) == 1 and not runner.calls
    assert repository.get_job(job.id).status == "RECOVERY_REQUIRED"
    assert rows(repository, CheckoutLockRow) == 1


def test_mode_change_after_admission_refuses_the_claim_before_any_effect(repository, context):
    """P011-T013: ACTIVE → REFUSED in flows/task-run.md; a foreign marker after queueing closes job and lock."""
    job = submit(repository, context)
    marker = context.root / ".harness/managed-mode.json"
    marker.parent.mkdir()
    marker.write_text("{}", encoding="utf-8")
    supervisor, agents, runner, _ = worker(repository, context, [edit(), review()])
    assert supervisor.run_once().status == "REFUSED"
    run = repository.get_run(job.run_id)
    assert run.status == "REFUSED" and run.stage == "mode_guard"
    assert repository.get_job(job.id).status == "REFUSED"
    assert not agents.requests and not runner.calls and rows(repository, CheckoutLockRow) == 0
    assert attempts(repository, job.run_id) == []


def test_conflicts_and_frozen_history_are_rejected(repository, context):
    job = submit(repository, context)
    with pytest.raises(Conflict):
        submit(repository, replace(context, policy=replace(context.policy, max_revision_cycles=2)))
    with pytest.raises(Conflict):
        repository.submit(context, "P001-T001", "P001", PLAN, {**VERSIONS, "engine": "other"}, key="start")
    supervisor, _, _, _ = worker(repository, context, [edit(), review("BLOCKED")])
    supervisor.run_once()
    record = repository.get_run(job.run_id)
    with pytest.raises(Conflict, match="changed"):
        repository.resume(job.run_id, key="resume", expected_version=record.version - 1)
    repository.resume(job.run_id, key="resume", expected_version=record.version)
    with pytest.raises(Conflict, match="unfinished"):
        repository.resume(job.run_id, key="another", expected_version=repository.get_run(job.run_id).version)
    claim = repository.claim()
    with pytest.raises(Conflict, match="contract"):
        repository.checkpoint(claim, replace(record.history, task_json='{"changed":true}'), "executor")
    with pytest.raises(Conflict, match="history"):
        repository.checkpoint(claim, replace(record.history, attempts=()), "executor")
    with pytest.raises(Conflict, match="context"):
        repository.checkpoint(claim, replace(record.history, context_json='{}'), "executor")
    assert repository.get_run(job.run_id).history == record.history




def test_managed_database_cannot_live_inside_agent_checkout(repository, context):
    engine = make_engine(f"sqlite:///{context.root / 'state.sqlite3'}")
    # Avoid creating/opening the database: check the guard on an already prepared repository.
    previous = repository.engine
    repository.engine = engine
    try:
        with pytest.raises(ValueError, match="outside"):
            submit(repository, context)
        assert not (context.root / "state.sqlite3").exists()
    finally:
        repository.engine = previous
        engine.dispose()


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_invalid_lease_has_no_effect(repository, seconds):
    with pytest.raises(ValueError):
        repository.claim(lease_seconds=seconds)
    assert rows(repository, ManagedEventRow) == 0


def test_codec_handles_preparation_and_failed_validation(repository, context):
    context = replace(context, profile=replace(context.profile, preparation=(Command(("prepare", "synthetic")),)))
    job = submit(repository, context)
    supervisor, _, _, _ = worker(repository, context, [edit(), review()], commands=[CommandResult(0), CommandResult(2)])
    supervisor.run_once()
    history = repository.get_run(job.run_id).history
    assert history.stop.stage == "acceptance" and not history.acceptance.eligible
    assert len(history.preparation_json) == 1 and not history.cycles[0].validation.all_passed
    assert load_history(dump_history(history)) == history
