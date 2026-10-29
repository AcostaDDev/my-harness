import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import { accountingQuery, activeFilters, ageDays, bucketState, captureFacts, counted, decimal, groupFilter, invocationLabel, money, nextDay,
  periodState, rateParts, reasonKey, REASONS } from '../src/accounting.ts';
import { translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ServiceModeContext } = await import('../src/ServiceMode.tsx');
const { AccountingPage } = await import('../src/pages/Accounting.tsx');
delete globalThis.__tsxHookHarness;

const t = language => (key, params) => translate({ en, es }, language, key, params);
// Intl separates the number and the unit with a no-break space; the tests compare plain text.
const plain = text => text.replace(/[  ]/g, ' ');

test('exact decimals are regrouped, never rounded or passed through a float', () => {
  assert.equal(decimal('0.540000000000', 'en'), '0.54');
  assert.equal(decimal('0.540000000000', 'en', 2), '0.54');
  assert.equal(decimal('12.000000000000', 'en', 2), '12.00');
  assert.equal(decimal('1234567.000000000001', 'en'), '1,234,567.000000000001');
  assert.equal(decimal('1234567.000000000001', 'es'), '1.234.567,000000000001');
  assert.equal(decimal('9007199254740993.1', 'en'), '9,007,199,254,740,993.1');
  assert.equal(decimal('-0.000000000000', 'en'), '0');
  assert.equal(decimal('-1.50', 'es', 2), '-1,50');
  assert.equal(decimal('not a number', 'en'), 'not a number');
  assert.equal(money('0.540000000000', 'USD', 'en', t('en')), '$0.54');
  assert.equal(plain(money('0.540000000000', 'USD', 'es', t('es'))), '0,54 US$');
  assert.equal(money('0.000123450000', 'USD', 'en', t('en')), '$0.00012345');
  assert.equal(money('-1.5', 'USD', 'en', t('en')), '-$1.50');
  assert.equal(money('12.5', 'chatgpt_work_codex_credit', 'en', t('en')), '12.5 credits');
  assert.equal(money('12.5', 'chatgpt_work_codex_credit', 'es', t('es')), '12,5 créditos');
  assert.equal(money('3', 'future_unit', 'en', t('en')), '3 future_unit');
  assert.equal(money(null, 'USD', 'es', t('es')), 'sin dato');
});

test('a bucket claims its full amount only when the API gives one', () => {
  assert.deepEqual(bucketState({ amount: '1.0', known_subtotal: '1.0' }), { state: 'full', value: '1.0' });
  assert.deepEqual(bucketState({ amount: null, known_subtotal: '0.54' }), { state: 'partial', value: '0.54' });
  assert.deepEqual(bucketState({ amount: null, known_subtotal: null }), { state: 'absent', value: null });
  assert.deepEqual(bucketState({ amount: '0', known_subtotal: '0' }), { state: 'full', value: '0' });
});

test('queries carry the scope, filters, inclusive UTC days and the selection', () => {
  assert.equal(accountingQuery({}), '');
  assert.equal(accountingQuery({ project: 'p' }, { phase: 'P001', task: 'T1', provider: ' claude ', work: ['task_first_pass', 'task_rework'],
    from_day: '2026-10-01', until_day: '2026-10-31' }, 'cohort-1', { offset: 10, limit: 20 }),
    '?project_id=p&phase=P001&task=T1&provider=claude&work=task_first_pass&work=task_rework'
    + '&started_from=2026-10-01T00%3A00%3A00Z&started_before=2026-11-01T00%3A00%3A00Z&cohort=cohort-1&offset=10&limit=20');
  // Phase and task need a project; a task needs its phase; invalid days are not sent.
  assert.equal(accountingQuery({}, { phase: 'P001', task: 'T1', role: '' }), '');
  assert.equal(accountingQuery({ project: 'p' }, { task: 'T1', from_day: '2026-02-30', until_day: 'x' }), '?project_id=p');
  assert.equal(nextDay('2026-12-31'), '2027-01-01');
  assert.equal(nextDay('2028-02-28'), '2028-02-29');
  assert.equal(nextDay('2026-02-29'), undefined);
  assert.equal(activeFilters({ provider: 'x', role: ' ', work: [], until_day: '2026-01-01' }), 2);
});

