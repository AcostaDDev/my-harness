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
delete globalThis.__tsxHookHarness;

for (const [language, catalog] of [['en', en], ['es', es]]) test(`knowledge editor interaction and exact retry (${language})`, async () => {
  let driver = hookHost();
  const store = new Map(), calls = [], saved = new Map();
  const original = globalThis.fetch;
  globalThis.document = { documentElement: { dataset: {}, getAttribute: () => null } };
  globalThis.window = { location: { hash: "" }, addEventListener() {}, removeEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: k => store.get(k) ?? null, setItem: (k,v) => store.set(k,v), removeItem: k => store.delete(k) };
  let draft = { draft_id: 'draft', status: 'DRAFT', base_revision_id: null, draft_sha256: 'a'.repeat(64), members: [], links: [], opener: {} };
  let lose = false;
  globalThis.fetch = async (path, options) => {
    const body = options?.body && JSON.parse(options.body); calls.push({ path, body, key: options?.headers?.['Idempotency-Key'] });
    if (!options) {
      if (path.endsWith('/preferences')) return Response.json({ visual_language: language });
      if (path.endsWith('/projects/own/knowledge')) return Response.json({ knowledge_project_id: 'kp', revision: null });
      if (path.includes('/knowledge/projects?')) return Response.json({ items: [{ id: 'kp', root: '/synthetic', head: null }] });
      if (path.endsWith('/knowledge/projects/kp')) return Response.json({ revision: null });
      if (path.includes('/history?')) return Response.json({ revisions: [], drafts: [], total: 0 });
      if (path.includes('/judge/requests?')) return Response.json({ items: [] });
      if (path.endsWith('/drafts/draft')) return Response.json(draft);
      throw Error(path);
    }
    if (path.endsWith('/adoption/preview')) return Response.json({ draft_id: 'draft', base_revision_id: null, draft_sha256: draft.draft_sha256, preview_sha256: 'b'.repeat(64), reason_required: true, classification: [], comparison: { items: draft.members.map(after => ({ before: null, after })), added_links: [], removed_links: [] } });
    const key = options.headers['Idempotency-Key']; assert.ok(key);
    if (saved.has(key)) return Response.json(saved.get(key));
    let result = { draft_id: 'draft', knowledge_project_id: 'kp' };
    if (path.endsWith('/changes')) {
      const c = body.changes[0];
      if (c.op === 'link') draft = { ...draft, links: [...draft.links, c] };
      else draft = { ...draft, draft_sha256: 'c'.repeat(64), members: [...draft.members.filter(m => m.code !== c.code), { ...c, item_id: c.code, version: 1, root_position: c.root_position ?? null }] };
    }
    if (path.endsWith('/adopt')) result = { number: 1 };
    saved.set(key, result);
    if (lose) { lose = false; throw TypeError('Lost response'); }
    return Response.json(result);
  };
  const tree = el(I18nProvider, null, el(KnowledgePage, { project: 'own' }));
  const render = () => driver.render(tree);
  const button = key => { const found = driver.host.elements.find(e => e.type === 'button' && e.props.children === catalog[key]); assert.ok(found, key); return found.props; };
  const click = key => { assert.equal(!!button(key).disabled, false, key); button(key).onClick(); };
  const input = (key, value) => { const label = driver.host.elements.find(e => e.type === 'label' && e.props.children[0] === catalog[key]); assert.ok(label, key); label.props.children[1].props.onChange({ target: { value } }); };
  try {
    await render(); click('knowledge.open'); await render();
    input('knowledge.code', 'R001'); input('knowledge.field.title', 'Synthetic title'); input('knowledge.field.statement', '**Synthetic requirement**'); await render();
    click('knowledge.save'); await render();
    for (const [kind, code, fields] of [
      ['criterion', 'C001', ['statement']], ['phase', 'P001', ['title','objective']],
      ['task', 'P001-T001', ['title','problem','expected_result','evidence','subtasks']],
      ['decision', 'D001', ['title','context','decision','alternatives','consequences']],
      ['section', 'instructions', ['title','body']],
    ]) {
      click('knowledge.new'); await render(); input('knowledge.kind', kind); await render();
      input('knowledge.code', code);
      for (const field of fields) { input('knowledge.field.' + field, 'Synthetic ' + field); await render(); }
      if (kind === 'section') { input('knowledge.document', 'instructions'); input('knowledge.position', '0'); }
      await render(); click('knowledge.save'); await render();
      const command = calls.filter(c => c.path.endsWith('/changes')).at(-1).body.changes[0];
      assert.equal(command.kind, kind); assert.equal(command.code, code);
      assert.equal(command.content[fields[0]], 'Synthetic ' + fields[0]);
    }
    const relationshipInput = (key, value) => {
      const label = driver.host.elements.filter(e => e.type === 'label' && e.props.children[0] === catalog[key]).at(-1);
      label.props.children[1].props.onChange({ target: { value } });
    };
    for (const [kind, source, target] of [['part_of','P001-T001','P001'], ['criterion_of','C001','R001'], ['addresses','P001-T001','R001']]) {
      relationshipInput('knowledge.kind', kind); relationshipInput('knowledge.source', source); relationshipInput('knowledge.target', target);
      await render(); click('knowledge.link'); await render();
      const link = calls.filter(c => c.path.endsWith('/changes')).at(-1).body.changes[0];
      assert.equal(link.kind, kind); assert.equal(link.source_item_id, source); assert.equal(link.target_item_id, target);
      assert.equal(link.position, kind === 'addresses' ? null : 0);
    }
    click('knowledge.preview'); await render();
    assert.equal(button('knowledge.adopt').disabled, true);
    input('knowledge.reason', 'Owner review'); await render(); lose = true;
    click('knowledge.adopt'); await render();
    assert.ok(store.get('harness-confirmation-v1'));
    driver.close(); driver = hookHost(); await render();
    click('knowledge.retry'); await render();
    const adopted = calls.filter(c => c.path.endsWith('/adopt'));
    assert.equal(adopted.length, 2); assert.equal(adopted[0].key, adopted[1].key); assert.deepEqual(adopted[0].body, adopted[1].body);
    assert.equal(store.has('harness-confirmation-v1'), false);
    assert.equal(adopted[0].body.preview_sha256, 'b'.repeat(64));
  } finally {
    driver.close(); globalThis.fetch = original;
    for (const k of ['document','window','MutationObserver','sessionStorage','localStorage']) delete globalThis[k];
  }
});

