import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };
globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { KnowledgePage } = await import('../src/pages/Knowledge.tsx');
const { Page } = await import('../src/Page.tsx');
const { ServiceModeContext } = await import('../src/ServiceMode.tsx');
delete globalThis.__tsxHookHarness;
const date = '2026-10-31T12:00:00Z';
function environment({ project, language = 'en', page = false, mode = {} } = {}) {
  const driver = hookHost(), calls = [], storage = new Map(), original = globalThis.fetch;
  globalThis.document = { documentElement: { getAttribute: () => null } };
  globalThis.window = { location: { hash: '' }, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) };
  const env = { ...driver, calls, storage, catalog: language === 'es' ? es : en, fail: '', defer: null };
  const revision = (kp, number) => ({ id: `${kp}-r${number}`, number, accepted_at: date, origin: 'owner_confirmed', actor: {}, reason: 'Synthetic' });
  const members = [
    { item_id: 'requirement', kind: 'requirement', code: 'R001', document: null, version: 1, provenance: 'known', root_position: null, content: { title: 'Work language title', statement: 'Work language statement', status: 'active' } },
    { item_id: 'task', kind: 'task', code: 'P001-T001', document: null, version: 1, provenance: 'known', content: { expected_result: 'Work language result', status: 'planned' } },
    { item_id: 'decision', kind: 'decision', code: 'D001', document: null, version: 1, provenance: 'known', content: { historical_status: 'Work language history', status: 'accepted' } },
    { item_id: 'section', kind: 'section', code: 'diagram', document: 'data_model', version: 1, provenance: 'known', content: { body: 'Work language body', status: 'active', format: 'markdown', target: 'agents' } },
  ];
  const links = [{ kind: 'addresses', source_item_id: 'task', target_item_id: 'requirement', position: null, qualifier: null }];
  globalThis.fetch = async (path, options) => {
    const url = new URL(path, 'http://local'), p = url.pathname; calls.push({ path, options });
    if (env.fail && path.includes(env.fail)) { env.fail = ''; throw Error('Transient initial read'); }
    if (env.defer?.match(path)) return new Promise(resolve => { env.defer.resolve = value => resolve(Response.json(value)); });
    if (p.endsWith('/preferences')) return Response.json({ ui_language: language });
    if (p.endsWith('/projects/own/knowledge')) return Response.json({ knowledge_project_id: 'a', revision: revision('a', 2) });
    if (p.endsWith('/knowledge/projects')) return Response.json({ items: ['a','b'].map(id => ({ id, root: `/synthetic/${id}`, head: { number: 2 } })) });
    if (/\/knowledge\/projects\/[ab]$/.test(p)) return Response.json({ revision: revision(p.at(-1), 2) });
    const kp = p.match(/\/knowledge\/projects\/([ab])/ )?.[1] ?? 'a';
    if (p.endsWith('/history')) return Response.json({ revisions: [revision(kp, 2), revision(kp, 1)], drafts: [{ id: 'draft', created_at: date }], total: 2 });
    if (p.endsWith('/judge/requests')) return Response.json({ items: [] });
    const number = Number(p.match(/\/revisions\/(\d+)/)?.[1]);
    if (number && !p.endsWith('/search')) return Response.json({ revision: revision(kp, number), members, links, contexts: [], contexts_truncated: false });
    if (p.endsWith('/search')) {
      const expected = `${kp}:${number}:${url.searchParams.get('query')}:page2`;
      const cursor = url.searchParams.get('cursor');
      assert.ok(cursor === null || cursor === expected, `foreign cursor ${cursor} for ${expected}`);
      return Response.json({ exposures: [{ identity: { item_id: cursor ? 'task' : 'requirement' } }], page: cursor ? {} : { next_cursor: expected } });
    }
    if (p.endsWith('/drafts/draft')) return Response.json({ draft_id: 'draft', status: 'DRAFT', base_revision_id: 'a-r2', members: [members[0]], links, draft_sha256: 'a'.repeat(64) });
    if (p.endsWith('/adoption/preview')) return Response.json({ draft_id: 'draft', base_revision_id: 'a-r2', reason_required: false, classification: [], comparison: { items: [{ before: members[1], after: members[2] }], added_links: links, removed_links: [] }, impact: { contexts: [{ invocation_id: 'i', attempt_id: 'at', run_id: 'run' }], contexts_truncated: true } });
    throw Error(path);
  };
  const component = page ? el(ServiceModeContext.Provider, { value: { read_only_archive: false, ports_configured: true, configuration_mode: null, ...mode } }, el(Page, { route: { name: 'project-knowledge', project: 'own' } })) : el(KnowledgePage, { project });
  env.tree = el(I18nProvider, null, component);
  env.render = async () => { let html; for (let i = 0; i < 3; i++) html = await driver.render(env.tree); return html; };
  env.click = key => { const b = driver.host.elements.find(e => e.type === 'button' && e.props.children === env.catalog[key]); assert.ok(b, key); assert.ok(!b.props.disabled); b.props.onClick(); };
  env.select = value => driver.host.elements.find(e => e.type === 'select').props.onChange({ target: { value } });
  env.revision = number => { const b = driver.host.elements.find(e => e.type === 'button' && Array.isArray(e.props.children) && e.props.children[0] === '#' && e.props.children[1] === number); assert.ok(b, `revision ${number}`); b.props.onClick(); };
  env.query = text => driver.host.elements.find(e => e.type === 'input').props.onChange({ target: { value: text } });
  env.search = () => driver.host.elements.find(e => e.type === 'form').props.onSubmit({ preventDefault() {} });
  env.close = () => { driver.close(); globalThis.fetch = original; for (const k of ['document','window','MutationObserver','sessionStorage','localStorage']) delete globalThis[k]; };
  return env;
}
for (const mode of [null, 'READY', 'UNCONFIGURED', 'INVALID', 'ARCHIVE']) test(`Page preserves knowledge lane for ${mode}`, async () => {
  const editable = mode === null || mode === 'READY';
  const env = environment({ page: true, mode: mode === 'ARCHIVE' ? { read_only_archive: true } : { configuration_mode: mode } });
  try { const html = await env.render(); assert.equal(env.calls.some(c => c.path.endsWith('/projects/own/knowledge')), editable); assert.equal(html.includes(en['knowledge.open']), editable); assert.equal(html.includes(en['knowledge.project'] + '<select'), !editable); assert.ok(env.calls.every(c => !c.options)); } finally { env.close(); }
});
for (const [project, failed] of [[undefined, '/knowledge/projects?'], ['own', '/knowledge/projects?'], ['own', '/projects/own/knowledge']]) test(`recover initial ${failed} without browser reload`, async () => {
  const env = environment({ project }); env.fail = failed;
  const pending = JSON.stringify({ path: '/projects/own/knowledge/drafts/draft/adopt', body: { preview_sha256: 'sealed' }, key: 'same-key' });
  env.storage.set('harness-confirmation-v1', pending);
  if (project) env.storage.set('knowledge-input-v1/own', JSON.stringify({ code: 'R009', kind: 'requirement', document: 'specification', position: '', content: { title: 'Unsaved title', statement: 'Unsaved work', status: 'active' } }));
  try { await env.render(); assert.equal(env.calls.filter(c => c.path.includes(failed)).length, 1); env.click('knowledge.reload'); let html = await env.render(); assert.ok(env.calls.filter(c => c.path.includes(failed)).length >= 2); assert.ok(html.includes(project ? en['knowledge.open'] : '/synthetic/a')); assert.equal(env.storage.get('harness-confirmation-v1'), pending); if (project) assert.equal(JSON.parse(env.storage.get('knowledge-input-v1/own')).content.statement, 'Unsaved work'); assert.ok(env.calls.every(c => !c.options)); } finally { env.close(); }
});
test('search cursors bind project, revision and query and old responses cannot restore them', async () => {
  const env = environment();
  try {
    await env.render(); env.select('a'); await env.render(); env.query('Work'); await env.render(); env.search(); await env.render(); env.search(); await env.render();
    assert.ok(env.calls.at(-1).path.includes('cursor=a%3A2%3AWork%3Apage2'));
    env.query('Work'); await env.render(); env.search(); await env.render(); env.revision(1); await env.render(); env.search(); await env.render();
    assert.ok(!env.calls.at(-1).path.includes('cursor=')); assert.ok(env.calls.at(-1).path.includes('/revisions/1/'));
    env.select('b'); await env.render(); env.search(); await env.render(); assert.ok(!env.calls.at(-1).path.includes('cursor='));
    env.defer = { match: p => p.includes('/search?') }; env.search(); await env.render();
    const deferred = env.defer; env.select('a'); await env.render(); deferred.resolve({ exposures: [], page: { next_cursor: 'b:2:Work:page2' } }); env.defer = null; await env.render();
    env.search(); await env.render(); assert.ok(!env.calls.at(-1).path.includes('cursor='));
  } finally { env.close(); }
});
test('Spanish consultation and preview use labels, localized dates and explicit truncated context', async () => {
  const env = environment({ project: 'own', language: 'es' });
  try {
    let html = await env.render();
    for (const label of ['Enunciado', 'Resultado esperado', 'Estado histórico', 'Requisito', 'Modelo de datos']) assert.ok(html.includes(label), label);
    assert.ok(!/<h4>(statement|expected_result|historical_status)<\/h4>/.test(html));
    const expectedDate = new Date(date).toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' }); assert.ok(html.split(expectedDate).length >= 5, 'history, draft and inspection dates use the visual locale');
    const d = env.host.elements.find(e => e.type === 'button' && Array.isArray(e.props.children) && e.props.children[0] === es['knowledge.draft']); d.props.onClick(); await env.render();
    const kindLabel = env.host.elements.find(e => e.type === 'label' && e.props.children[0] === es['knowledge.kind']);
    kindLabel.props.children[1].props.onChange({ target: { value: 'section' } }); await env.render();
    assert.ok(env.host.elements.some(e => e.type === 'option' && e.props.value === 'data_model' && e.props.children === 'Modelo de datos'));
    const requirement = env.host.elements.find(e => e.type === 'label' && e.props.children[0] === es['knowledge.kind']);
    requirement.props.children[1].props.onChange({ target: { value: 'requirement' } }); await env.render();
    env.click('knowledge.preview'); html = await env.render();
    assert.ok(html.includes(es['knowledge.truncated'])); assert.ok(html.includes(es['knowledge.unassociated']));
    assert.ok(html.includes('Resultado esperado')); assert.ok(html.includes('Estado histórico')); assert.ok(!/<h4>(expected_result|historical_status)<\/h4>/.test(html));
    assert.ok(html.includes(es['knowledge.label.relation.addresses']));
    assert.ok(!html.includes('→ addresses →'));
    assert.ok(html.includes('Work language result')); assert.ok(html.includes('Work language history'));
  } finally { env.close(); }
});

