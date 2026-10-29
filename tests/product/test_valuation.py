"""T002: pinned public observations and synthetic usage/terms, entirely offline."""

from copy import deepcopy
from decimal import Decimal, getcontext
from hashlib import sha256
import json
from pathlib import Path

import pytest

from my_harness.core.engine.metric_references import (
    Reference, ReferenceBundle, ReferenceError, canonical, digest, load_bundle, load_packaged_bundle,
    make_bundle, seal_reference,
)
from my_harness.core.engine.valuation import calculate, compare_estimate, normalize


@pytest.fixture
def bundle():
    return load_packaged_bundle()


def component(model='claude-sonnet-5-5', **changes):
    return dict(dict(key='terminal', grain='invocation_total', reported_model=model, model_source='model_usage',
                semantics='claude-cli-1', coverage='complete', input_tokens=100000, cache_read_tokens=900000,
                cache_write_tokens=20000, write_5m=20000, write_1h=0, output_tokens=10000), **changes)


def changed_component(model='claude-sonnet-5-5', **changes):
    return {**component(model), **changes}


def codex(**changes):
    return changed_component('gpt-6.1-sol', semantics='codex-cli-1', input_tokens=1000000,
                             cache_write_tokens=0, write_5m=0, **changes)


def evidence(*components, **changes):
    return dict(format='usage-accounting-1', components=list(components or [component()]),
                coverage='complete', partition='single' if len(components) <= 1 else 'disjoint',
                delegation='none', charges_complete=True, charges=[], **changes)


def scenario(kind='claude', **changes):
    result = dict(format='valuation-scenario-1', at='2026-10-27T22:00:00Z', retrospective=True,
                  provider='claude', platform='anthropic_first_party', product='claude_api',
                  scheme='anthropic_api_usd', unit='USD', basis='api_usd',
                  conditions={k: dict(value=v, provenance='asserted', source='synthetic scenario terms')
                              for k, v in dict(speed='standard', geography='global').items()})
    if kind in ('credit', 'enterprise', 'api'):
        result.update(provider='codex', platform='openai_first_party', product={
            'credit': 'work_codex', 'enterprise': 'enterprise_codex', 'api': 'openai_api'}[kind],
            scheme={'credit': 'chatgpt_work_codex_credit', 'enterprise': 'chatgpt_enterprise_usd', 'api': 'openai_api_usd'}[kind],
            basis={'credit': 'token_credit', 'enterprise': 'enterprise_usd', 'api': 'api_usd'}[kind])
        if kind == 'credit':
            result['unit'] = 'chatgpt_work_codex_credit'
        if kind != 'api':
            result['conditions']['eligibility'] = dict(value='scheme_eligible', provenance='asserted', source='synthetic eligibility')
        if kind == 'enterprise':
            result['conditions']['agreement'] = dict(value='published_terms', provenance='asserted', source='synthetic agreement')
    result.update(changes)
    return result


def set_condition(profile, key, value):
    result = deepcopy(profile)
    result['conditions'][key] = dict(value=value, provenance='asserted', source='synthetic terms')
    return result


def assert_amount(result, amount):
    assert result['status'] == 'complete', result
    assert result['reasons'] == []
    assert Decimal(result['amount']) == Decimal(amount)
    assert result['amount'] == result['known_subtotal']


def selected_ref(bundle, kind='tariff', model='claude-sonnet-5-5', product='claude_api'):
    return next(r for r in bundle.references if r.document()['kind'] == kind and r.document()['model'] == model
                and r.document()['product'] == product)


def replace_reference(bundle, old, document):
    new = seal_reference(document)
    return make_bundle([r for r in bundle.references if r != old] + [new]), new


def test_seed_pins_immutable_research_and_all_suggestions(bundle):
    root = Path(__file__).resolve().parents[2]
    raw = (root / 'docs/archive/phase-001/P001-T001-reference-observations.json').read_bytes()
    assert sha256(raw).hexdigest() == '2e7e88f759e206f40ceb641668d104fbe788fae37e75ecb117de6f71e790baf8'
    assert bundle.id == '41d20094709ebe26c0ff5787d4de00f573f27e2e2ffabd26c5279ca688fdd5bc'
    assert len(bundle.references) == 38
    observations = json.loads(raw)
    ids = {model for row in observations['sources'] for model in row.get('exact_ids', [])}
    assert {r.document()['model'] for r in bundle.references} == ids
    for ref in bundle.references:
        doc = ref.document()
        assert doc['effective_period_unknown'] and doc['effective_from'] is doc['effective_to'] is None
        assert all(s['evidence_digest'] == sha256(raw).hexdigest() for s in doc['sources'])
        if doc['kind'] == 'tariff':
            assert any(other.document()['kind'] == 'model_identity' and all(other.document()[k] == doc[k]
                       for k in ('model', 'provider', 'platform', 'product')) for other in bundle.references)