test('persisted consultation uses only reads, history and search without a workspace', async () => {
  const driver = hookHost(), calls = [], store = new Map(), original = globalThis.fetch;
  globalThis.localStorage = { getItem: () => 'en' };
  globalThis.sessionStorage = { getItem: k => store.get(k) ?? null, setItem: (k,v) => store.set(k,v), removeItem: k => store.delete(k) };
  globalThis.document = { documentElement: { getAttribute: () => null } };
  globalThis.window = { location: { hash: '' }, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  const revision = { id: 'accepted', number: 1, actor: { principal: 'owner' }, origin: 'owner_confirmed', reason: 'Synthetic review', accepted_at: '2026-10-31', counts: {} };
  const member = { item_id: 'item', kind: 'requirement', code: 'R001', document: null, version: 1, provenance: 'unknown', content: { title: 'Synthetic history', statement: '<script>inert</script>', status: 'active' } };
  let fail = false;
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options }); assert.equal(options, undefined);
    if (fail) { fail = false; throw TypeError('Synthetic read failure'); }
    if (path.endsWith('/preferences')) return Response.json({ visual_language: 'en' });
    if (path.includes('/knowledge/projects?')) return Response.json({ items: [{ id: 'kp', root: '/absent-checkout', head: { number: 1 } }] });
    if (path.endsWith('/kp')) return Response.json({ revision });
    if (path.includes('/history?')) return Response.json({ revisions: [revision], drafts: [], total: 1 });
    if (path.includes('/judge/requests?')) return Response.json({ items: [] });
    if (path.endsWith('/revisions/1')) return Response.json({ revision, members: [member], links: [], contexts: [] });
    if (path.includes('/search?')) return Response.json({ exposures: [{ identity: { item_id: 'item' } }], page: {} });
    throw Error(path);
  };
  const tree = el(I18nProvider, null, el(KnowledgePage));
  try {
    await driver.render(tree);
    const select = driver.host.elements.find(e => e.type === 'select'); select.props.onChange({ target: { value: 'kp' } });
    let html = await driver.render(tree); assert.match(html, /Synthetic history/); assert.ok(!html.includes('<script>inert</script>'));
    assert.ok(!driver.host.elements.some(e => e.type === 'button' && e.props.children === en['knowledge.open']));
    const input = driver.host.elements.find(e => e.type === 'input'); input.props.onChange({ target: { value: 'history' } });
    await driver.render(tree); driver.host.elements.find(e => e.type === 'form').props.onSubmit({ preventDefault() {} }); await driver.render(tree);
    assert.ok(calls.some(c => c.path.includes('/search?query=history')));
    fail = true; driver.host.elements.find(e => e.type === 'button' && e.props.children === en['knowledge.reload']).props.onClick();
    html = await driver.render(tree); assert.match(html, /Synthetic read failure/);
    driver.host.elements.find(e => e.type === 'button' && e.props.children === en['knowledge.reload']).props.onClick();
    html = await driver.render(tree); assert.match(html, /Synthetic history/); assert.ok(calls.every(c => c.options === undefined));
    assert.equal(store.has('harness-confirmation-v1'), false);
  } finally {
    driver.close(); globalThis.fetch = original;
    for (const k of ['document','window','MutationObserver','sessionStorage','localStorage']) delete globalThis[k];
  }
});
