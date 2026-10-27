"""P010-T007: gaps of the acceptance matrix (SPECIFICATION §10, criteria 2 and 13) through the managed API.

Temporary Git/SQLite, fake agents and commands; no provider, network or private run.
"""

from my_harness.core.engine.validation import CommandResult

from test_managed_api import (  # noqa: F401 (fixtures)
    Ports, action, all_events, client, config, edit, engine, git, repo, review, settle, submit, task, url)

SELECTION = {"model": "synthetic-executor", "effort": "medium", "reason": "Fix the failing synthetic test"}


def revise():
    return {**review(), "verdict": "REVISE", "next_prompt": "Make the synthetic test pass",
            "executor_selection": dict(SELECTION), "findings": [{
                "severity": "high", "category": "testing", "file": "app/main.txt", "problem": "Synthetic test fails"}]}


def correct(context, request):
    context.path("app/main.txt").write_text("corrected\n", encoding="utf-8")
    return {"result": "synthetic correction"}


def test_failed_test_correction_review_and_commit_keep_the_whole_history(tmp_path, url, task):
    """Criterion 2: test failure → correction → review → commit, with both cycles and their attempts."""
    base = git(task.root, "rev-parse", "HEAD")
    ports = Ports([edit, revise(), correct, review()], [CommandResult(1, stderr="Synthetic failed assertion")])
    with client(url, tmp_path, config(task, ports)) as http:
        job = submit(http).json()
        run = settle(http, job["run_id"])
        assert run["status"] == "ACCEPTANCE_READY" and run["history"]["acceptance"]["eligible"] is True
        cycles = http.get(f"/api/managed/runs/{job['run_id']}/cycles").json()["items"]
        assert [cycle["verdict"] for cycle in cycles] == ["REVISE", "ACCEPT"]
        first, second = (cycle["validation"]["entries"][0]["result"] for cycle in cycles)
        assert first["exit_code"] == 1 and second["exit_code"] == 0
        assert cycles[0]["review"] == revise() and cycles[1]["review"] == review()
        assert cycles[0]["fingerprint"] != cycles[1]["fingerprint"]
        attempts = http.get(f"/api/managed/runs/{job['run_id']}/attempts").json()["items"]
        assert [(a["number"], a["role"], a["status"]) for a in attempts] == [
            (1, "executor", "COMPLETED"), (2, "reviewer", "COMPLETED"),
            (3, "executor", "COMPLETED"), (4, "reviewer", "COMPLETED")]

        assert action(http, job["run_id"], "commit", run["version"], "commit").status_code == 202
        final = settle(http, job["run_id"])
        assert final["status"] == "COMMITTED"
        assert final["commit"]["commit"] == git(task.root, "rev-parse", "HEAD")
        assert git(task.root, "rev-list", "--count", f"{base}..HEAD") == "1"
        assert git(task.root, "show", "HEAD:app/main.txt") == "corrected"
        # The full history stays readable after the commit: same cycles and attempts.
        assert http.get(f"/api/managed/runs/{job['run_id']}/cycles").json()["items"] == cycles
        assert http.get(f"/api/managed/runs/{job['run_id']}/attempts").json()["items"] == attempts
        events = all_events(http, job["run_id"])
        assert [event["sequence"] for event in events] == list(range(1, final["version"] + 1))
    assert ports.roles() == ["executor", "reviewer", "executor", "reviewer"]
    assert ports.agents.requests[2].selection.model == SELECTION["model"]


def test_event_cursor_resumes_across_a_restart_without_gaps_or_duplicates(tmp_path, url, task):
    """Criterion 13 (D029, T007 interpretation): the managed UI cursor replaces SSE.

    Small pages are read while the run advances, the service restarts and reading continues from the last
    accepted cursor; repeating keeps the prefix already read. An incomplete page may grow with new events."""
    ports = Ports([edit, review()])
    seen, cursor = [], 0

    def drain(http):
        nonlocal cursor
        while True:
            page = http.get(f"/api/managed/runs/{job['run_id']}/events", params={"after": cursor, "limit": 2}).json()
            assert [event["sequence"] for event in page["items"]] == list(range(cursor + 1, page["cursor"] + 1))
            again = http.get(f"/api/managed/runs/{job['run_id']}/events", params={"after": cursor, "limit": 2}).json()
            assert again["items"][:len(page["items"])] == page["items"]
            seen.extend(page["items"])
            cursor = page["cursor"]
            if not page["has_more"]:
                return

    with client(url, tmp_path, config(task, ports)) as http:
        job = submit(http).json()
        drain(http)
        run = settle(http, job["run_id"])
        drain(http)
        assert action(http, job["run_id"], "commit", run["version"], "commit").status_code == 202
    # Restart: the commit may be queued or finished; the cursor stays valid in the new service.
    with client(url, tmp_path, config(task, ports)) as http:
        final = settle(http, job["run_id"])
        drain(http)
        assert final["status"] == "COMMITTED"
        assert seen == all_events(http, job["run_id"])
    assert [event["sequence"] for event in seen] == list(range(1, final["version"] + 1))
    assert len({event["id"] for event in seen}) == len(seen)