test('a group narrows the view only through filters the API accepts', () => {
  const group = (key, key_kind = 'value', phase_code = null) => ({ key, key_kind, phase_code });
  assert.deepEqual(groupFilter('provider', group('claude')), { provider: 'claude' });
  assert.equal(groupFilter('provider', group(null, 'unknown')), undefined);
  assert.deepEqual(groupFilter('effective_model', group('m', 'reported')), { effective_model: 'm' });
  assert.deepEqual(groupFilter('effective_model', group(null, 'mixed')), { effective_model_kind: 'mixed' });
  assert.deepEqual(groupFilter('effective_model', group(null, 'unknown')), { effective_model_kind: 'unknown' });
  assert.deepEqual(groupFilter('work', group('task_rework')), { work: ['task_rework'] });
  assert.equal(groupFilter('work', group('future')), undefined);
  assert.deepEqual(groupFilter('day', group('2026-10-27')), { from_day: '2026-10-27', until_day: '2026-10-27' });
  assert.equal(groupFilter('phase', group('P001')), undefined, 'a phase filter needs a project');
  assert.deepEqual(groupFilter('phase', group('P001'), 'p'), { phase: 'P001' });
  assert.deepEqual(groupFilter('task', group('T1', 'value', 'P001'), 'p'), { phase: 'P001', task: 'T1' });
  assert.equal(groupFilter('root', group('/r')), undefined);
});

test('invocations are labelled by their source id, not by the kind every row shares', () => {
  assert.equal(invocationLabel('managed_attempt:a57db841-da00-4000-8000-000000000001'), 'a57db841');
  assert.equal(invocationLabel('configuration_assistance:op-2'), 'op-2');
  assert.equal(invocationLabel('legacy-id'), 'legacy-i');
});

test('reference period, age, reasons, capture facts and rates', () => {
  assert.equal(periodState({ reasons: ['reference_out_of_period'], warnings: [] }, 1), 'out_of_period');
  assert.equal(periodState({ reasons: ['effective_period_unknown'], warnings: [] }, 1), 'unknown');
  assert.equal(periodState({ reasons: [], warnings: ['effective_period_unknown'] }, 2), 'retrospective');
  assert.equal(periodState({ reasons: [], warnings: [] }, 2), 'applies');
  assert.equal(periodState({ reasons: ['reference_missing'], warnings: [] }, 0), 'no_reference');
  assert.equal(ageDays('2026-10-27T21:06:53Z', new Date('2026-10-29T21:06:52Z')), 1);
  assert.equal(ageDays(null, new Date()), null);
  assert.equal(ageDays('later', new Date()), null);
  for (const code of REASONS) {
    for (const catalog of [en, es]) assert.ok(catalog[reasonKey(code)], code);
  }
  assert.equal(reasonKey('future_reason'), undefined);
  assert.deepEqual(counted({ b: 1, a: 1, c: 3, z: 0 }), [['c', 3], ['a', 1], ['b', 1]]);
  assert.deepEqual(captureFacts(null).tools, null);
  const facts = captureFacts({ client: { cli_version: '2.0' }, timing: { wall_ms: 1200, duration_ms: -1 },
    activity: { tools: { Read: 2, Bash: 'x' }, turns: 3 }, reported_amounts: { total_cost_usd: { value: '0.1', representation: 'legacy_float' } } });
  assert.equal(facts.cli_version, '2.0'); assert.equal(facts.wall_ms, 1200); assert.equal(facts.duration_ms, null);
  assert.deepEqual(facts.tools, [['Read', 2]]); assert.equal(facts.turns, 3);
  assert.deepEqual(facts.reported_cost, { value: '0.1', legacy: true });
  assert.deepEqual(rateParts({ amount: '2.50', quantity: 1000000, unit: 'token' }), { amount: '2.50', quantity: 1000000, unit: 'token' });
  assert.equal(rateParts({ amount: 2.5, quantity: 1 }), null);
});

// --- page ------------------------------------------------------------------------------------------

const selection = (cohort = null) => ({ policy: cohort ? 'cohort' : 'admission', cohort, complete: !cohort || cohort.status === 'CLOSED' });
const cohort = { id: 'cohort-1', name: 'reprice-oct', kind: 'repricing', status: 'BUILDING', expected: 4, built: 1,
  selection_digest: 'a'.repeat(64), scenario_digest: null, reference_set_digest: null, basis: 'api_usd', retrospective: true,
  created_at: '2026-10-28T10:00:00Z', closed_at: null };