@pytest.mark.parametrize('write_5m,write_1h,expected', [(20000, 0, '.44'), (0, 20000, '.47'), (10000, 10000, '.455')])
def test_a01_a02_disjoint_claude_lines(bundle, write_5m, write_1h, expected):
    result = calculate(evidence(changed_component(write_5m=write_5m, write_1h=write_1h)), scenario(), bundle)
    assert_amount(result, expected)
    assert len(result['lines']) == 5
    assert {l['category'] for l in result['lines']} == {'uncached_input', 'cache_read', 'write_5m', 'write_1h', 'output'}
    assert result['selected_components'][0]['quantities']['uncached_input'] == 100000
    assert result['warnings'] == ['effective_period_unknown']


def test_a03_no_write_lifetime_fallback(bundle):
    result = calculate(evidence(changed_component(write_5m=None, write_1h=None)), scenario(), bundle)
    assert result['status'] == 'incomplete' and result['amount'] is None
    assert 'cache_lifetime_unknown' in result['reasons']


def test_a04_codex_reads_are_inside_input(bundle):
    result = calculate(evidence(codex()), scenario('credit'), bundle)
    assert_amount(result, '9.75')
    assert result['selected_components'][0]['quantities'] == dict(uncached_input=100000, cache_read=900000, output=10000)
    assert len(result['lines']) == 3


@pytest.mark.parametrize('speed,expected', [('standard', '9.75'), ('fast', '19.5'), ('ultrafast', '58.5')])
def test_a05_credit_speed_requires_eligibility(bundle, speed, expected):
    profile = set_condition(scenario('credit'), 'speed', speed)
    if speed == 'ultrafast':
        bad = calculate(evidence(codex()), profile, bundle)
        assert bad['amount'] is None and 'unsupported_modifier' in bad['reasons']
        profile = set_condition(profile, 'eligibility', 'ultrafast_eligible')
    assert_amount(calculate(evidence(codex()), profile, bundle), expected)


@pytest.mark.parametrize('model,source,reason', [(None, 'response', 'model_unreported'),
                                               ('gpt-6.1-sol', 'init', 'model_unreported'),
                                               ('my-custom-model', 'response', 'reference_missing')])
def test_a06_model_report_not_requested_selection(bundle, model, source, reason):
    c = codex()
    c.update(reported_model=model, model_source=source, requested_model='gpt-6.1-sol')
    result = calculate(evidence(c), scenario('credit'), bundle)
    assert result['amount'] is None and reason in result['reasons']
    assert result['selected_components'][0]['quantities']['uncached_input'] == 100000


def test_a06_unknown_profile_scheme_and_basis(bundle):
    for change, reason in [(dict(scheme=None), 'billing_profile_unknown'), (dict(scheme='legacy'), 'scheme_unsupported'),
                           (dict(basis='api_usd'), 'scheme_unsupported'), (dict(unit='other_credit'), 'scheme_unsupported')]:
        result = calculate(evidence(codex()), scenario('credit', **change), bundle)
        assert result['amount'] is None and reason in result['reasons']


@pytest.mark.parametrize('reasoning', [None, 0, 100, 10000])
def test_a07_reasoning_is_output_subset(bundle, reasoning):
    result = calculate(evidence(changed_component(reasoning_tokens=reasoning)), scenario(), bundle)
    assert_amount(result, '.44')
    assert 'reasoning' not in {l['category'] for l in result['lines']}


def haiku(prompt, **changes):
    return changed_component('claude-haiku-5-5', grain='request', input_tokens=prompt, cache_read_tokens=0,
                             cache_write_tokens=0, write_5m=0, output_tokens=1000, **changes)