test('late revision and project loads cannot replace the current consultation', async () => {
  const env = environment();
  try {
    await env.render(); env.select('a'); await env.render();
    env.defer = { match: p => p.endsWith('/a/revisions/1') };
    env.revision(1); await env.render(); const oldRevision = env.defer;
    env.select('b'); await env.render();
    oldRevision.resolve({ revision: { number: 1 }, members: [{ item_id: 'old', kind: 'requirement', code: 'R999', content: { statement: 'Late wrong revision' } }], links: [], contexts: [] });
    env.defer = null; let html = await env.render(); assert.ok(!html.includes('Late wrong revision'));
    env.defer = { match: p => p.endsWith('/a/revisions/2') }; env.select('a'); await env.render(); const oldProject = env.defer;
    env.select('b'); await env.render();
    oldProject.resolve({ revision: { number: 2 }, members: [{ item_id: 'old', kind: 'requirement', code: 'R999', content: { statement: 'Late wrong project' } }], links: [], contexts: [] });
    env.defer = null; html = await env.render(); assert.ok(!html.includes('Late wrong project'));
    env.query('Work'); await env.render(); env.search(); await env.render(); assert.ok(env.calls.at(-1).path.includes('/projects/b/revisions/2/search'));
  } finally { env.close(); }
});

