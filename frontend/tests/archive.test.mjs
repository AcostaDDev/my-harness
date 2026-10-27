import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';

// Install the optional hook host before importing local TSX modules.
globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ServiceModeContext, ServiceModeProvider } = await import('../src/ServiceMode.tsx');
const { Page } = await import('../src/Page.tsx');
const { RunEvidence } = await import('../src/pages/RunEvidence.tsx');
const { parse, href } = await import('../src/router.ts');
delete globalThis.__tsxHookHarness;

const mode = archive => ({ read_only_archive: archive, enabled: false, alive: false, last_error: null,
  ports_configured: false, commit_writer_configured: false });
const hash = 'a'.repeat(64);
const validation = { source_attempt_id: 'attempt-1', evidence: { base_revision: 'base', fingerprint: 'fingerprint' }, entries: [{
  command_id: 'check', requested: 'synthetic check', result: { exit_code: 0, duration_seconds: null }, reports: [{
    path: 'junit.xml', sha256: hash, size_bytes: 123, case_count: 1, coverage: 'synthetic selection',
    status: 'complete', freshness: 'created', diagnostics: [], original_available: true,
  }],
}] };
const run = status => ({ id: 'saved-run', root: '/synthetic/missing-checkout', project_id: null,
  task_id: 'T001', phase_id: 'P001', purpose: 'task', status, stage: 'historical', version: 7,
  revisions: 0, revision_limit: 0, created_at: null, active_job: 'historical-job', locked_by_job: 1,
  actions: ['commit', 'retry_executor', 'revalidate'], commit: { status: 'COMMITTED', commit: '123456789abc' },
  history: { cycle_count: 11, task: {}, acceptance: null, stop: null }, versions: { engine: 'synthetic' },
});
const cycle = { number: 0, verdict: 'ACCEPT', diff_sha256: hash, diff_bytes: 10, changed_paths: ['a.txt'], validation, review: {}, formatting: null };
const metrics = { run_id: 'saved-run', attempt_id: 'attempt-1', root: '/synthetic/missing-checkout', phase_code: 'P001', task_id: 'T001',
  purpose: 'task', number: 1, role: 'executor', status: 'COMPLETE', started_at: null, provider: 'synthetic',
  requested_model: 'requested', reported_models: ['reported'], requested_effort: 'low',
  total_tokens: null, turns: 0, cost_usd: 0, wall_ms: null, provenance: { total_tokens: 'absent', turns: 'reported', cost_usd: 'reported' } };
const page = (items, next_offset = null) => ({ items, next_offset });

