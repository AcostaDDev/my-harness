"""Pure valuation-1 calculator. No adapter, database, network, clock or file reads.

Inputs are JSON values, not metrics-1 floats or CLI streams. Components are a caller-established
single view or disjoint model/request partition; capture reconciliation belongs to T003.
See docs/phase/P001-T002-reference-calculator.md for the versioned input contract.
"""

from decimal import Decimal, DecimalException, Inexact, Rounded, ROUND_HALF_EVEN, localcontext

from my_harness.core.engine.metric_references import (DECIMAL, DIGEST, ReferenceError, decimal_value,
                                                     digest, make_bundle, timestamp)

CALCULATOR = 'valuation-1'
NORMALIZATION = 'usage-accounting-1'
QUANTUM = Decimal('0.000000000001')
REASONS = frozenset('usage_missing terminal_missing partial_capture capture_unavailable model_unreported '
                    'model_partition_unknown model_partition_conflict delegation_boundary_unknown billing_profile_unknown '
                    'scheme_unsupported reference_missing reference_conflict effective_period_unknown reference_out_of_period '
                    'cache_lifetime_unknown cache_write_semantics_unknown request_tier_unknown speed_unknown geography_unknown '
                    'tool_charge_unknown unsupported_modifier invalid_quantity invalid_rate inconsistent_usage legacy_evidence'.split())
UNSUPPORTED = {'scheme_unsupported', 'unsupported_modifier', 'cache_write_semantics_unknown',
               'invalid_quantity', 'invalid_rate', 'inconsistent_usage', 'reference_conflict'}


class CalculationError(ValueError):
    def __init__(self, reason):
        self.reason = reason


def _fail(reason):
    raise CalculationError(reason)


def _quantity(value):
    if value is None:
        _fail('usage_missing')
    if type(value) is not int or not 0 <= value <= 2**63-1:
        _fail('invalid_quantity')
    return value


def _amount(value):
    return format(value, 'f')


def normalize(component):
    """Disjoint quantities only; Responses API evidence is never a Codex CLI contract."""
    semantics = component.get('semantics')
    if semantics not in ('claude-cli-1', 'codex-cli-1', 'responses-api-1'):
        _fail('cache_write_semantics_unknown')
    raw, read, output = (_quantity(component.get(k)) for k in ('input_tokens', 'cache_read_tokens', 'output_tokens'))
    write = _quantity(component.get('cache_write_tokens'))
    reasoning = component.get('reasoning_tokens')
    if reasoning is not None and _quantity(reasoning) > output:
        _fail('inconsistent_usage')
    quantities = {'uncached_input': raw, 'cache_read': read, 'output': output}
    if semantics == 'codex-cli-1':
        if write:
            _fail('cache_write_semantics_unknown')
        if any(component.get(k) not in (None, 0) or type(component.get(k)) is bool
               for k in ('write_5m', 'write_1h', 'write_30m', 'write_12h')):
            _fail('inconsistent_usage')
        if read > raw:
            _fail('inconsistent_usage')
        quantities['uncached_input'] = raw - read
    else:
        lifetimes = ('write_5m', 'write_1h') if semantics == 'claude-cli-1' else ('write_30m', 'write_12h')
        other = {'write_5m', 'write_1h', 'write_30m', 'write_12h'} - set(lifetimes)
        if any(component.get(k) not in (None, 0) or type(component.get(k)) is bool for k in other):
            _fail('inconsistent_usage')
        # An explicitly observed zero aggregate establishes that both write categories are zero.
        if write and any(component.get(k) is None for k in lifetimes):
            _fail('cache_lifetime_unknown')
        for key in lifetimes:
            quantities[key] = _quantity(component.get(key, 0) if component.get(key) is not None else 0)
        if sum(quantities[k] for k in lifetimes) != write:
            _fail('inconsistent_usage')
        if semantics == 'responses-api-1':
            if read + write > raw:
                _fail('inconsistent_usage')
            quantities['uncached_input'] = raw - read - write
    return quantities


def _period(document, scenario, reasons, warnings):
    at = timestamp(scenario['at'])
    start, end = document['effective_from'], document['effective_to']
    if ((start is not None and at < timestamp(start)) or (end is not None and at >= timestamp(end))):
        reasons.add('reference_out_of_period')
        return False
    if document['effective_period_unknown']:
        if scenario.get('retrospective') is True:
            warnings.add('effective_period_unknown')
        else:
            reasons.add('effective_period_unknown')
    return True


