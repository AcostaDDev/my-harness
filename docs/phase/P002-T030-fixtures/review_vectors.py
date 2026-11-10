"""Offline assertions for the T030 synthetic design vectors, using only the standard library."""

from hashlib import sha256
import json
from pathlib import Path


def digest(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def unique_object(pairs):
    result = dict(pairs)
    assert len(result) == len(pairs), pairs
    return result


SEMANTIC = json.loads(
    Path(__file__).with_name("semantic.json").read_text(), object_pairs_hook=unique_object
)
MEMBERS = {member["id"]: member for member in SEMANTIC["records"]}
LINKS = SEMANTIC["links"]


def target(kind, source):
    return next(link["to"] for link in LINKS if (link["kind"], link["from"]) == (kind, source))


def check_fixture():
    assert len(MEMBERS) == len(SEMANTIC["records"]) == 27
    assert list(MEMBERS) == sorted(MEMBERS)
    assert len({(m["kind"], m["code"]) for m in MEMBERS.values()}) == len(MEMBERS)
    keys = [(edge["kind"], edge["from"], edge["to"]) for edge in LINKS]
    assert keys == sorted(set(keys)) and len(keys) == 22
    assert all(source in MEMBERS and dest in MEMBERS for _, source, dest in keys)
    groups = {}
    for edge in LINKS:
        if edge["position"] is not None:
            group = (edge["kind"], edge["to"], MEMBERS[edge["from"]]["kind"])
            groups.setdefault(group, []).append(edge["position"])
    for positions in groups.values():
        assert sorted(positions) == list(range(len(positions)))


def check_coverage():
    route = ("task_admit", "I02", "task_validate", "task_review", "I03", "task_accept",
             "task_export_commit", "phase_validate", "I04", "phase_ready")
    producers = {"sample-check": "task_validate", "phase-check": "phase_validate"}

    def check_producer(check, boundary):
        return route.index(producers[check]) < route.index(boundary)

    def slot(evidence):
        definition = MEMBERS[evidence]["content"]
        criterion_or_gate = target("requires_evidence", evidence)
        return criterion_or_gate, definition["alternatives"][0]["check"]

    task_slots = dict(slot(evidence) for evidence in
                      ("evidence-t", "evidence-s", "evidence-r", "evidence-gate"))
    assert set(task_slots) == {"criterion-t", "criterion-s", "criterion-r", "gate"}
    assert {target("criterion_of", criterion) for criterion in task_slots if criterion != "gate"} == {
        "task", "subtask", "requirement"
    }
    assert target("part_of", "subtask") == "task"
    assert target("addresses", "task") == "requirement"
    assert target("requires_gate", "task") == "gate"
    assert MEMBERS["gate"]["content"]["boundaries"] == ["task_accept"]
    assert all(check_producer(check, "task_accept") for check in task_slots.values())
    assert not any(check_producer(check, boundary) for check in task_slots.values()
                   for boundary in ("task_admit", "I02", "task_validate"))
    assert not check_producer("phase-check", "task_accept")

    for verdict in ("passed", "failed"):
        history = list(route[:3])  # A fresh admission and validation start with no check record.
        candidate = ("rev-2", "task", 1, "candidate-A", "sample-check")
        terminal = {"binding": candidate, "status": verdict}
        assert terminal["binding"] == candidate and terminal["status"] in {"passed", "failed"}
        history.extend(("task_review", "I03"))
        if verdict == "failed":
            assert history == list(route[:5])
            assert terminal["status"] != "passed"  # No acceptance or downstream effect.
            continue

        task_receipt = {"task": "task", "candidate": "candidate-A", "validation": digest(terminal),
                        "criteria": sorted(task_slots), "inputs": "inputs-A", "commit": "commit-A"}
        history.extend(("task_accept", "task_export_commit", "phase_validate", "I04"))
        criterion, phase_check = slot("evidence-p")
        assert target("criterion_of", criterion) == target("part_of", task_receipt["task"]) == "phase"
        confirmed_mapping = {"criterion-p": "task"}
        assert confirmed_mapping[criterion] == task_receipt["task"]
        assert check_producer(phase_check, "phase_ready")
        phase_snapshot = {"subject": "phase", "tree": "tree-A", "included_commit": "commit-A",
                          "task_inputs": "inputs-A", "check": "phase-check", "status": "passed"}
        assert phase_snapshot["included_commit"] == task_receipt["commit"]
        assert phase_snapshot["task_inputs"] == task_receipt["inputs"]
        assert phase_snapshot["check"] != terminal["binding"][-1]
        changed_snapshot = dict(phase_snapshot, task_inputs="inputs-B")
        assert changed_snapshot["task_inputs"] != task_receipt["inputs"]
        phase_coverage = {"subject": "phase", "contribution": digest(task_receipt),
                          "phase_witness": digest(phase_snapshot)}
        assert phase_coverage["contribution"] != phase_coverage["phase_witness"]
        history.append("phase_ready")
        assert history == list(route)


def check_identity():
    specification = {"id": "s-spec", "kind": "section", "document": "specification",
                     "code": "notes", "version": 1, "position": 1, "body": "Spec."}
    architecture = dict(specification, id="s-arch", document="architecture", body="Architecture.")
    instruction = dict(specification, id="s-rule", document="instructions", code="rule", position=0,
                       body="See the original [notes](legacy:rev-1/s-spec/1).")
    original = (specification, architecture, instruction)
    frozen = digest(original)
    historical = {("v1", "sample", "rev-1", item["id"], item["version"], digest(item)): item
                  for item in original}
    current = {
        "s-spec": ("b-spec", "block", "notes", 1),
        "s-arch": ("b-arch", "block", "architecture-notes", 1),
        "s-rule": ("i-rule", "instruction", "rule", 0),
    }
    assert specification["code"] == architecture["code"]
    assert len({(kind, code) for _, kind, code, _ in current.values()}) == len(current)
    for item in original:
        dest, kind, _, position = current[item["id"]]
        assert dest not in current and kind != item["kind"] and position == item["position"]
    ref = ("v1", "sample", "rev-1", "s-spec", 1, digest(specification))
    assert historical[ref] == specification
    assert instruction["body"].endswith("(legacy:rev-1/s-spec/1).")
    assert current[ref[3]][0] == "b-spec" and digest(original) == frozen


def check_delivered_coverage_renewal():
    task_a, task_b = ("task-A", 1), ("task-B", 1)
    plan = {"id": "plan-1", "revision": "rev-2", "mapping": {"criterion-p": [task_a, task_b]}}
    state_path = "docs/STATE.md"
    artifact = "generated/counter.json"
    state_a = "# State\nNext task: B\n"
    state_b = "# State\nNext task: none\n"
    generation_a, generation_b = "generation-A", "generation-B"
    snapshots = {
        "commit-A": {"src/counter.py": "counter-7", artifact: '{"count":7}', "checks/config": "config-1",
                     state_path: state_a},
        "commit-B": {"src/counter.py": "counter-7", artifact: '{"count":7}', "checks/config": "config-2",
                     state_path: state_b},
    }
    ancestors = {"commit-A": ("commit-A",), "commit-B": ("commit-A", "commit-B")}
    authority = "harness-state@2"
    generations = {
        generation_a: {"authority": authority, "commit": "commit-A", "path": state_path,
                       "output": digest(state_a)},
        generation_b: {"authority": authority, "commit": "commit-B", "path": state_path,
                       "output": digest(state_b)},
    }
    current_generations = {"commit-A": generation_a, "commit-B": generation_b}
    deliveries = {
        task_a: {"commit": "commit-A", "result": {"src/counter.py": "counter-7", artifact: '{"count":7}'},
                 "shared": generation_a},
        task_b: {"commit": "commit-B", "result": {"checks/config": "config-2"}, "shared": generation_b},
    }
    check_paths = {task_a: ("src/counter.py", "checks/config"), task_b: ("checks/config", state_path)}

    def generation_matches(generation_id, head, *, original=False):
        generation = generations.get(generation_id)
        if generation is None or generation["authority"] != authority or generation["path"] != state_path:
            return False
        observed = generation["commit"]
        return (observed in ancestors[head]
                and (not original or observed == head)
                and generation["output"] == digest(snapshots[observed].get(state_path))
                and generation["output"] == digest(snapshots[head].get(state_path)))

    def binding(task, head):
        return {
            "plan": digest(plan), "task": task, "contract": f"{task[0]}-contract@1",
            "coverage": f"{task[0]}-coverage@1", "head": head, "tree": digest(snapshots[head]),
            "delivery": digest(deliveries[task]), "check": "sample-check@1",
            "environment": "env-1", "authority": "epoch-1",
            "inputs": digest({path: snapshots[head][path] for path in check_paths[task]}),
            "generation": digest(generations.get(current_generations.get(head))),
        }

    originals = {
        task: {"binding": binding(task, receipt["commit"]), "status": "passed"}
        for task, receipt in deliveries.items()
    }
    frozen = digest([(task, originals[task], receipt) for task, receipt in deliveries.items()])
    renewals = []

    def delivery_status(task, head):
        receipt = deliveries[task]
        original = receipt["commit"]
        if (original not in ancestors[head]
                or not generation_matches(receipt["shared"], original, original=True)
                or not generation_matches(current_generations.get(head), head)
                or any(snapshots[original].get(path) != value for path, value in receipt["result"].items())):
            return "held"
        if any(snapshots[head].get(path) != value for path, value in receipt["result"].items()):
            return "delivery_required"
        return "verified"

    def contribution(task, head):
        status = delivery_status(task, head)
        if status != "verified":
            return status
        current = binding(task, head)
        original = originals[task]
        latest = next((record for record in reversed(renewals) if record["binding"] == current), None)
        if latest is not None:
            return "current" if (
                latest["status"] == "accepted" and latest["original_acceptance"] == digest(original)
            ) else "held"
        # Original coverage is portable to a descendant only with identical complete inputs.
        snapshot_fields = {"head", "tree", "generation"}
        original_inputs = {key: value for key, value in original["binding"].items()
                           if key not in snapshot_fields}
        current_inputs = {key: value for key, value in current.items() if key not in snapshot_fields}
        return "current" if original_inputs == current_inputs else "stale"

    def ready(head):
        phase_witness = {"check": "phase-check@1", "head": head, "status": "passed"}
        return phase_witness["status"] == "passed" and all(
            contribution(task, head) == "current" for task in plan["mapping"]["criterion-p"]
        )

    def start_renewal(task, head, confirmation):
        status = delivery_status(task, head)
        if status != "verified":
            return status
        preview = {"binding": binding(task, head), "original_acceptance": digest(originals[task])}
        if confirmation != digest(preview):
            return "refused"
        renewal = dict(preview, status="pending")
        renewals.append(renewal)
        return renewal

    def accept_renewal(record, head, validation, review, confirmation):
        task = record["binding"]["task"]
        sealed = {"binding": record["binding"], "original_acceptance": record["original_acceptance"],
                  "validation": digest(validation), "review": digest(review)}
        if (delivery_status(task, head) != "verified" or record["binding"] != binding(task, head)
                or validation != {"binding": record["binding"], "status": "passed"}
                or review != {"validation": digest(validation), "recommendation": "accept"}
                or confirmation != digest(sealed)):
            return "refused"
        renewals.append(dict(sealed, status="accepted"))
        return "accepted"

    assert contribution(task_a, "commit-A") == "current"
    assert generation_matches(generation_a, "commit-A")
    assert generation_matches(generation_b, "commit-B")
    assert not generation_matches(generation_a, "commit-B")
    assert contribution(task_a, "commit-B") == "stale"
    assert contribution(task_b, "commit-B") == "current"
    assert not ready("commit-B")
    preview = {"binding": binding(task_a, "commit-B"), "original_acceptance": digest(originals[task_a])}
    assert start_renewal(task_a, "commit-B", None) == "refused"
    renewal = start_renewal(task_a, "commit-B", digest(preview))
    assert not ready("commit-B")  # A queued renewal cannot make the old coverage current.
    validation = {"binding": preview["binding"], "status": "passed"}
    review = {"validation": digest(validation), "recommendation": "accept"}
    confirmation = digest(dict(preview, validation=digest(validation), review=digest(review)))
    assert accept_renewal(renewal, "commit-B", validation, review, None) == "refused"
    assert accept_renewal(renewal, "commit-A", validation, review, confirmation) == "refused"
    assert not ready("commit-B")
    assert accept_renewal(renewal, "commit-B", validation, review, confirmation) == "accepted"
    assert ready("commit-B")
    for generation_id in (generation_a, generation_b):
        proof = generations.pop(generation_id)
        assert start_renewal(task_a, "commit-B", digest(preview)) == "held"
        assert contribution(task_a, "commit-B") == "held"
        assert not ready("commit-B")
        generations[generation_id] = proof
    assert ready("commit-B")
    accepted = renewals[-1]
    assert renewal["status"] == "pending" and accepted["status"] == "accepted"
    assert accepted["binding"]["delivery"] == digest(deliveries[task_a])
    assert accepted["original_acceptance"] == digest(originals[task_a])
    assert len(deliveries) == 2
    assert digest([(task, originals[task], receipt) for task, receipt in deliveries.items()]) == frozen

    snapshots["commit-C"] = {**snapshots["commit-B"], artifact: '{"count":8}'}
    ancestors["commit-C"] = (*ancestors["commit-B"], "commit-C")
    current_generations["commit-C"] = generation_b
    assert start_renewal(task_a, "commit-C", digest(preview)) == "delivery_required"
    assert contribution(task_a, "commit-C") == "delivery_required"
    assert not ready("commit-C")

    # B reads STATE.md. A valid generation with no other changes still stales B's check.
    state_d = "# State\nReady for review\n"
    snapshots["commit-D"] = {**snapshots["commit-B"], state_path: state_d}
    ancestors["commit-D"] = (*ancestors["commit-B"], "commit-D")
    current_generations["commit-D"] = "generation-D"
    generations["generation-D"] = {"authority": authority, "commit": "commit-D", "path": state_path,
                                   "output": digest(state_d)}
    assert delivery_status(task_b, "commit-D") == "verified"
    assert contribution(task_b, "commit-D") == "stale"


def check_exchange():
    # One actual complete supplied view. The companion also has the six document views.
    supplied = b"# Sample rule\nKeep the review bounded.\n## Counter rule\nCheck the count.\n"
    root, child = (MEMBERS[key]["content"] for key in ("rule", "rule-scoped"))
    rendered = f"# {root['title']}\n{root['body']}\n## {child['title']}\n{child['body']}\n".encode()
    assert supplied == rendered
    assert sha256(supplied).hexdigest() == "e47c85c827e862878a1014f68c1672b8407cfe0f731af36a782abc3d30ace542"
    assert supplied[14:38] == root["body"].encode()
    assert supplied[55:71] == child["body"].encode()
    assert target("part_of", "rule-scoped") == "rule"
    assert MEMBERS["rule-hidden"]["content"]["export"] == "none"

    # Stage one field of an existing child. Architecture is omitted from the supplied files.
    local = {
        "local-child": {"version": 2, "scope": [{"type": "project"}]},
        "local-rule": {"version": 1, "body": "Existing parent."},
        "local-counter": {"version": 4, "body": "Existing component."},
        "local-hidden": {"version": 3, "body": "Existing hidden instruction."},
    }
    mapping = {"rule-scoped": ("local-child", 2), "component": ("local-counter", 4)}

    def stage_scope(maps):
        child_id, version = maps["rule-scoped"]
        assert local[child_id]["version"] == version
        scope = []
        for selector in child["scope"]:
            target_ref = maps.get(selector["id"])
            if target_ref is None:
                return "unresolved"
            local_id, expected_version = target_ref
            if local[local_id]["version"] != expected_version:
                return "stale"
            scope.append(dict(selector, id=local_id))
        return {**local, child_id: dict(local[child_id], scope=scope)}

    staged = stage_scope(mapping)
    assert staged["local-child"]["scope"] == [{"type": "component", "id": "local-counter"}]
    assert {key for key in local if local[key] != staged[key]} == {"local-child"}
    assert stage_scope({"rule-scoped": mapping["rule-scoped"]}) == "unresolved"
    assert stage_scope(dict(mapping, component=("local-counter", 3))) == "stale"

    # IDE changes grow the marked body without moving or editing its baseline frames.
    original = MEMBERS["purpose"]["content"]["body"].encode()
    end = b"\n<!-- harness:end 0 -->\n"
    body = b"Return **7 tokens**.\r\n"
    for title, offset in (("Specification", 119), ("Especificación", 121)):
        prefix = f"# {title}\n\n<a id=\"k-purpose\"></a>\n## purpose — Purpose\n**body**\n".encode()
        prefix += b"<!-- harness:field purpose /content/body 0 -->\n"
        assert len(prefix) == offset
        suffix = b"- status: active\n"
        assert (prefix + original + end + suffix)[offset:offset + 15] == original
        edited = prefix + body + end + suffix
        parsed, separator, tail = edited[len(prefix):].partition(end)
        assert (parsed, separator, tail) == (body, end, suffix)
        assert len(parsed) != len(original) and parsed.endswith(b"\r\n")


def check_manual():
    limits = {"path": "src/counter.py", "check": ("sample-check", ("python3", "checks/count.py"), 30)}
    base = {"format": "manual-execution-2", "path": limits["path"], "check": limits["check"]}

    def admit(request, confirmed):
        if confirmed is None:
            return "typed_source_missing"
        if request["path"] != confirmed["path"] or request["check"] != confirmed["check"]:
            return "outside_confirmed_limits"
        return ("admitted", "I02")

    assert admit(base, limits) == ("admitted", "I02")
    assert admit(base, None) == "typed_source_missing"
    assert admit(dict(base, path="docs/STATE.md"), limits) == "outside_confirmed_limits"
    assert admit(dict(base, check=("sample-check", ("python3", "other.py"), 30)), limits) == (
        "outside_confirmed_limits"
    )


def check_authoring():
    saved = {("purpose", "body"): "Return 7.", ("scope", "body"): "Counter only."}
    copy_hash = digest(sorted((list(key), value) for key, value in saved.items()))
    derived = [(key, saved[key]) for key in sorted(saved)]
    assert len(derived) == 2 and dict(derived) == saved
    injected = {"edits": derived[:1]}
    assert set(injected) == {"edits"}  # Stage has closed empty input.
    assert copy_hash != digest(sorted((list(key), value) for key, value in derived[:1]))


def check_recovery_fence():
    # Each transition models one serialized turn of the synthetic domain writer.
    generation = 1
    revision = 0
    journal = {}
    effects = []

    def envelope(key, preview):
        return {"command": "knowledge.adopt@2", "project": "sample", "key": key,
                "expected": {"head": "head-1", "draft": "draft-1", "copy": "copy-1",
                             "preview": preview},
                "input": {"reason": "Review the counter definitions.", "confirmed": True}}

    a = envelope("adopt-A", "preview-A")
    b = envelope("adopt-B", "preview-B")
    a_hash, b_hash = digest(a), digest(b)
    assert a_hash != b_hash and digest(dict(a, key=b["key"])) != a_hash

    def reserve(expected, command, request_digest):
        nonlocal revision
        key = command["key"]
        if digest(command) != request_digest:
            return "mismatch"
        if key in journal:
            return "replay" if journal[key]["digest"] == request_digest else "mismatch"
        if expected != generation:
            return "stale"
        if any(row["status"] == "reserved" for row in journal.values()):
            return "busy"
        journal[key] = {"key": key, "digest": request_digest, "generation": generation,
                        "status": "reserved"}
        revision += 1
        return "reserved"

    def dispatch(command, request_digest):
        nonlocal revision
        key = command["key"]
        if (digest(command) != request_digest or key not in journal
                or journal[key]["digest"] != request_digest):
            return "refused"
        if journal[key]["status"] == "reserved":
            effects.append(key)
            journal[key]["status"] = "settled"
            journal[key]["outcome"] = digest({"command": request_digest, "adopted": "head-2"})
            revision += 1
        return journal[key]["status"]

    def recover():
        rows = [dict(journal[key]) for key in sorted(journal)]
        return rows, (generation, revision, digest(rows))

    def fence(observed):
        nonlocal generation, revision
        if observed != recover()[1]:
            return "view_changed"
        if any(row["status"] == "reserved" for row in journal.values()):
            return "busy"
        generation += 1
        revision += 1
        return generation

    def cancel(command):
        nonlocal revision
        row = journal[command["key"]]
        assert row["status"] == "reserved" and row["digest"] == digest(command)
        row["status"] = "cancelled"
        revision += 1

    empty, b_observed = recover()
    assert empty == []
    assert reserve(1, a, a_hash) == "reserved"
    assert reserve(1, b, a_hash) == "mismatch"
    assert reserve(1, b, b_hash) == "busy"
    assert fence(recover()[1]) == "busy"
    assert dispatch(a, a_hash) == "settled"  # A loses the reply.
    assert generation == 1 and all(row["status"] != "reserved" for row in journal.values())
    assert fence(b_observed) == "view_changed"  # The empty view cannot enable fresh consent.
    assert generation == 1
    presented, b_observed = recover()
    recovered, = presented
    assert (recovered["key"], recovered["digest"], recovered["status"], recovered["outcome"]) == (
        a["key"], a_hash, "settled", digest({"command": a_hash, "adopted": "head-2"}))
    assert dispatch(a, recovered["digest"]) == "settled"  # Exact replay after losing identity.
    assert effects == ["adopt-A"]
    assert fence(b_observed) == 2  # B explicitly confirms the view that includes A's result.
    assert recover()[0] == presented  # A's result remains discoverable after the fence.

    # Separate ordering: A's reserve is still in transit when B fences an empty view.
    generation, revision = 1, 0
    journal.clear()
    effects.clear()
    empty, b_observed = recover()
    assert empty == [] and fence(b_observed) == 2
    assert reserve(1, a, a_hash) == "stale"
    assert dispatch(a, a_hash) == "refused"
    assert reserve(2, b, b_hash) == "reserved"
    cancel(b)
    assert dispatch(b, b_hash) == "cancelled"
    assert effects == []


if __name__ == "__main__":
    check_fixture()
    for check in (check_coverage, check_delivered_coverage_renewal, check_identity, check_exchange,
                  check_manual, check_authoring, check_recovery_fence):
        check()
        print(f"{check.__name__}: passed")