@pytest.mark.parametrize('prompt,expected', [(100000, '.0105'), (100001, '.0525005')])
def test_a08_haiku_request_boundary(bundle, prompt, expected):
    assert_amount(calculate(evidence(haiku(prompt)), scenario(), bundle), expected)


def test_a08_cache_is_part_of_request_prompt_and_two_requests_stay_separate(bundle):
    c = haiku(0)
    c.update(cache_read_tokens=100001)
    assert_amount(calculate(evidence(c), scenario(), bundle), '.00750005')
    a, b = haiku(60000), haiku(60000)
    a['key'], b['key'] = 'request-1', 'request-2'
    assert_amount(calculate(evidence(a, b), scenario(), bundle), '.013')


@pytest.mark.parametrize('prompt', [1, 100000, 120000])
def test_a09_invocation_sum_cannot_establish_request_tier(bundle, prompt):
    c = haiku(prompt)
    c['grain'] = 'invocation_total'
    result = calculate(evidence(c), scenario(), bundle)
    assert result['amount'] is None and result['reasons'] == ['request_tier_unknown']


def test_a10_sourced_category_region_factor_and_no_double_application(bundle):
    old = selected_ref(bundle)
    doc = old.document()
    c = doc['cases'][0]
    c['conditions']['geography'] = 'synthetic-region'
    c['factors'] = [dict(key='region', value='1.1', categories=sorted(c['rates']), source='synthetic contract')]
    modified, _ = replace_reference(bundle, old, doc)
    profile = set_condition(scenario(), 'geography', 'synthetic-region')
    result = calculate(evidence(), profile, modified)
    assert_amount(result, '.484')
    assert all(l['factors'][0]['key'] == 'region' for l in result['lines'])
    c['included_adjustments'] = ['region']
    with pytest.raises(ReferenceError, match='unsupported_modifier'):
        seal_reference(doc)
    bad = calculate(evidence(), {**profile, 'extra_factors': ['region']}, modified)
    assert bad['amount'] is None and 'unsupported_modifier' in bad['reasons']


def test_a11_responses_api_write_contract_is_separate_from_cli(bundle):
    old = selected_ref(bundle, model='gpt-6.1-terra', product='openai_api')
    doc = old.document()
    # Synthetic API fixture without request tier; output zero isolates the input hand calculation.
    doc['cases'] = [deepcopy(doc['cases'][1])]
    doc['cases'][0].update(prompt_from=0, prompt_to=None, factors=[])
    doc['cases'][0]['rates']['cache_read']['amount'] = '0.1'
    modified, _ = replace_reference(bundle, old, doc)
    c = changed_component('gpt-6.1-terra', semantics='responses-api-1', input_tokens=12000, cache_read_tokens=4000,
                          cache_write_tokens=7000, write_5m=0, write_1h=0, write_30m=3000, write_12h=4000, output_tokens=0)
    result = calculate(evidence(c), scenario('api'), modified)
    assert_amount(result, '.01515')
    assert result['selected_components'][0]['quantities']['uncached_input'] == 1000
    c['semantics'] = 'codex-cli-1'
    bad = calculate(evidence(c), scenario('api'), modified)
    assert bad['amount'] is None and 'cache_write_semantics_unknown' in bad['reasons']


@pytest.mark.parametrize('prompt,expected', [(272000, '.554'), (272001, '1.103004')])
def test_a12_api_request_boundary(bundle, prompt, expected):
    c = codex()
    c.update(grain='request', input_tokens=prompt, cache_read_tokens=0, output_tokens=1000)
    assert_amount(calculate(evidence(c), scenario('api'), bundle), expected)
    # Sign-in tariffs have no API long-context threshold and need no request partition.
    c['grain'] = 'invocation_total'
    assert_amount(calculate(evidence(c), scenario('credit'), bundle), str(Decimal(prompt) * Decimal('0.00005') + Decimal('.25')))


@pytest.mark.parametrize('condition,reason', [('speed', 'speed_unknown'), ('geography', 'geography_unknown')])
def test_a13_unknown_required_condition(bundle, condition, reason):
    profile = scenario()
    del profile['conditions'][condition]
    result = calculate(evidence(), profile, bundle)
    assert result['amount'] is None and reason in result['reasons']


def test_a13_unknown_tool_charge_keeps_only_token_subtotal(bundle):
    ev = evidence()
    ev['charges_complete'] = False
    result = calculate(ev, scenario(), bundle)
    assert result['amount'] is None and result['known_subtotal'] == '0.440000000000'
    assert result['reasons'] == ['tool_charge_unknown']