function environment(language = 'en', status = 'COMMITTED') {
  const driver = hookHost();
  const requests = [], timers = [], navigation = [], pendingReads = [];
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = callback => { timers.push(callback); return timers.length; };
  globalThis.clearTimeout = () => {};
  globalThis.document = { documentElement: { lang: '' } };
  globalThis.localStorage = { getItem: () => language, setItem: () => {} };
  const saved = JSON.stringify({ path: '/runs/saved-run/actions', body: { action: 'commit', expected_version: 7 }, key: 'pending-synthetic' });
  globalThis.sessionStorage = { getItem: key => { pendingReads.push(key); return key === 'harness-managed-pending-v1' ? saved : null; },
    setItem: () => assert.fail('No saved requests'), removeItem: () => assert.fail('Pending request must be preserved') };
  globalThis.window = { location: { pathname: '/runs/saved-run' }, history: {
    replaceState: (_, __, path) => navigation.push(path), pushState: (_, __, path) => navigation.push(path),
  } };
  globalThis.fetch = async (path, options) => {
    assert.equal(options, undefined, 'Evidence requests must be GET'); requests.push(path);
    const url = new URL(path, 'http://synthetic');
    let data;
    if (url.pathname.endsWith('/supervisor')) data = mode(true);
    else if (url.pathname.endsWith('/unknown')) return new Response('{}', { status: 404 });
    else if (url.pathname.endsWith('/saved-run')) data = run(status);
    else if (url.pathname.endsWith('/jobs')) data = page([{ id: 1, status: 'RECOVERY_REQUIRED', action: 'start', owner_token: 'historical-token' }], 30);
    else if (url.pathname.endsWith('/attempts') && url.pathname.includes('/metrics/')) data = page([metrics], 10);
    else if (url.pathname.endsWith('/attempts')) data = page([{ id: 'attempt-1', number: 1, role: 'executor', status: 'COMPLETE' }], 30);
    else if (url.pathname.endsWith('/events')) data = { items: [{ sequence: 101, kind: 'historical', payload: {}, recorded_at: null }], cursor: 101, has_more: !url.searchParams.get('after') || url.searchParams.get('after') === '0' };
    else if (url.pathname.endsWith('/cycles')) data = page([cycle], 10);
    else if (url.pathname.endsWith('/diff')) data = { sha256: hash, size_bytes: 10, offset: 0, next_offset: null, text: '+synthetic' };
    else if (url.pathname.endsWith('/reports/0')) data = { items: [{ id: 'case-1', suite: ['suite'], name: 'synthetic case', result: 'passed', error: null }], next_offset: null, command_id: 'check', source_attempt_id: 'attempt-1', evidence: {} };
    else if (url.pathname.endsWith('/logs')) data = [{ stream: 'stdout', state: 'purged', size_bytes: 0 }];
    else assert.fail(`Unexpected read: ${path}`);
    return Response.json(data);
  };
  return { ...driver, requests, timers, navigation, pendingReads,
    tree: (route, archive = true) => el(I18nProvider, null, el(ServiceModeContext.Provider, { value: archive === undefined ? undefined : mode(archive) }, el(Page, { route: parse(route) }))),
    close() {
      driver.close(); Object.assign(globalThis, original);
      for (const key of ['document', 'localStorage', 'sessionStorage', 'window']) delete globalThis[key];
    },
  };
}

for (const language of ['en', 'es']) {
  test(`archive run reads evidence, JUnit, streams and metrics without operational effects (${language})`, async () => {
    const env = environment(language);
    try {
      const tree = env.tree('/runs/saved-run');
      let html = await env.render(tree);
      assert.match(html, /123456789abc/);
      assert.match(html, /missing-checkout/);
      assert.match(html, /junit.xml/);
      assert.match(html, /requested/); assert.match(html, /reported/);
      assert.match(html, /RECOVERY_REQUIRED/);
      assert.doesNotMatch(html, /type="checkbox"|owner_token.*<input|decision-pending|run-decision/);
      assert.equal(env.navigation.length, 0);
      assert.deepEqual(env.pendingReads, []);
      assert.equal(env.timers.length, 0, 'Historical activity never schedules execution polling');
      assert.ok(env.requests.includes('/api/managed/metrics/attempts?run_id=saved-run&offset=0&limit=10'));
      assert.ok(env.requests.every(path => !path.includes('project_id') && !path.includes('/projects')));
      assert.ok(env.host.elements.some(({ type, props }) => type === 'a' && props.href.endsWith('/original')));
      // Open the actual shared diff and JUnit components and inspect their resulting requests/render.
      env.host.elements.find(e => e.type === 'details' && e.props.onToggle).props.onToggle({ currentTarget: { open: true } });
      env.host.elements.find(e => e.type === 'button' && e.props['aria-expanded'] === false).props.onClick();
      env.host.elements.find(e => e.type === 'button' && e.props.children === (language === 'en' ? 'Check original logs' : 'Comprobar originales de logs')).props.onClick();
      html = await env.render(tree);
      assert.match(html, /synthetic case/);
      assert.match(html, /\+synthetic/);
      assert.ok(env.requests.some(path => path.includes(`/diff?offset=0&sha256=${hash}`)));
      assert.ok(env.requests.some(path => path.includes('/reports/0?offset=0&limit=50')));
      assert.ok(env.requests.some(path => path.endsWith('/attempts/attempt-1/logs')));
      const eventsNav = env.host.elements.find(e => e.type === 'nav' && e.props['aria-label'] === (language === 'en' ? 'Confirmed events' : 'Eventos confirmados'));
      eventsNav.props.children[1].props.onClick();
      await env.render(tree);
      assert.ok(env.requests.some(path => path.endsWith('/events?after=101&limit=50')));
      env.host.elements.find(e => e.type === 'nav' && e.props['aria-label'] === (language === 'en' ? 'Confirmed events' : 'Eventos confirmados')).props.children[0].props.onClick();
      await env.render(tree);
      assert.equal(env.requests.filter(path => path.endsWith('/events?after=0&limit=50')).length, 2);
      // Metrics pages remain run-scoped; event cursors may have gaps and must round-trip exactly.
      const metricNav = env.host.elements.filter(e => e.type === 'nav' && e.props['aria-label'] === (language === 'en' ? 'Attempt pages' : 'Páginas de intentos')).at(-1);
      const metricNext = metricNav.props.children[1]; metricNext.props.onClick();
      await env.render(tree);
      assert.ok(env.requests.some(path => path.includes('metrics/attempts?run_id=saved-run&offset=10')));
    } finally { env.close(); }
  });
}

