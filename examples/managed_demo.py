"""Opt-in synthetic UI fixture. Never imports or launches provider adapters.

Prepare a NEW directory: python -m examples.managed_demo /path/to/new-demo
Then set HARNESS_DEMO_ROOT to it and HARNESS_MANAGED_CONFIG=examples.managed_demo:build.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from my_harness.adapters.engine_fake import ScriptedCommandRunner
from my_harness.adapters.git import GitWorkspace, GitWorktrees
from my_harness.core.engine.commit import GitIdentity
from my_harness.core.engine.context import Command, EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.core.engine.journal import JournalError
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject

VERSIONS = {"engine": "h2-ui-demo-1", "agent_adapter": "synthetic-ui-1", "commands": "synthetic-1", "evidence": "git-1", "provider_cli": None}
PLAN = """# Synthetic UI plan
## P001-T001 — UI task
**Objective:** Change synthetic content.
**Allowed paths:** `app/**`
**Acceptance criteria:**
- Synthetic behavior is present.
**Validation commands:** `test-runner check`
**Executor:** synthetic-executor / medium — Explicit synthetic selection
"""
IDENTITY = GitIdentity("Harness Demo", "demo@example.invalid")


def context(root):
    return ProjectContext(root, ProjectProfile("synthetic-ui", validations=(Command(("test-runner", "check")),),
        allowed_command_prefixes=(("test-runner",),)), EnginePolicy(("synthetic-executor",), ("medium",),
        "synthetic-planner", "medium", "synthetic-reviewer", "high", max_revision_cycles=1))


class DemoAgent:
    def __init__(self, area):
        self.area = area

    def invoke(self, context, request):
        # Audit outside checkouts, so restart tests can prove the executor was not repeated.
        with (self.area / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"root": str(context.root), "role": request.role, "id": request.id}) + "\n")
        task = json.loads(request.task_json or "{}")
        if request.role == "executor":
            context.path("app/main.txt").write_text("implemented by synthetic UI adapter\n")
            payload = {"result": "synthetic; no provider"}
        elif request.role == "reviewer":
            marker = self.area / "recovery-injected"
            if context.root.name == "recovery" and not marker.exists():
                marker.write_text("one synthetic failure, retained across restarts\n")
                raise JournalError("Synthetic UI quarantine after executor; no live process")
            payload = {"task_id": task["task_id"], "verdict": "ACCEPT", "findings": [], "blocking_questions": [], "scope_grants": []}
        elif request.role == "phase":
            # H3.3: synthetic READY evaluation of the frozen criteria it receives as evidence.
            evidence = json.loads(request.prompt.split("Evidence:\n", 1)[1].split("\nReturn exactly one JSON object", 1)[0])
            phase = evidence["phase"]
            payload = {"phase_id": phase["code"], "verdict": "READY", "summary": "Synthetic phase review; no provider",
                       "exit_criteria_results": [{"criterion": c, "passed": True, "evidence": "synthetic"}
                                                 for c in phase["exit_criteria"]],
                       "required_actions": [], "blocking_questions": []}
        elif request.role == "chat":
            # H4.1: synthetic read-only answer with a proposal derived from the message.
            text = request.prompt.split("User message:\n", 1)[1].split("\nReturn exactly one JSON object", 1)[0].strip()
            payload = {"answer": f"Synthetic read-only answer; no provider. Message: {text}",
                       "references": ["app/main.txt"],
                       "proposals": [{"title": "Adjust app/main.txt", "objective": f"Apply the request: {text}",
                                      "scope": "Only app/main.txt", "acceptance_criteria": ["app/main.txt reflects the request"],
                                      "validation": ["test-runner check"], "rationale": "Synthetic chat proposal"}]}
        elif request.role == "planner":
            # H4.1: only for tasks created from a confirmed proposal; contract within the policy.
            data = json.loads(next(line for line in request.prompt.splitlines() if line.startswith('{"phase_id"')))
            payload = {"task_id": data["task_id"], "phase_id": data["phase_id"], "title": "Synthetic chat task",
                       "objective": "Apply the confirmed chat proposal", "executor_prompt": "Change app/main.txt",
                       "allowed_paths": ["app/**"], "forbidden_paths": [], "acceptance_criteria": ["app/main.txt changed"],
                       "validation_commands": [], "executor_selection": {"model": "synthetic-executor", "effort": "medium",
                                                                         "reason": "Synthetic planner selection"}}
        else:
            raise ValueError(f"Unsupported synthetic role {request.role}")
        return AgentResult(freeze(payload), terminal_observed=True, exit_code=0)


def build():
    area = Path(os.environ["HARNESS_DEMO_ROOT"]).resolve(strict=True)
    if (area / "demo-marker").read_text() != "synthetic-ui-v1\n":
        raise ValueError("Not a prepared synthetic UI area")
    agent = DemoAgent(area)
    def ports(ctx, versions):
        if versions != VERSIONS:
            raise ValueError("Frozen demo versions differ")
        return agent, ScriptedCommandRunner(), writer(ctx, versions)
    def writer(ctx, versions):
        if versions != VERSIONS:
            raise ValueError("Frozen demo versions differ")
        return GitWorkspace(IDENTITY)
    return ManagedConfig(tuple(ManagedProject(name, context(area / name), VERSIONS)
        for name in ("task", "recovery")), ports_factory=ports, commit_factory=writer,
        supervisor=True, poll_seconds=0.1)


def prepare(area):
    area = area.resolve()
    area.mkdir(exist_ok=False)
    (area / "demo-marker").write_text("synthetic-ui-v1\n")
    (area / "task.md").write_text(PLAN)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": IDENTITY.name, "GIT_AUTHOR_EMAIL": IDENTITY.email,
           "GIT_COMMITTER_NAME": IDENTITY.name, "GIT_COMMITTER_EMAIL": IDENTITY.email}
    for name in ("source", "recovery"):
        root = area / name
        (root / "app").mkdir(parents=True)
        (root / "app/main.txt").write_text("baseline\n")
        (root / ".gitignore").write_text(".harness/runs/\n.harness/managed-mode.json\n")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "synthetic baseline")):
            subprocess.run(["git", "-C", str(root), *args], env=env, check=True)
    GitWorktrees().prepare(area / "source", area / "task", branch="harness/ui-task")
    return area


if __name__ == "__main__":
    print(prepare(Path(sys.argv[1])))