@pytest.mark.parametrize('value', [-1, True, 2**63, '1', 1.5, float('inf'), float('nan')])
def test_a14_invalid_quantities(bundle, value):
    result = calculate(evidence(changed_component(input_tokens=value)), scenario(), bundle)
    assert result['amount'] is None and 'invalid_quantity' in result['reasons']


@pytest.mark.parametrize('changes,reason', [
    (dict(input_tokens=None), 'usage_missing'), (dict(write_5m=19999), 'inconsistent_usage'),
    (dict(write_5m=True), 'invalid_quantity'), (dict(reasoning_tokens=10001), 'inconsistent_usage'),
    (dict(reasoning_tokens=-1), 'invalid_quantity'), (dict(write_30m=1), 'inconsistent_usage'),
])
def test_a14_invalid_claude_partitions(bundle, changes, reason):
    result = calculate(evidence(changed_component(**changes)), scenario(), bundle)
    assert result['amount'] is None and reason in result['reasons']


def test_a14_reads_writes_cannot_exceed_total_input(bundle):
    c = codex()
    c['input_tokens'] = 1
    assert calculate(evidence(c), scenario('credit'), bundle)['reasons'] == ['inconsistent_usage']
    c.update(semantics='responses-api-1', cache_write_tokens=2, write_30m=2, write_12h=0)
    assert calculate(evidence(c), scenario('api'), bundle)['reasons'] == ['inconsistent_usage']


def test_a20_alias_drift_pins_versions_and_never_supplies_a_model_report(bundle):
    old = selected_ref(bundle, 'model_identity')
    alias = old.document()
    alias.update(model='sonnet-alias', identity_rule='alias')
    first = seal_reference(alias)
    b1 = make_bundle([*bundle.references, first])
    c = changed_component('sonnet-alias')
    assert_amount(calculate(evidence(c), scenario(), b1), '.44')
    alias['canonical_model'] = 'claude-opus-5-5'
    second = seal_reference(alias)
    b2 = make_bundle([*bundle.references, second])
    assert_amount(calculate(evidence(c), scenario(), b2), '.88')
    assert b1.id != b2.id and first.id != second.id
    assert_amount(calculate(evidence(c), scenario(), b1), '.44')
    with pytest.raises(ReferenceError, match='ambiguous reference versions'):
        make_bundle([*bundle.references, first, second])
    c['reported_model'], c['requested_model'] = None, 'sonnet-alias'
    assert 'model_unreported' in calculate(evidence(c), scenario(), b1)['reasons']


@pytest.mark.parametrize('at,expected', [('2026-10-26T23:59:59Z', False), ('2026-10-27T00:00:00Z', True),
                                      ('2026-10-27T23:59:59Z', True), ('2026-10-28T00:00:00Z', False)])
def test_a21_known_effective_intervals_are_half_open(bundle, at, expected):
    refs = []
    for ref in bundle.references:
        doc = ref.document()
        doc.update(effective_from='2026-10-27T00:00:00Z', effective_to='2026-10-28T00:00:00Z', effective_period_unknown=False)
        refs.append(seal_reference(doc))
    b = make_bundle(refs)
    result = calculate(evidence(), scenario(at=at, retrospective=False), b)
    if expected:
        assert_amount(result, '.44')
        assert result['warnings'] == []
    else:
        assert result['amount'] is None and 'reference_out_of_period' in result['reasons']


def test_a21_unknown_period_never_claims_historical_validity(bundle):
    result = calculate(evidence(), scenario(retrospective=False), bundle)
    assert result['amount'] is None and result['known_subtotal'] == '0.440000000000'
    assert result['reasons'] == ['effective_period_unknown']
    assert calculate(evidence(), scenario(), bundle)['retrospective'] is True