def _find(bundle, kind, model, scenario, reasons, warnings, *, quantity_basis=None):
    matches = []
    for ref in bundle.references:
        doc = ref.document()
        if doc['kind'] != kind or doc['model'] != model:
            continue
        if any(doc[k] != scenario.get(k) for k in ('provider', 'platform', 'product')):
            continue
        if kind == 'tariff' and (doc['scheme'] != scenario.get('scheme') or doc['unit'] != scenario.get('unit')
                                or scenario.get('basis') not in doc['bases'] or doc['quantity_basis'] != quantity_basis):
            continue
        matches.append((ref, doc))
    valid = []
    for ref, doc in matches:
        local_reasons, local_warnings = set(), set()
        if _period(doc, scenario, local_reasons, local_warnings):
            valid.append((ref, doc, local_reasons, local_warnings))
    if len(valid) > 1:
        reasons.add('reference_conflict')
        return None
    if not valid:
        reasons.add('reference_out_of_period' if matches else 'reference_missing')
        return None
    ref, doc, local_reasons, local_warnings = valid[0]
    reasons.update(local_reasons)
    warnings.update(local_warnings)
    return ref, doc


def _conditions(scenario):
    conditions = scenario.get('conditions')
    if type(conditions) is not dict:
        return {}
    for key, value in conditions.items():
        if value is None:
            continue
        if (type(value) is not dict or set(value) != {'value', 'provenance', 'source'}
                or value['provenance'] not in ('reported', 'asserted')
                or not isinstance(value['source'], str) or not value['source'].strip()
                or not isinstance(value['value'], str) or not value['value'].strip()):
            _fail('unsupported_modifier')
    return {key: value['value'] for key, value in conditions.items() if value is not None and value['value'] != 'unknown'}


def _case(document, conditions, component, quantities, reasons):
    missing = set(document['required_conditions']) - conditions.keys()
    if missing:
        reasons.update({'speed': 'speed_unknown', 'geography': 'geography_unknown'}.get(k, 'unsupported_modifier') for k in missing)
        return None
    # Extra declared conditions cannot be silently ignored by this tariff.
    if conditions.keys() - set(document['required_conditions']):
        reasons.add('unsupported_modifier')
        return None
    cases = [c for c in document['cases'] if c['conditions'] == conditions]
    if not cases:
        reasons.add('unsupported_modifier')
        return None
    tiered = any(c['prompt_from'] != 0 or c['prompt_to'] is not None for c in cases)
    if tiered:
        # Invocation/model sums cannot select a per-request threshold, even below it.
        if component.get('grain') != 'request' or component.get('coverage') != 'complete':
            reasons.add('request_tier_unknown')
            return None
        prompt = sum(value for key, value in quantities.items() if key != 'output')
        cases = [c for c in cases if c['prompt_from'] <= prompt and (c['prompt_to'] is None or prompt <= c['prompt_to'])]
    if len(cases) != 1:
        reasons.add('reference_conflict' if cases else 'request_tier_unknown')
        return None
    return cases[0]


def _lines(component_key, quantities, case, ref, identity_id, reasons):
    lines = []
    for category, quantity in sorted(quantities.items()):
        rate = case['rates'].get(category)
        if rate is None or rate['amount'] is None:
            if quantity:
                reasons.add('reference_missing')
            continue
        factors = [f for f in case['factors'] if category in f['categories']]
        exact = Decimal(quantity) * decimal_value(rate['amount']) / Decimal(rate['quantity'])
        for factor in factors:
            exact *= decimal_value(factor['value'], factor=True)
        lines.append({'component': component_key, 'category': category, 'quantity': quantity,
                      'rate': rate, 'factors': factors, 'included_adjustments': case['included_adjustments'],
                      'tariff_reference': ref.id, 'identity_reference': identity_id, 'rate_case': case['key'],
                      'exact_amount': _amount(exact)})
    return lines