test('late search results after editing the query do not restore the old cursor', async () => {
  const env = environment();
  try {
    await env.render(); env.select('a'); await env.render(); env.query('Work'); await env.render();
    env.defer = { match: p => p.includes('/search?') }; env.search(); await env.render(); const oldSearch = env.defer;
    env.query('Changed'); await env.render(); oldSearch.resolve({ exposures: [], page: { next_cursor: 'a:2:Work:page2' } });
    env.defer = null; await env.render(); env.search(); await env.render();
    assert.ok(env.calls.at(-1).path.includes('query=Changed')); assert.ok(!env.calls.at(-1).path.includes('cursor='));
  } finally { env.close(); }
});

test('adoption preview announces a truncated association list independently of READY', async () => {
  const env = environment({ project: 'own' });
  try {
    await env.render(); const d = env.host.elements.find(e => e.type === 'button' && Array.isArray(e.props.children) && e.props.children[0] === en['knowledge.draft']);
    d.props.onClick(); await env.render(); env.click('knowledge.preview'); const html = await env.render();
    assert.ok(html.includes(en['knowledge.truncated'])); assert.ok(html.includes(en['knowledge.unassociated']));
    assert.ok(html.includes(en['knowledge.impact'])); assert.ok(html.includes('/runs/run'));
  } finally { env.close(); }
});