for (const status of ['QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED', 'REVISION_LIMIT']) {
  test(`archive preserves ${status} without timers or write controls`, async () => {
    const env = environment();
    try {
      const html = await env.render(el(I18nProvider, null, el(RunEvidence, { run: run(status), jobs: page([{ id: 1, status: 'RECOVERY_REQUIRED' }]),
        attempts: page([]), cycles: page([]), events: [], offset: 0, cycleOffset: 0, jobOffset: 0,
        setOffset() {}, setCycleOffset() {}, setJobOffset() {} })));
      assert.match(html, new RegExp(`title="${status}"`));
      assert.doesNotMatch(html, /<input|run-decision|<button/);
      assert.deepEqual(env.requests, []); assert.deepEqual(env.timers, []);
    } finally { env.close(); }
  });
}

test('archive home, blocked direct routes, missing run and loading gate never mount workspace', async () => {
  for (const path of ['/', '/projects/new', '/preferences', '/projects/p/settings', '/projects/p/phases/P001/tasks/T001/runs/saved-run',
    '/projects/p/chat', '/projects/p/docs', '/projects/p/onboarding', '/projects/p/setup', '/projects/p/phases/P001/plan', '/runs/unknown']) {
    const env = environment('es');
    try {
      const html = await env.render(env.tree(path));
      assert.doesNotMatch(html, /decision-pending|my-harness serve --config/);
      if (path === '/') assert.match(html, /Id de run/);
      else if (path !== '/runs/unknown') assert.match(html, /no está disponible/);
      assert.ok(env.requests.length === 0 || path === '/runs/unknown');
      assert.deepEqual(env.pendingReads, []);
    } finally { env.close(); }
  }
});

test('ordinary short route retains canonical redirect and no-project empty state', async () => {
  for (const project_id of [null, 'registered']) {
    const env = environment(); const fetch = globalThis.fetch;
    globalThis.fetch = async (...args) => {
      const response = await fetch(...args); return Response.json({ ...await response.json(), project_id });
    };
    try {
      const html = await env.render(env.tree('/runs/saved-run', false));
      assert.deepEqual(env.navigation, project_id ? ['/projects/registered/phases/P001/tasks/T001/runs/saved-run'] : []);
      if (!project_id) assert.match(html, /without a registered project/i);
      assert.equal(env.requests.length, 1);
    } finally { env.close(); }
  }
});

test('persistent archive signal is loaded before routing and stops supervisor polling', async () => {
  const env = environment();
  try {
    const tree = el(I18nProvider, null, el(ServiceModeProvider, null, el(Page, { route: { name: 'home' } })));
    assert.match(await env.render(tree), /Run id/);
    assert.deepEqual(env.requests, ['/api/managed/supervisor']);
    assert.deepEqual(env.timers, []);
    assert.equal(href({ name: 'run-short', run: 'id #?ñ' }), '/runs/id%20%23%3F%C3%B1');
  } finally { env.close(); }
});

