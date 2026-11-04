"""P002-T016 (D300): consumer of `roadmap_review` jobs. Canonical frozen context, the versioned `roadmap-readiness`
or `roadmap-task-plan` template, one accounted reviewer invocation through the existing supervisor and ledger, and
harness validation of the output. The model proposes; nothing here adopts, grants or seals authority."""
from dataclasses import replace

from my_harness.core.engine import autonomy
from my_harness.core.engine.contracts import ContractError, Selection, freeze, invoke_agent, stop_history
from my_harness.core.engine.prompts import dump_catalog, render_attempt
from my_harness.services.knowledge_exchange import PhaseKnowledge
from my_harness.storage.frozen_context import ContextRepository
from my_harness.i18n import tr
from sqlalchemy.orm import Session

TEMPLATES = {'readiness': 'roadmap-readiness', 'task_plan': 'roadmap-task-plan'}


def _failed(history, reason):
    return stop_history(history, 'autonomy', reason), {'status': 'FAILED', 'result': None, 'reason': reason}


def execute(managed, context, history, request, agents, evidence, journal, catalog, versions, language):
    kind = request['kind']
    journal.checkpoint(history, 'autonomy')
    with Session(managed.engine) as session:
        revision = PhaseKnowledge.accepted(session, context.root)
    frozen = request['revision']
    if revision is None or revision.id != frozen['id'] or revision.revision_sha256 != frozen['sha256']:
        return _failed(history, tr('autonomy.refused', reason='revision_changed'))
    items = [i for i in request['item_ids'] if i in revision.members]
    if len(items) != len(request['item_ids']):
        return _failed(history, tr('autonomy.refused', reason='revision_changed'))
    contexts = ContextRepository(managed.engine)
    client = versions.get('reviewer_provider', 'codex')
    ident = contexts.prepare_for(context, sorted(items), client=client, revision=revision.number)
    canonical = contexts.snapshot(revision.project_id, ident)
    inputs = {'revision': revision.number, 'item_ids': sorted(items), **request.get('inputs', {})}
    before = evidence.capture(context)
    prompt, rendered = render_attempt(catalog, TEMPLATES[kind], {'CONTEXT_JSON': freeze(inputs)}, context, language,
                                      canonical=canonical)
    history = replace(history, prompt_catalog_json=dump_catalog(catalog))
    history, data = invoke_agent(context, history, agents, 'planning',
                                 Selection(context.policy.reviewer_model, context.policy.reviewer_effort,
                                           'Autonomous roadmap review'), prompt, journal, prompt_snapshot_json=rendered)
    if data is None:
        return _failed(history, history.stop.reason if history.stop else 'invocation_failed')
    if evidence.capture(context) != before:
        return _failed(history, tr('autonomy.refused', reason='checkout_changed'))
    done = replace(history, status='completed', stop=None)
    if kind == 'readiness':
        try:
            return done, {'status': 'REPORTED', 'result': autonomy.validate_gap_report(data), 'reason': None}
        except autonomy.AutonomyRefusal as error:
            return done, {'status': 'MALFORMED', 'result': None, 'reason': error.code}
    result = task_contract(context, request, data)
    return done, result


def task_contract(context, request, data):
    """D301: validate a delegated task contract proposal against accepted content, the repository and the project
    profile, render it, and require T014's deterministic parser to reproduce every executed field exactly."""
    import json
    import shlex
    from my_harness.core.engine import permission_targets as targets
    from my_harness.core.engine.contracts import harness_owned_paths
    from my_harness.core.engine.planning import deterministic_task
    executor = (context.policy.executor_models[0], context.policy.executor_efforts[0])
    try:
        owned = harness_owned_paths(context, {'forbidden_paths': []}, request['task_id'])['forbidden_paths']
        contract = autonomy.validate_task_plan(data, task_id=request['task_id'], criteria=request['criteria'],
                                               objective=request.get('objective'),
                                               protected=(*context.profile.protected_paths, *owned))
        for path in contract['allowed_paths']:
            target = context.root / path
            if targets.path(path, str(context.root)) != path or target.is_dir() or (
                    target.exists() and not target.is_file()):
                raise autonomy.AutonomyRefusal('task_plan_paths_invalid')
        prefixes = [tuple(p) for p in context.profile.allowed_command_prefixes]
        for command in contract['validation_commands']:
            argv = tuple(shlex.split(command))
            if not argv or not any(argv[:len(p)] == p for p in prefixes):
                raise autonomy.AutonomyRefusal('task_plan_command_outside_profile')
        text = autonomy.render_task_plan(contract, title=request['title'], phase=request['phase_id'],
                                         executor=executor)
        parsed = json.loads(deterministic_task(context, request['task_id'], request['phase_id'], text))
        autonomy.compare_parsed_contract(parsed, contract, phase=request['phase_id'], title=request['title'],
                                         executor=executor)
    except (autonomy.AutonomyRefusal, ContractError, ValueError) as error:
        return {'status': 'REFUSED', 'result': None, 'reason': getattr(error, 'code', str(error))[:200]}
    return {'status': 'PROPOSED', 'result': contract, 'plan_text': text,
            'contract_sha256': autonomy.digest(parsed), 'reason': None}