def calculate(evidence, scenario, bundle):
    """Return JSON-safe evidence and decimal strings; no mutation of any supplied value.

    Missing evidence produces reasons. Malformed references are unsupported. A partial subtotal
    can be retained, but amount is null unless the entire declared invocation scope is covered.
    """
    reasons, warnings, lines, selections = set(), set(), [], []
    result = {'format': CALCULATOR, 'normalization': NORMALIZATION, 'status': 'incomplete', 'amount': None,
              'known_subtotal': None, 'exact_sum': None, 'rounding_adjustment': None, 'lines': lines,
              'selected_components': selections, 'reasons': [], 'warnings': [], 'unit': scenario.get('unit'),
              'basis': scenario.get('basis'), 'scheme': scenario.get('scheme'),
              'counterfactual': scenario.get('basis') == 'subscription_equivalent',
              'retrospective': scenario.get('retrospective') is True}
    try:
        # Bind inputs before interpretation; reject floats instead of hashing their approximation.
        try:
            result['evidence_digest'] = digest(evidence)
        except ReferenceError:
            _fail('invalid_quantity')
        result['profile_digest'] = digest(scenario)
        bundle = make_bundle(bundle.references)
        result['reference_set_digest'] = bundle.id
        if evidence.get('format') != NORMALIZATION:
            _fail('legacy_evidence')
        evidence_reasons = evidence.get('reasons', [])
        if type(evidence_reasons) is not list or any(type(r) is not str or r not in REASONS for r in evidence_reasons):
            _fail('usage_missing')
        reasons.update(evidence_reasons)
        if scenario.get('format') != 'valuation-scenario-1':
            _fail('billing_profile_unknown')
        if type(scenario.get('retrospective')) is not bool:
            _fail('billing_profile_unknown')
        if not all(isinstance(scenario.get(k), str) and scenario[k] for k in ('provider', 'platform', 'product', 'scheme', 'unit', 'basis')):
            _fail('billing_profile_unknown')
        if scenario['basis'] not in ('api_usd', 'enterprise_usd', 'token_credit', 'subscription_equivalent'):
            _fail('scheme_unsupported')
        if not any(r.document().get('scheme') == scenario['scheme'] and scenario['basis'] in r.document().get('bases', [])
                   and r.document().get('unit') == scenario['unit'] for r in bundle.references):
            _fail('scheme_unsupported')
        timestamp(scenario['at'])
        conditions = _conditions(scenario)
        if scenario.get('extra_factors'):
            _fail('unsupported_modifier')  # Rate overrides require a new sourced reference, never ad hoc multiplication.
        components = evidence.get('components')
        if not isinstance(components, list) or not components:
            _fail('usage_missing')
        if evidence.get('coverage') not in ('complete', 'partial', 'absent'):
            _fail('usage_missing')
        if evidence['coverage'] != 'complete':
            reasons.add('partial_capture' if evidence['coverage'] == 'partial' else 'usage_missing')
        partition = evidence.get('partition')
        if partition not in ('single', 'disjoint') or (partition == 'single' and len(components) != 1):
            _fail('model_partition_unknown')
        keys = [c.get('key') for c in components]
        if any(type(k) is not str or not k for k in keys) or len(set(keys)) != len(keys):
            _fail('model_partition_conflict')
        grains = {c.get('grain') for c in components}
        if not grains <= {'invocation_total', 'model_total', 'request'} or len(grains) != 1:
            _fail('model_partition_conflict')
        if len(components) > 1 and 'invocation_total' in grains:
            _fail('model_partition_conflict')
        if 'model_total' in grains and len({c.get('reported_model') for c in components}) != len(components):
            _fail('model_partition_conflict')
        if any(c.get('parent_key') in keys or set(c.get('includes', [])) & set(keys) for c in components):
            _fail('model_partition_conflict')
        if evidence.get('delegation') not in ('none', 'disjoint', 'included'):
            reasons.add('delegation_boundary_unknown')
        if evidence.get('charges_complete') is not True:
            reasons.add('tool_charge_unknown')
        with localcontext() as ctx:
            ctx.prec = 160
            ctx.traps[Inexact] = ctx.traps[Rounded] = True
            for component in components:
                try:
                    if component.get('coverage') != 'complete':
                        reasons.add('partial_capture' if component.get('coverage') == 'partial' else 'usage_missing')
                    quantities = normalize(component)
                    selections.append({'key': component['key'], 'quantities': quantities,
                                       'semantics': component['semantics'], 'reported_model': component.get('reported_model'),
                                       'model_source': component.get('model_source')})
                    model = component.get('reported_model')
                    if not model or component.get('model_source') not in ('response', 'model_usage'):
                        _fail('model_unreported')
                    identity = _find(bundle, 'model_identity', model, scenario, reasons, warnings)
                    if identity is None:
                        continue
                    identity_ref, identity_doc = identity
                    tariff = _find(bundle, 'tariff', identity_doc['canonical_model'], scenario, reasons, warnings,
                                   quantity_basis='disjoint_tokens')
                    if tariff is None:
                        continue
                    ref, doc = tariff
                    if component['semantics'] not in doc['semantics']:
                        _fail('cache_write_semantics_unknown')
                    case = _case(doc, conditions, component, quantities, reasons)
                    if case:
                        lines.extend(_lines(component['key'], quantities, case, ref, identity_ref.id, reasons))
                except CalculationError as exc:
                    reasons.add(exc.reason)
            charges = evidence.get('charges', [])
            if type(charges) is not list:
                _fail('tool_charge_unknown')
            charge_keys = [charge.get('key') for charge in charges]
            if (any(type(key) is not str or not key for key in charge_keys)
                    or len(set(charge_keys)) != len(charge_keys) or set(charge_keys) & set(keys)):
                _fail('model_partition_conflict')
            for charge in charges:
                try:
                    if charge.get('provenance') not in ('reported_billable', 'asserted_billable') or not charge.get('source'):
                        _fail('tool_charge_unknown')
                    quantity = _quantity(charge.get('quantity'))
                    ref = bundle.get(charge.get('tariff_reference'))
                    if ref is None:
                        _fail('reference_missing')
                    doc = ref.document()
                    if (doc['kind'] != 'tariff' or doc['quantity_basis'] != 'charged_tool'
                            or any(doc[k] != scenario[k] for k in ('provider', 'platform', 'product', 'scheme', 'unit'))
                            or scenario['basis'] not in doc['bases']):
                        _fail('scheme_unsupported')
                    if not _period(doc, scenario, reasons, warnings):
                        continue
                    case = _case(doc, _conditions({'conditions': charge.get('conditions')}), {}, {}, reasons)
                    if case:
                        lines.extend(_lines(charge['key'], {charge['category']: quantity}, case, ref, None, reasons))
                except CalculationError as exc:
                    reasons.add(exc.reason)
            if lines:
                exact = sum((Decimal(line['exact_amount']) for line in lines), Decimal(0))
                ctx.traps[Inexact] = ctx.traps[Rounded] = False
                rounded = exact.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
                ctx.traps[Inexact] = ctx.traps[Rounded] = True
                result.update(exact_sum=_amount(exact), known_subtotal=_amount(rounded),
                              rounding_adjustment=_amount(rounded - exact))
    except (ReferenceError, CalculationError) as exc:
        reasons.add(exc.reason)
    except (KeyError, TypeError, AttributeError):
        reasons.add('usage_missing')
    if not lines and not reasons:
        reasons.add('reference_missing')
    result['reasons'], result['warnings'] = sorted(reasons), sorted(warnings)
    result['status'] = 'unsupported' if reasons & UNSUPPORTED else 'incomplete' if reasons or not lines else 'complete'
    if result['status'] == 'complete':
        result['amount'] = result['known_subtotal']
    return result