const bucket = (basis, extra) => ({ unit: 'USD', platform: 'anthropic_first_party', product: 'claude_api', scheme: 'anthropic_api_usd', basis,
  counterfactual: basis === 'subscription_equivalent', retrospective: false, invocations: 3, complete: 1, incomplete: 1, unsupported: 0,
  denominator: 3, amount: null, known_subtotal: null, reasons: {}, discrepancies: {}, ...extra });
const tokens = { uncached_input_tokens: { sum: 1200, invocations: 2, partial: 1 }, cache_read_tokens: { sum: null, invocations: 0, partial: 0 },
  output_tokens: { sum: 0, invocations: 2, partial: 0 } };
const totals = {
  coverage: { invocations: 4, expected: 3, launch: { pending: 0, not_invoked: 1, observed: 3, unknown_execution: 0 }, captured: 2,
    usage: { complete: 1, partial: 1, absent: 1 }, valuation: { complete: 1, incomplete: 1, unsupported: 0, unpriced: 1 },
    unpriced_reasons: { capture_unavailable: 1 }, outside_selection: null, full_scope_priced: false },
  tokens, cache_hit: { cache_read_tokens: 0, input_tokens: 0, invocations: 0, excluded: 2, ratio: null },
  wall_throughput: { output_tokens: 0, wall_ms: 0, invocations: 0, excluded: 2, output_tokens_per_wall_second: null },
  amounts: [bucket('api_usd', { known_subtotal: '0.540000000000', reasons: { effective_period_unknown: 1 }, discrepancies: { not_comparable: 1 } }),
    bucket('subscription_equivalent', { amount: '1.250000000000', known_subtotal: '1.250000000000' }),
    bucket('token_credit', { unit: 'chatgpt_work_codex_credit', scheme: 'chatgpt_work_codex_credit', amount: '12.500000000000', known_subtotal: '12.500000000000' })],
};
const invocation = { id: 'managed_attempt:0f1e2d3c-0001', source_kind: 'managed_attempt', source_id: 'attempt-1', run_id: 'run-1', attempt_id: 'attempt-1',
  preparation_id: null, preparation_step_id: null, operation_id: null, request_id: null, root: '/synthetic/root', project_id: null,
  phase_code: 'P001', task_id: 'T1', purpose: 'task', work: 'task_first_pass', role: 'executor', agent: 'claude', provider: 'claude',
  requested_model: 'requested-model', requested_effort: 'low', effective_model: null, effective_model_kind: 'mixed', launch: 'observed',
  outcome: 'COMPLETE', started_at: '2026-10-27T10:00:00.000000+00:00', finished_at: null, wall_ms: 1500,
  capture: { id: 7, version: 'usage-capture-1', source: 'capture', recorded_at: '2026-10-27T10:00:02Z' },
  usage: { coverage: 'partial', partition: 'disjoint', delegation: 'none', charges_complete: true, reasons: ['partial_capture'], tokens: { output_tokens: 10 } },
  in_selection: true, unpriced_reason: null,
  valuations: [{ id: 'val-0000001', origin: 'admission', status: 'incomplete', unit: 'USD', platform: 'anthropic_first_party', product: 'claude_api',
    scheme: 'anthropic_api_usd', basis: 'api_usd', counterfactual: false, retrospective: true, amount: null, known_subtotal: '0.540000000000',
    reasons: [], warnings: ['effective_period_unknown'], discrepancy: 'not_comparable' }] };
const valuation = { ...invocation.valuations[0], capture_id: 7, normalization: 'usage-accounting-1', calculator: 'valuation-1',
  profile_digest: 'p', reference_set_digest: 'r', scenario_digest: 's', evidence_digest: 'e', scenario: {}, exact_sum: '0.540000000000',
  rounding_adjustment: '0', selected_components: [], supersedes: null, recorded_at: '2026-10-27T10:00:03Z', cohorts: [],
  discrepancy_detail: { status: 'not_comparable', delta: null, tolerance: null, within_precision: null, reasons: ['comparison_basis_unknown_or_different'],
    reported: { value: '0.61', representation: 'decimal_text' } },
  lines: [{ number: 1, component_key: 'terminal', category: 'output', quantity: 54000, rate: { amount: '10', quantity: 1000000, unit: 'token' },
    factors: [], included_adjustments: [], tariff_reference: 'b'.repeat(64), identity_reference: 'c'.repeat(64), rate_case: 'standard', exact_amount: '0.540000000000' }],
  references: [{ id: 'b'.repeat(64), kind: 'tariff', format: 'metrics-reference-1', source: 'packaged', provider: 'claude', product: 'claude_api',
    model: 'synthetic-model', observed_at: '2026-10-27T21:06:53Z' }] };
