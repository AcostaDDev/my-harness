"""T015 managed phase job consumer: canonical context and accounted, versioned invocation boundary."""
from dataclasses import replace

from my_harness.core.engine.contracts import freeze, Selection, invoke_agent, stop_history, ContractError
from my_harness.core.engine.phases import check_phase
from my_harness.core.engine.prompts import render_attempt, dump_catalog
from my_harness.core.engine.judge import input_check
from my_harness.storage.frozen_context import ContextRepository
from my_harness.i18n import tr


def execute(managed, context, history, snapshot, agents, commands, git, journal, catalog, versions, language):
    domain = snapshot['structured']['domain']
    client = versions.get('reviewer_provider', 'codex')
    def canonical():
        contexts = ContextRepository(managed.engine)
        phase_id = next(m['item_id'] for m in domain['members'] if m['kind'] == 'phase' and m['code'] == snapshot['definition']['code'])
        selected = {phase_id, *[l['source'] for l in domain['links']
                              if l['target'] == phase_id and l['kind'] in ('part_of', 'criterion_of')]}
        selected.update(l['source'] for l in domain['links'] if l['kind'] == 'criterion_of' and l['target'] in selected)
        ident = contexts.prepare_for(context, sorted(selected), client=client, revision=domain['revision']['number'])
        return contexts.snapshot(domain['source_project_id'], ident)
    if snapshot['kind'] != 'plan':
        history, outcome = check_phase(context, history, snapshot, agents, commands, git, journal, catalog, language,
                                       canonical=canonical)
        outcome['reviewer'].update(provider=versions.get('reviewer_provider'), cli=versions.get('reviewer_cli'))
        if outcome['verdict'] == 'BLOCKED' and (outcome.get('result') or {}).get('blocked_classification') == 'planning_ambiguity':
            candidate = {'classification': 'planning_ambiguity', 'blocked_evidence': freeze(outcome['reasons']) or 'Blocked',
                         'intent_id': snapshot['operation_id']}
            input_check('blocked_check', candidate)
            outcome['judge_input'] = candidate
        return history, outcome
    def result(verdict, reasons=(), data=None):
        return replace(history, status='completed'), {'verdict': verdict, 'reasons': list(reasons), 'result': data}
    try:
        evidence = git.capture(context)
        if evidence.changed_paths or snapshot['plan_request']['knowledge'] != snapshot['knowledge']:
            return result('FAILED', [tr('phases.structured_refused', reason='planning_inputs_changed')])
        planning_inputs = {key: snapshot[key] for key in ('operation_id', 'knowledge', 'tasks',
            'task_evidence', 'open_questions', 'answered_questions')}
        planning_inputs['previous_adopted_plan'] = snapshot['definition']
        prompt, rendered = render_attempt(catalog, 'structured-phase-plan', {'CONTEXT_JSON': freeze(planning_inputs)},
                                          context, language, canonical=canonical())
        history = replace(history, prompt_catalog_json=dump_catalog(catalog))
        history, data = invoke_agent(context, history, agents, 'planning',
            Selection(context.policy.reviewer_model, context.policy.reviewer_effort, 'Independent phase planning'),
            prompt, journal, prompt_snapshot_json=rendered)
        if data is None:
            return result('FAILED', [history.stop.reason])
        from my_harness.core.engine.intake import validate_phase_plan
        from my_harness.core.engine.domain_catalogue import SchemaError
        try:
            validated = validate_phase_plan(data)
        except SchemaError as exc:
            raise ContractError(tr('phases.structured_refused', reason='invalid_phase_plan_output')) from exc
        if git.capture(context) != evidence:
            return result('FAILED', [tr('phases.structured_refused', reason='planning_code_changed')])
        return result('PROPOSED', data=validated)
    except (ValueError, ContractError) as exc:
        history = stop_history(history, 'phase', str(exc))
        return result('FAILED', [str(exc)])