@pytest.mark.parametrize('numerator,expected', [('0.5', '0.000000000000'), ('1.5', '0.000000000002')])
def test_a24_once_per_invocation_half_even_rounding(bundle, numerator, expected):
    old = selected_ref(bundle)
    doc = old.document()
    for rate in doc['cases'][0]['rates'].values():
        rate['amount'] = '0'
    doc['cases'][0]['rates']['uncached_input']['amount'] = format(Decimal(numerator) / 1000000, 'f')
    modified, _ = replace_reference(bundle, old, doc)
    c = changed_component(input_tokens=1, cache_read_tokens=0, cache_write_tokens=0, write_5m=0, output_tokens=0)
    result = calculate(evidence(c), scenario(), modified)
    assert result['amount'] == expected
    assert Decimal(result['exact_sum']) == Decimal(numerator) / 10**12
    assert Decimal(result['rounding_adjustment']) == Decimal(expected) - Decimal(result['exact_sum'])
    # Two individually sub-quantum lines must be summed before rounding.
    c['key'] = 'r1'
    c['grain'] = 'request'
    other = {**c, 'key': 'r2'}
    combined = calculate(evidence(c, other), scenario(), modified)
    assert Decimal(combined['amount']) == Decimal(numerator) * 2 / 10**12


def test_a25_units_bases_and_schemes_are_not_convertible(bundle):
    api = calculate(evidence(codex()), scenario('enterprise'), bundle)
    equivalent = calculate(evidence(codex()), scenario('enterprise', basis='subscription_equivalent'), bundle)
    assert_amount(api, '.39')
    assert_amount(equivalent, '.39')
    assert equivalent['counterfactual'] and not api['counterfactual']
    key = digest({'scope': 'synthetic invocation', 'model_partition': 'single', 'conditions': 'standard'})
    estimate = dict(unit='USD', basis='api_usd', scheme='openai_api_usd', comparison_key=key, amount='.39')
    assert compare_estimate({**api, 'comparison_key': key}, estimate)['status'] == 'not_comparable'


def test_a26_discrepancy_preserves_signed_delta_and_known_precision(bundle):
    value = calculate(evidence(), scenario(), bundle)
    key = digest({'scope': 'same scope, model partition and conditions'})
    value['comparison_key'] = key
    estimate = dict(unit='USD', basis='api_usd', scheme='anthropic_api_usd', comparison_key=key, amount='.45')
    # Plain decimal grammar requires a leading zero in a reported amount.
    estimate['amount'] = '0.45'
    original = deepcopy(estimate)
    unknown = compare_estimate(value, estimate)
    assert unknown['status'] == 'precision_unknown' and Decimal(unknown['delta']) == Decimal('-.01')
    known = compare_estimate(value, {**estimate, 'rounding_quantum': '0.01', 'rounding_source': 'synthetic documented policy'})
    assert known['status'] == 'compared' and known['tolerance'] == '0.0050000000005'
    assert known['within_precision'] is False and Decimal(known['delta']) == Decimal('-.01')
    assert estimate == original
    assert compare_estimate(value, {**estimate, 'legacy_float': True})['reasons'] == ['legacy_float']
    assert compare_estimate(value, {**estimate, 'amount': '0.439'})['delta'] == '0.001000000000'


def test_partial_unknown_delegation_and_overlapping_views_never_produce_full_amount(bundle):
    for key, val, reason in [('coverage', 'partial', 'partial_capture'), ('delegation', 'unknown', 'delegation_boundary_unknown'),
                             ('partition', 'unknown', 'model_partition_unknown')]:
        ev = evidence()
        ev[key] = val
        result = calculate(ev, scenario(), bundle)
        assert result['amount'] is None and reason in result['reasons']
    ev = evidence(component(), {**component(), 'key': 'constituent', 'grain': 'request'})
    assert calculate(ev, scenario(), bundle)['reasons'] == ['model_partition_conflict']
    ev['components'][1] = component()
    assert calculate(ev, scenario(), bundle)['reasons'] == ['model_partition_conflict']


def test_calculation_is_reproducible_immutable_and_ignores_global_decimal_context(bundle):
    ev, profile = evidence(), scenario()
    before = deepcopy((ev, profile, bundle.envelope()))
    first = calculate(ev, profile, bundle)
    precision = getcontext().prec
    try:
        getcontext().prec = 3
        assert calculate(ev, profile, bundle) == first
    finally:
        getcontext().prec = precision
    assert (ev, profile, bundle.envelope()) == before
    assert first['evidence_digest'] == digest(ev) and first['profile_digest'] == digest(profile)
    assert first['reference_set_digest'] == bundle.id
    doc = bundle.references[0].document()
    doc['model'] = 'tampered'
    assert bundle.envelope() == before[2]