const page = (items, next_offset = null) => ({ items, offset: 0, next_offset });

function environment(language, archive) {
  const driver = hookHost();
  const requests = [], timers = [];
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = callback => { timers.push(callback); return timers.length; };
  globalThis.clearTimeout = () => {};
  globalThis.document = { documentElement: { lang: '' } };
  globalThis.localStorage = { getItem: () => language, setItem: () => {} };
  globalThis.fetch = async (path, options) => {
    assert.equal(options, undefined, 'Accounting reads are GET only'); requests.push(path);
    const url = new URL(path, 'http://synthetic');
    const base = { format: 'accounting-aggregate-1', filters: {}, selection: selection(url.searchParams.get('cohort') ? cohort : null) };
    let data;
    if (url.pathname === '/api/managed/projects') data = [];
    else if (url.pathname.endsWith('/accounting/summary')) data = { ...base, ...totals };
    else if (url.pathname.endsWith('/accounting/cohorts')) data = page([cohort]);
    else if (url.pathname === '/api/managed/configuration/references') data = page([{ id: 'e'.repeat(64), source: 'packaged', recorded_at: null,
      available: true, references: 2, providers: ['claude'], models: ['synthetic-model'], observed_from: null, observed_to: null,
      effective_period: 'unknown', schemes: [] }]);
    else if (url.pathname.endsWith('/accounting/tasks')) data = { ...base, tasks: { attempted: 2, committed: 1, acceptance_unknown: 1, not_committed: 0 },
      coverage: totals.coverage, committed_coverage: totals.coverage, indicators: [{ ...bucket('api_usd'), total: { amount: null, known_subtotal: '0.54' },
        committed_work: { amount: null, known_subtotal: '0.3' }, per_committed_task: null, per_attempted_task: null, committed_work_per_committed_task: null }] };
    else if (url.pathname.endsWith('/accounting/groups')) data = { ...base, dimension: url.searchParams.get('dimension'), order: 'invocations', offset: 0, next_offset: null,
      items: [{ key: 'claude', key_kind: 'value', root: null, phase_code: null, ...totals }, { key: null, key_kind: 'unknown', root: null, phase_code: null, ...totals }] };
    else if (url.pathname.endsWith('/accounting/invocations')) data = { ...base, ...page([invocation], 20) };
    else if (url.pathname.endsWith('/valuations')) data = page([valuation]);
    else if (url.pathname.endsWith('/accounting/invocations/managed_attempt%3A0f1e2d3c-0001')) data = { ...invocation, selection: base.selection, versions: {}, binding: { basis: 'api_usd' },
      binding_sha256: 'd'.repeat(64), captures: 1, capture_document: { digest: 'x', evidence: null, evidence_digest: null,
        document: { client: { cli_version: 'synthetic-cli' }, activity: { tools: { Read: 2 }, turns: 4 }, timing: { duration_ms: 1400 } } },
      components: [{ key: 'terminal', grain: 'terminal', parent_key: null, inclusion: 'inclusive', reported_model: null, model_source: null, semantics: 'claude-cli-1',
        coverage: 'partial', input_tokens: 5, cache_read_tokens: null, cache_write_tokens: null, write_5m: null, write_1h: null, output_tokens: 10, reasoning_tokens: null, reasons: [] }] };
    else assert.fail(`Unexpected read: ${path}`);
    return Response.json(data);
  };
  const mode = { read_only_archive: archive, enabled: !archive, alive: !archive, last_error: null, ports_configured: false, commit_writer_configured: false };
  return { ...driver, requests, timers,
    tree: () => el(I18nProvider, null, el(ServiceModeContext.Provider, { value: mode }, el(AccountingPage, {}))),
    button: label => driver.host.elements.find(e => e.type === 'button' && (e.props['aria-label'] === label || e.props.children === label)),
    close() {
      driver.close(); Object.assign(globalThis, original);
      for (const key of ['document', 'localStorage']) delete globalThis[key];
    } };
}

