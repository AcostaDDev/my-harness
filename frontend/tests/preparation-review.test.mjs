import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import { genericPreparationPlan, genericConfiguration } from './fixtures/preparation-plan.mjs';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ProjectWorkspace } = await import('../src/workspace.tsx');
const { Preparation } = await import('../src/pages/Preparation.tsx');
delete globalThis.__tsxHookHarness;

function environment(language = 'en', plan = genericPreparationPlan()) {
  const driver = hookHost(), storage = new Map(), requests = [];
  const originals = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const env = { ...driver, plan, requests, catalog: language === 'en' ? en : es, configuration: genericConfiguration(), operation: null };
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
  globalThis.document = { documentElement: {} };
  globalThis.setTimeout = () => 1; globalThis.clearTimeout = () => {};
  globalThis.fetch = async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : undefined;
    requests.push({ path, body, key: options?.headers?.['Idempotency-Key'] });
    if (path.endsWith('/preferences')) return Response.json({ version: 1, ui_language: language, default_work_language: 'en' });
    if (path.endsWith('/preparation')) return Response.json({ available: true, recipe: plan.recipe, prepared: false, project_version: 3, operation: env.operation });
    if (path.endsWith('/preparation/preview')) return Response.json(env.plan);
    if (path.endsWith('/preparation/confirm')) return Response.json({ id: 'synthetic-operation', status: 'QUEUED' });
    assert.fail('Unexpected request: ' + path);
  };
  env.tree = () => el(I18nProvider, null, el(ProjectWorkspace, { project: 'own' }, el(Preparation, { configuration: env.configuration })));
  env.show = () => driver.render(env.tree());
  env.button = key => { const found = env.host.elements.find(e => e.type === 'button' && e.props.children === env.catalog[key]); assert.ok(found, key); return found.props; };
  env.click = async key => { const button = env.button(key); assert.ok(!button.disabled, key); button.onClick(); return env.show(); };
  env.reason = value => {
    const label = env.host.elements.find(e => e.type === 'label' && Array.isArray(e.props.children) && e.props.children[0] === env.catalog['docs.review.reason']);
    assert.ok(label); label.props.children[1].props.onChange({ target: { value } });
  };
  env.tick = checked => {
    const input = env.host.elements.find(e => e.type === 'input' && e.props.type === 'checkbox');
    assert.ok(input); input.props.onChange({ target: { checked } });
  };
  env.close = () => { driver.close(); Object.assign(globalThis, originals); for (const key of ['document', 'localStorage', 'sessionStorage']) delete globalThis[key]; };
  return env;
}

for (const language of ['en', 'es']) test(`generic plan review displays actual effects and commands before consent (${language})`, async () => {
  const env = environment(language);
  try {
    await env.show();
    const html = await env.click('preparation.review');
    assert.ok(!html.includes('undefined'), 'no nonexistent file hash/content is invented');
    assert.ok(!html.includes('<strong></strong>'), 'every generic step has a visible label');
    assert.ok(html.includes('[&quot;python&quot;,&quot;-m&quot;,&quot;synthetic.prepare&quot;,&quot;--name&quot;,&quot;two words&quot;]'));
    assert.ok(html.includes('[&quot;python&quot;,&quot;-m&quot;,&quot;synthetic.tests&quot;,&quot;&lt;escaped&gt;&quot;]'));
    assert.equal(env.button('preparation.confirm_generic').disabled, true);
    assert.equal(env.requests.filter(r => r.body !== undefined).length, 1, 'preview does not confirm/activate');
  } finally { env.close(); }
});