def compare_estimate(valuation, estimate):
    """Descriptive signed delta only for exactly equal comparison scopes/bases/conditions.

    The caller supplies the same comparison_key (a digest of scope/model partition/conditions)
    for each amount. Decimal spelling is never treated as evidence of provider precision.
    """
    base = {'status': 'not_comparable', 'delta': None, 'tolerance': None, 'within_precision': None, 'reasons': []}
    dimensions = ('unit', 'basis', 'scheme', 'comparison_key')
    if (valuation.get('status') != 'complete' or valuation.get('amount') is None
            or any(not valuation.get(k) or valuation.get(k) != estimate.get(k) for k in dimensions)
            or not DIGEST.fullmatch(str(valuation.get('comparison_key', '')))):
        return {**base, 'reasons': ['comparison_basis_unknown_or_different']}
    if estimate.get('legacy_float'):
        return {**base, 'reasons': ['legacy_float']}
    try:
        with localcontext() as ctx:
            ctx.prec = 160
            ctx.traps[Inexact] = ctx.traps[Rounded] = True
            # Amounts may exceed an individual rate's bound, but retain the same plain decimal grammar.
            reported = estimate['amount']
            if type(reported) is not str or len(reported) > 160:
                raise ValueError
            if not DECIMAL.fullmatch(reported):
                raise ValueError
            delta = Decimal(valuation['amount']) - Decimal(reported)
            base.update(status='precision_unknown', delta=_amount(delta))
            quantum = estimate.get('rounding_quantum')
            if quantum is not None and estimate.get('rounding_source'):
                quantum = decimal_value(quantum)
                if quantum <= 0:
                    raise ValueError
                tolerance = quantum / 2 + QUANTUM / 2
                base.update(status='compared', tolerance=_amount(tolerance), within_precision=abs(delta) <= tolerance)
            return base
    except (ValueError, KeyError, DecimalException):
        return {**base, 'status': 'not_comparable', 'reasons': ['reporting_precision_invalid']}