for (const [language, archive] of [['en', false], ['es', true]]) {
  test(`accounting page reads only the accounting API and separates bases (${language}, ${archive ? 'archive' : 'live'})`, async () => {
    const env = environment(language, archive);
    try {
      const tree = env.tree();
      let html = plain(await env.render(tree));
      // The global page also lists the available reference bundles (D263), read-only.
      assert.ok(env.requests.every(path => path.startsWith('/api/managed/accounting/') || path === '/api/managed/projects'
        || path.startsWith('/api/managed/configuration/references?')), env.requests.join('\n'));
      assert.ok(!env.requests.some(path => path.includes('/metrics/')), 'Reported estimates stay on Statistics');
      if (language === 'en') {
        assert.match(html, /\$0\.54<sup class="partial"[^>]*> partial<\/sup>/);
        assert.match(html, /Subscription equivalent<\/strong> <span class="status status-attention"[^>]*><span class="status-mark" aria-hidden="true"><\/span>counterfactual/);
        assert.match(html, /\$1\.25/); assert.match(html, /12\.5 credits/);
        assert.match(html, /No capture/); assert.match(html, /capture_unavailable/);
        assert.match(html, /requested-model<\/span> → <span class="muted">Mixed models/);
        assert.match(html, /The scope is not fully priced/);
      } else {
        assert.match(html, /0,54 US\$<sup class="partial"[^>]*> parcial<\/sup>/);
        assert.match(html, /12,5 créditos/);
        assert.match(html, /En construcción \(incompleta\)/);
      }
      // Null tokens are "no data"; an observed zero stays zero.
      assert.match(html, language === 'en' ? /Cache read<\/th><td class="numeric"><span class="muted">no data/ : /Caché leída<\/th><td class="numeric"><span class="muted">sin dato/);
      assert.equal(/accounting-backfill/.test(html), !archive, 'CLI commands are named only on a live service');
      // The available reference bundles are listed read-only, also on an archive; no import control here.
      assert.match(html, language === 'en' ? /Pricing references/ : /Referencias de precios/);
      assert.match(html, language === 'en' ? /Unknown \(observed prices only\)/ : /Desconocido \(solo precios observados\)/);
      assert.doesNotMatch(html, /references-content|references-file/);
      assert.doesNotMatch(html, /type="text" name=|method="post"/i);
      if (archive) assert.equal(env.timers.length, 0, 'A query-only archive never polls');
      else assert.ok(env.timers.length > 0, 'A live service refreshes its reads');

      // Selecting a cohort replaces the admission policy in every read; a BUILDING cohort is incomplete.
      env.button(language === 'en' ? 'Use cohort reprice-oct' : 'Usar la cohorte reprice-oct').props.onClick();
      html = plain(await env.render(tree));
      assert.ok(env.requests.some(path => path.startsWith('/api/managed/accounting/summary?cohort=cohort-1')));
      assert.ok(env.requests.some(path => path.startsWith('/api/managed/accounting/groups?cohort=cohort-1&dimension=provider')));
      assert.match(html, language === 'en' ? /still being built/ : /aún se está construyendo/);

      // A group narrows the filters; an unknown group offers no filter.
      const filters = env.host.elements.filter(e => e.type === 'button' && e.props['aria-label']?.startsWith(language === 'en' ? 'Filter by' : 'Filtrar por'));
      assert.equal(filters.length, 1);
      filters[0].props.onClick();
      await env.render(tree);
      assert.ok(env.requests.some(path => path === '/api/managed/accounting/summary?provider=claude&cohort=cohort-1'));

      // The detail shows requested versus effective model, tools, lines, references and the comparison.
      env.button(language === 'en' ? 'Details of invocation 0f1e2d3c' : 'Detalle de la invocación 0f1e2d3c').props.onClick();
      html = plain(await env.render(tree));
      assert.ok(env.requests.includes('/api/managed/accounting/invocations/managed_attempt%3A0f1e2d3c-0001?cohort=cohort-1'));
      assert.ok(env.requests.includes('/api/managed/accounting/invocations/managed_attempt%3A0f1e2d3c-0001/valuations?offset=0&limit=5'));
      assert.match(html, /synthetic-cli/); assert.match(html, /Read<\/span> × 2/);
      if (language === 'en') {
        assert.match(html, /\$10\.00 per 1,000,000 token/);
        assert.match(html, /effective period unknown, accepted by the retrospective scenario/);
        assert.match(html, /Client-reported estimate: 0\.61 USD \(its tariff basis is not established\)/);
        assert.match(html, /Not comparable: both figures are shown and no billing discrepancy is asserted/);
        assert.match(html, /Packaged/); assert.match(html, /selected \(cohort\)/);
      } else {
        assert.match(html, /10,00 US\$ por 1\.000\.000 token/);
        assert.match(html, /Empaquetada/);
      }
      if (archive) assert.equal(env.timers.length, 0, 'Opening details in an archive does not poll either');
    } finally { env.close(); }
  });
}