for (const language of ['en', 'es']) test(`generic review retains exact configuration/hash/reason consent and resets on a new review (${language})`, async () => {
  const env = environment(language);
  try {
    await env.show();
    let html = await env.click('preparation.review');
    assert.ok(html.includes(env.catalog['preparation.write_scope']));
    assert.ok(html.includes(env.catalog['preparation.effect.write']));
    assert.ok(!html.includes('wheels') && !html.includes('PyPI') && !html.includes('npm'));
    const labels = [...html.matchAll(/<strong>(.*?)<\/strong>/g)].map(match => match[1]);
    assert.equal(labels.length, 5);
    assert.ok(labels.every(Boolean));
    assert.ok(labels.includes(env.catalog['preparation.step.directories']));
    assert.ok(labels.includes(env.catalog['preparation.step.executor']));
    assert.ok(html.includes('<pre>Write only app/prepare.py and the private preparation files.</pre>'));
    assert.ok(html.includes('synthetic-executor') && html.includes('120 s') && html.includes('SYNTHETIC_VALUE'));
    env.tick(true); await env.show();
    assert.equal(env.button('preparation.confirm_generic').disabled, true, 'consent alone cannot bypass a reason');
    env.reason('Reviewed exact synthetic scope'); await env.show();
    assert.equal(env.button('preparation.confirm_generic').disabled, false);
    await env.click('preparation.review');
    assert.equal(env.button('preparation.confirm_generic').disabled, true, 'a refreshed preview needs fresh consent');
    env.tick(true); await env.show();
    await env.click('preparation.confirm_generic');
    const posts = env.requests.filter(r => r.path.endsWith('/preparation/confirm'));
    assert.equal(posts.length, 1);
    assert.ok(posts[0].key);
    assert.deepEqual(posts[0].body, { change: { contract: 'project-profile-preparation-1', expected_version: 3, mode: 'offline',
      configuration_revision: 2, configuration_sha256: 'c'.repeat(64), proposal_id: 'synthetic-profile', proposal_sha256: 'd'.repeat(64) },
      preview_sha256: 'b'.repeat(64), confirmed: true, reason: 'Reviewed exact synthetic scope' });
    assert.ok(env.requests.every(r => !r.path.endsWith('/activate')), 'preparation never activates configuration');
  } finally { env.close(); }
});

for (const recipe of ['django-recipe-1', 'django-recipe-2', 'typescript-web-recipe-1', 'typescript-web-recipe-2']) {
  test(`fixed recipe file evidence and command argv remain reviewable (${recipe})`, async () => {
    const plan = { ...genericPreparationPlan(), contract: 'project-preparation-1', recipe,
      files: [{ path: 'synthetic.txt', sha256: 'e'.repeat(64), diff: '+fixed synthetic bytes\n', content: 'fixed synthetic bytes\n' }],
      steps: [{ kind: 'command', label: 'Frozen recipe validation', ...(recipe.endsWith('-2') ? { id: 'validate-0' } : {}),
        argv: ['/synthetic/tool', 'test', '--exact'] }, { kind: 'commit', label: 'Frozen technical commit', ...(recipe.endsWith('-2') ? { id: 'commit' } : {}) }] };
    const env = environment('es', plan); env.configuration = undefined;
    try {
      await env.show();
      const html = await env.click('preparation.review');
      assert.ok(html.includes('eeeeeeeeeeee') && html.includes('fixed synthetic bytes'));
      assert.ok(html.includes('[&quot;/synthetic/tool&quot;,&quot;test&quot;,&quot;--exact&quot;]'));
      assert.ok(html.includes(recipe.endsWith('-2') ? 'Validar: tool test --exact' : 'Frozen recipe validation'));
      assert.ok(!html.includes('undefined') && !html.includes('<strong></strong>'));
      assert.deepEqual(env.requests.find(r => r.path.endsWith('/preparation/preview')).body, { expected_version: 3, mode: 'offline' });
    } finally { env.close(); }
  });
}

for (const language of ['en', 'es']) test(`generic active journal names the same kind-based steps (${language})`, async () => {
  const env = environment(language);
  env.operation = { id: 'synthetic-operation', status: 'ACTIVE', version: 1, plan_sha256: 'b'.repeat(64),
    steps: env.plan.steps.map((spec, number) => ({ id: `step-${number}`, number, status: number === 0 ? 'DONE' : number === 1 ? 'STARTED' : 'PENDING', spec })) };
  try {
    const html = await env.show();
    assert.ok(html.includes(env.catalog['preparation.step.directories']));
    assert.ok(html.includes(env.catalog['preparation.step.executor']));
    assert.ok(html.includes('synthetic.tests &lt;escaped&gt;'));
    assert.ok(!html.includes('undefined'));
  } finally { env.close(); }
});