for (const language of ['en', 'es']) {
  test(`incomplete archive run and absent metrics stay absent (${language})`, async () => {
    const env = environment(language);
    const fetch = globalThis.fetch;
    globalThis.fetch = async (path, options) => {
      if (path.includes('/metrics/attempts')) { env.requests.push(path); return Response.json(page([])); }
      if (path.endsWith('/saved-run')) return Response.json({ ...run('QUEUED'), commit: null, history: { cycle_count: 0 } });
      return fetch(path, options);
    };
    try {
      const html = await env.render(env.tree('/runs/saved-run'));
      assert.doesNotMatch(html, /123456789abc|junit.xml|synthetic check/);
      assert.match(html, language === 'en' ? /No attempts/ : /Sin intentos/);
      assert.match(html, /title="QUEUED"/);
      assert.equal(env.timers.length, 0);
    } finally { env.close(); }
  });
}

test('ordinary project run retains decisions, recovery, permissions and polling after evidence extraction', async () => {
  const env = environment(); const fetch = globalThis.fetch;
  globalThis.sessionStorage = { getItem: () => null };
  const path = '/projects/registered/phases/P001/tasks/T001/runs/saved-run';
  globalThis.window.location.pathname = path;
  globalThis.fetch = async (path, options) => {
    if (path.endsWith('/permissions')) { env.requests.push(path); return Response.json([]); }
    const response = await fetch(path, options);
    return path.endsWith('/saved-run') ? Response.json({ ...await response.json(), project_id: 'registered' }) : response;
  };
  try {
    const html = await env.render(env.tree(path, false));
    assert.match(html, /run-decision/);
    assert.match(html, /type="checkbox"/);
    assert.ok(env.requests.some(path => path.endsWith('/permissions')));
    assert.ok(env.timers.length > 0);
    assert.deepEqual(env.navigation, []);
  } finally { env.close(); }
});

test('blocked configuration retains run consultation without project actions, pending requests or polling', async () => {
  for (const configuration_mode of ['UNCONFIGURED', 'INVALID', 'RESTART_REQUIRED', 'RECOVERY_REQUIRED']) {
    for (const path of ['/runs/saved-run', '/projects/registered/phases/P001/tasks/T001/runs/saved-run']) {
      const env = environment();
      try {
        const tree = el(I18nProvider, null, el(ServiceModeContext.Provider, { value: { ...mode(false), configuration_mode } }, el(Page, { route: parse(path) })));
        const html = await env.render(tree);
        assert.match(html, /123456789abc/);
        assert.doesNotMatch(html, /run-decision|decision-pending|type="checkbox"/);
        assert.deepEqual(env.pendingReads, []); assert.deepEqual(env.navigation, []); assert.deepEqual(env.timers, []);
        assert.ok(env.requests.every(request => !request.includes('/projects')));
      } finally { env.close(); }
    }
  }
});

test('archive home submits an encoded run link without making a request', async () => {
  const env = environment();
  try {
    const tree = env.tree('/');
    await env.render(tree);
    env.host.elements.find(e => e.type === 'input').props.onChange({ target: { value: 'id #?ñ' } });
    await env.render(tree);
    env.host.elements.find(e => e.type === 'form').props.onSubmit({ preventDefault() {} });
    assert.deepEqual(env.navigation, ['/runs/id%20%23%3F%C3%B1']);
    assert.deepEqual(env.requests, []);
  } finally { env.close(); }
});

test('unresolved mode cannot mount ordinary pages or read pending work', async () => {
  const env = environment();
  try {
    const tree = el(I18nProvider, null, el(ServiceModeContext.Provider, { value: undefined }, el(Page, { route: parse('/projects/registered') })));
    await env.render(tree);
    assert.deepEqual(env.pendingReads, []); assert.deepEqual(env.requests, []);
  } finally { env.close(); }
});

for (const language of ['en', 'es']) {
  test(`failed archive evidence reads show errors instead of empty results (${language})`, async () => {
    const env = environment(language); const fetch = globalThis.fetch;
    globalThis.fetch = async (path, options) => path.includes('/metrics/attempts') || path.endsWith('/events?after=0&limit=50')
      ? Response.json({ detail: { code: 'synthetic_failure', diagnostic: 'synthetic failure' } }, { status: 500 }) : fetch(path, options);
    try {
      const html = await env.render(env.tree('/runs/saved-run'));
      assert.match(html, /synthetic failure/);
      assert.doesNotMatch(html, language === 'en' ? /No attempts/ : /Sin intentos/);
      assert.equal(env.timers.length, 0);
    } finally { env.close(); }
  });
}