@pytest.mark.parametrize('rate', ['NaN', 'Infinity', '-1', '1e2', '1000000001', '0.0000000000001', 1.0, True])
def test_invalid_rates_are_rejected_at_reference_admission(bundle, rate):
    doc = selected_ref(bundle).document()
    doc['cases'][0]['rates']['output']['amount'] = rate
    with pytest.raises(ReferenceError, match='invalid_rate'):
        seal_reference(doc)


@pytest.mark.parametrize('factor', ['0', '-1', '1001', '1.0000001', '1e1', True, float('inf')])
def test_invalid_factors_rejected(bundle, factor):
    doc = selected_ref(bundle).document()
    doc['cases'][0]['factors'] = [dict(key='contract', value=factor, categories=['output'], source='synthetic')]
    with pytest.raises(ReferenceError, match='unsupported_modifier'):
        seal_reference(doc)


def test_reference_bytes_digests_keys_order_and_overlaps_are_validated(bundle):
    assert load_bundle(canonical(bundle.envelope())) == bundle
    raw = canonical(bundle.envelope())
    with pytest.raises(ReferenceError, match='duplicate JSON key'):
        load_bundle(b'{"format":"metrics-reference-1","format":"metrics-reference-1","references":[]}')
    env = bundle.envelope()
    env['references'][0]['document']['model'] = 'tamper'
    with pytest.raises(ReferenceError):
        load_bundle(canonical(env))
    env = bundle.envelope()
    env['references'].append(env['references'][0])
    with pytest.raises(ReferenceError):
        load_bundle(canonical(env))
    with pytest.raises(ReferenceError):
        load_bundle(raw.replace(b'1000000', b'1.0', 1))
    doc = selected_ref(bundle).document()
    doc['cases'].append({**deepcopy(doc['cases'][0]), 'key': 'z-overlap'})
    with pytest.raises(ReferenceError, match='overlapping'):
        seal_reference(doc)
    bad = ReferenceBundle((Reference('0'*64, bundle.references[0].content),))
    result = calculate(evidence(), scenario(), bad)
    assert result['status'] == 'unsupported' and result['reasons'] == ['reference_conflict']


def test_exact_arithmetic_accepts_maximum_bounds_and_eight_factors(bundle):
    doc = selected_ref(bundle).document()
    case = doc['cases'][0]
    case['rates']['uncached_input']['amount'] = '1000000000'
    case['factors'] = [dict(key=f'f{i}', value='999.999999', categories=['uncached_input'], source='synthetic') for i in range(8)]
    modified, _ = replace_reference(bundle, selected_ref(bundle), doc)
    c = changed_component(input_tokens=2**63-1, cache_read_tokens=0, cache_write_tokens=0, write_5m=0, output_tokens=0)
    result = calculate(evidence(c), scenario(), modified)
    assert result['status'] == 'complete'
    # Independent integer-rational expectation; avoids repeating Decimal implementation arithmetic.
    numerator = (2**63-1) * 10**9 * 999999999**8
    denominator = 10**6 * (10**6)**8
    scaled, remainder = divmod(numerator * 10**12, denominator)
    scaled += int(remainder * 2 > denominator or remainder * 2 == denominator and scaled % 2)
    assert result['amount'] == f'{scaled//10**12}.{scaled%10**12:012d}'
    case['factors'].append(dict(key='f8', value='1', categories=['uncached_input'], source='synthetic'))
    with pytest.raises(ReferenceError, match='too many factors'):
        seal_reference(doc)


def test_independent_server_tool_tariff_and_client_activity_not_billable(bundle):
    doc = selected_ref(bundle).document()
    doc.update(model='synthetic-search', quantity_basis='charged_tool', semantics=[], required_conditions=[])
    doc['cases'] = [dict(key='search', conditions={}, prompt_from=0, prompt_to=None,
                         rates={'search': dict(amount='10', quantity=1000, unit='search')},
                         factors=[], included_adjustments=[])]
    tool = seal_reference(doc)
    b = make_bundle([*bundle.references, tool])
    charge = dict(key='server-search', category='search', quantity=2, tariff_reference=tool.id,
                  provenance='reported_billable', source='synthetic billable counter', conditions={})
    ev = evidence()
    ev['charges'] = [charge]
    result = calculate(ev, scenario(), b)
    assert_amount(result, '.46')
    assert result['lines'][-1]['rate']['unit'] == 'search'
    charge['provenance'] = 'client_tool_activity'
    bad = calculate(ev, scenario(), b)
    assert bad['amount'] is None and bad['known_subtotal'] == '0.440000000000'
    assert 'tool_charge_unknown' in bad['reasons']


def test_no_side_effects_or_source_refresh_during_calculation(bundle, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('calculator attempted I/O')
    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr('socket.socket', forbidden)
    assert_amount(calculate(evidence(), scenario(), bundle), '.44')


def test_observed_zero_is_complete_absence_is_not(bundle):
    zero = changed_component(input_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                             write_5m=None, write_1h=None, output_tokens=0)
    result = calculate(evidence(zero), scenario(), bundle)
    assert result['status'] == 'complete' and result['amount'] == '0.000000000000'
    zero['output_tokens'] = None
    absent = calculate(evidence(zero), scenario(), bundle)
    assert absent['amount'] is absent['known_subtotal'] is None
    assert absent['reasons'] == ['usage_missing']


def test_a22_a23_calculator_boundary_profile_edits_create_separate_evidence(bundle):
    profile = scenario()
    old = calculate(evidence(), profile, bundle)
    saved = deepcopy(old)
    # There is no configuration activation or queued-job rebinding in this pure boundary.
    profile['basis'] = 'subscription_equivalent'
    newer = calculate(evidence(), profile, bundle)
    assert newer['profile_digest'] != old['profile_digest']
    assert newer['amount'] == old['amount'] and newer['counterfactual']
    assert old == saved


def test_source_backed_contract_factors_and_already_adjusted_rates_agree(bundle):
    original = selected_ref(bundle)
    doc = original.document()
    c = doc['cases'][0]
    c['factors'] = [dict(key='contract', value='0.5', categories=['output'], source='synthetic agreement')]
    doc['required_conditions'].append('contract')
    doc['required_conditions'].sort()
    c['conditions']['contract'] = 'synthetic'
    profile = set_condition(scenario(), 'contract', 'synthetic')
    discounted, _ = replace_reference(bundle, original, doc)
    assert_amount(calculate(evidence(), profile, discounted), '.39')
    c['factors'] = []
    c['rates']['output']['amount'] = '5'
    c['included_adjustments'] = ['contract']
    adjusted, _ = replace_reference(bundle, original, doc)
    assert_amount(calculate(evidence(), profile, adjusted), '.39')
    assert 'unsupported_modifier' in calculate(evidence(), profile, bundle)['reasons']


def test_missing_reference_missing_rate_and_unsupported_speed_never_use_standard(bundle):
    old = selected_ref(bundle)
    assert 'reference_missing' in calculate(evidence(), scenario(), make_bundle([r for r in bundle.references if r != old]))['reasons']
    doc = old.document()
    doc['cases'][0]['rates']['write_5m']['amount'] = None
    modified, _ = replace_reference(bundle, old, doc)
    result = calculate(evidence(), scenario(), modified)
    assert result['amount'] is None and result['known_subtotal'] == '0.390000000000'
    assert result['reasons'] == ['reference_missing']
    fast = calculate(evidence(), set_condition(scenario(), 'speed', 'fast'), bundle)
    assert fast['amount'] is None and fast['reasons'] == ['unsupported_modifier']


def test_disjoint_versions_select_the_effective_reference_without_changing_old_bytes(bundle):
    old = selected_ref(bundle)
    first = old.document()
    first.update(effective_from='2026-01-01T00:00:00Z', effective_to='2026-10-27T00:00:00Z', effective_period_unknown=False)
    earlier = seal_reference(first)
    later_doc = deepcopy(first)
    later_doc.update(effective_from=first['effective_to'], effective_to=None, supersedes=earlier.id)
    later_doc['cases'][0]['rates']['output']['amount'] = '20'
    later = seal_reference(later_doc)
    b = make_bundle([r for r in bundle.references if r != old] + [earlier, later])
    assert_amount(calculate(evidence(), scenario(at='2026-10-26T00:00:00Z'), b), '.44')
    result = calculate(evidence(), scenario(), b)
    assert_amount(result, '.54')
    assert all(l['tariff_reference'] == later.id for l in result['lines'])
    assert earlier.document() == first


@pytest.mark.parametrize('change', ['duplicate', 'overlap'])
def test_duplicate_charges_and_inclusive_parent_children_are_rejected(bundle, change):
    ev = evidence()
    if change == 'duplicate':
        # Even identical duplicate billable counters must not be charged twice.
        charge = dict(key='same', quantity=1)
        ev['charges'] = [charge, charge]
    else:
        a, b = component(), component('claude-opus-5-5')
        a.update(key='parent', grain='model_total', includes=['child'])
        b.update(key='child', grain='model_total', parent_key='parent')
        ev = evidence(a, b)
    result = calculate(ev, scenario(), bundle)
    assert result['amount'] is None and 'model_partition_conflict' in result['reasons']


@pytest.mark.parametrize('key,value', [('format', None), ('sources', [{'url': 123}]), ('cases', [{'key': []}]),
                                     ('effective_period_unknown', None), ('required_conditions', ['speed', 'speed'])])
def test_malformed_references_fail_with_stable_reason(bundle, key, value):
    doc = selected_ref(bundle).document()
    doc[key] = value
    with pytest.raises(ReferenceError) as exc:
        seal_reference(doc)
    assert exc.value.reason == 'reference_conflict'


def test_mixed_model_partition_has_two_separately_sourced_amounts(bundle):
    a, b = component(), component('claude-opus-5-5')
    a.update(key='sonnet', grain='model_total')
    b.update(key='opus', grain='model_total')
    result = calculate(evidence(a, b), scenario(), bundle)
    assert_amount(result, '1.32')
    assert len({line['identity_reference'] for line in result['lines']}) == 2


def test_estimate_precision_boundary_and_unknown_rounding_source(bundle):
    value = calculate(evidence(), scenario(), bundle)
    key = digest({'scope': 'same'})
    value['comparison_key'] = key
    estimate = dict(unit='USD', scheme='anthropic_api_usd', basis='api_usd', comparison_key=key,
                    amount='0.435', rounding_quantum='0.01', rounding_source='synthetic policy')
    assert compare_estimate(value, estimate)['within_precision'] is True
    estimate.pop('rounding_source')
    result = compare_estimate(value, estimate)
    assert result['status'] == 'precision_unknown' and result['tolerance'] is None


@pytest.mark.parametrize('value', [None, dict(value='unknown', provenance='asserted', source='synthetic')])
def test_explicit_unknown_conditions_keep_specific_reasons(bundle, value):
    profile = scenario()
    profile['conditions']['speed'] = value
    assert calculate(evidence(), profile, bundle)['reasons'] == ['speed_unknown']


def test_capture_reasons_are_retained_and_cannot_become_complete(bundle):
    ev = evidence()
    ev['reasons'] = ['terminal_missing', 'partial_capture']
    result = calculate(ev, scenario(), bundle)
    assert result['amount'] is None and result['known_subtotal'] == '0.440000000000'
    assert result['reasons'] == ['partial_capture', 'terminal_missing']


@pytest.mark.parametrize('value', ['2026-10-27Z', '2026-10-27T00:00:00+01:00', '2026-02-30T00:00:00Z'])
def test_reference_timestamps_require_real_utc_instants(bundle, value):
    doc = selected_ref(bundle).document()
    doc['observed_at'] = value
    with pytest.raises(ReferenceError, match='reference_conflict'):
        seal_reference(doc)


def test_unrepresentable_reported_precision_never_rounds_a_descriptive_delta(bundle):
    value = calculate(evidence(), scenario(), bundle)
    key = digest({'scope': 'same'})
    value.update(comparison_key=key, amount='9'*50 + '.000000000000')
    estimate = dict(unit='USD', scheme='anthropic_api_usd', basis='api_usd', comparison_key=key,
                    amount='0.' + '0'*150 + '1')
    result = compare_estimate(value, estimate)
    assert result['status'] == 'not_comparable' and result['reasons'] == ['reporting_precision_invalid']


@pytest.mark.parametrize('unit,bases', [('other_credit', ['api_usd']), ('USD', ['token_credit'])])
def test_reference_unit_and_basis_cannot_conflate_dollars_and_credits(bundle, unit, bases):
    doc = selected_ref(bundle).document()
    doc.update(unit=unit, bases=bases)
    with pytest.raises(ReferenceError, match='reference_conflict'):
        seal_reference(doc)
