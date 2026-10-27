import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import { translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

globalThis.__tsxHookHarness = {};
const { applicableDocuments, reviewDocumentProposals, applyReviewedDocuments } = await import('../src/proposal-batch.ts');
const { I18nProvider } = await import('../src/Language.tsx');
const { ProjectWorkspace } = await import('../src/workspace.tsx');
const { ProposalBatch } = await import('../src/pages/ProposalBatch.tsx');
delete globalThis.__tsxHookHarness;

const BASE = '/projects/own/planning/c1';
const hash = n => String(n).repeat(64);
const proposal = (n, extras = {}) => ({ id: `p${n}`, path: `docs/flow-${n}.md`, kind: 'draft', status: 'PROPOSED',
  content: `# Synthetic document ${n}\n`, reason: `Synthetic proposal ${n}`, base_sha256: null,
  content_sha256: hash(n), proposal_sha256: hash(n + 3), actions: ['apply'], ...extras });
function environment() {
  const original = globalThis.fetch;
  const env = { requests: [], files: new Map(), fail: null, concurrent: false,
    conversation: { id: 'c1', kind: 'onboarding', version: 7, created: false, actions: ['edit_draft'], turns: [],
      proposals: [proposal(1), proposal(2), proposal(3), proposal(4, { kind: 'profile', path: null }),
        proposal(5, { kind: 'plan' }), proposal(6, { status: 'SUPERSEDED' })] } };
  globalThis.fetch = async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : undefined;
    env.requests.push({ url, body });
    if (url === '/api/managed/preferences') return Response.json({ version: 1, ui_language: env.language ?? 'en', default_work_language: 'en' });
    if (url === '/api/managed' + BASE) return Response.json(env.conversation);
    if (url.includes('/drafts/content?path=')) {
      const path = decodeURIComponent(url.split('path=')[1]);
      return env.files.has(path) ? Response.json(env.files.get(path))
        : Response.json({ detail: { code: 'not_found' } }, { status: 404 });
    }
    const id = url.match(/\/proposals\/(p\d+)\/apply$/)?.[1];
    assert.ok(id, url);
    const p = env.conversation.proposals.find(p => p.id === id);
    const current = env.files.get(p.path)?.sha256 ?? null;
    if (body.expected_version !== env.conversation.version || body.proposal_sha256 !== p.proposal_sha256
        || current !== p.base_sha256 && current !== p.content_sha256 || env.fail === id) {
      return Response.json({ detail: { code: 'draft_changed', diagnostic: 'Synthetic conflict' } }, { status: 409 });
    }
    p.status = 'APPLIED'; p.actions = [];
    env.files.set(p.path, { path: p.path, content: p.content, sha256: p.content_sha256 });
    env.conversation.version += 1;
    if (env.concurrent === id) env.conversation.version += 1;
    if (env.lose === id) throw new TypeError('Synthetic lost response');
    return Response.json(env.conversation);
  };
  env.posts = () => env.requests.filter(r => r.body);
  env.close = () => { globalThis.fetch = original; };
  return env;
}

test('joint review is read-only and excludes profiles, plans, historical proposals and closed work', async () => {
  const env = environment();
  try {
    assert.equal(applicableDocuments(env.conversation).length, 3);
    const shown = await reviewDocumentProposals(BASE, env.conversation);
    assert.equal(shown.documents.length, 3);
    assert.equal(env.posts().length, 0);
    for (const change of [{ created: true }, { kind: 'phase_planning' }, { turns: [{ status: 'QUEUED' }] }])
      assert.deepEqual(applicableDocuments({ ...env.conversation, ...change }), []);
  } finally { env.close(); }
});

test('one selected review applies exact hashes in order and leaves excluded documents alone', async () => {
  const env = environment();
  try {
    const shown = await reviewDocumentProposals(BASE, env.conversation);
    shown.documents = shown.documents.filter(d => d.proposal.id !== 'p2');
    const result = await applyReviewedDocuments(BASE, shown);
    assert.deepEqual(result, { applied: ['docs/flow-1.md', 'docs/flow-3.md'], remaining: [] });
    assert.deepEqual(env.posts().map(r => r.body), [
      { expected_version: 7, proposal_sha256: hash(4), confirmed: true },
      { expected_version: 8, proposal_sha256: hash(6), confirmed: true },
    ]);
    assert.equal(env.files.has('docs/flow-2.md'), false);
  } finally { env.close(); }
});

for (const drift of ['version', 'draft', 'proposal']) test(`${drift} drift after review refuses every write`, async () => {
  const env = environment();
  try {
    const shown = await reviewDocumentProposals(BASE, env.conversation);
    if (drift === 'version') env.conversation.version++;
    if (drift === 'draft') env.files.set('docs/flow-3.md', { content: 'User edit', sha256: hash(9) });
    if (drift === 'proposal') env.conversation.proposals[2].proposal_sha256 = hash(9);
    const result = await applyReviewedDocuments(BASE, shown);
    assert.ok(result.error); assert.deepEqual(result.applied, []); assert.equal(env.posts().length, 0);
  } finally { env.close(); }
});

test('an already conflicting document is shown and cannot pass the batch preflight', async () => {
  const env = environment();
  try {
    env.files.set('docs/flow-2.md', { content: '# Existing user content\n', sha256: hash(9) });
    const shown = await reviewDocumentProposals(BASE, env.conversation);
    assert.equal(shown.documents[1].conflict, true);
    const result = await applyReviewedDocuments(BASE, shown);
    assert.ok(result.error); assert.equal(env.posts().length, 0);
    shown.documents = shown.documents.filter(d => !d.conflict);
    assert.deepEqual((await applyReviewedDocuments(BASE, shown)).applied, ['docs/flow-1.md', 'docs/flow-3.md']);
    assert.equal(env.files.get('docs/flow-2.md').sha256, hash(9));
  } finally { env.close(); }
});

for (const mode of ['conflict', 'lost', 'concurrent']) test(`${mode} during application stops without rollback, rebase or retry`, async () => {
  const env = environment();
  try {
    const shown = await reviewDocumentProposals(BASE, env.conversation);
    if (mode === 'conflict') env.fail = 'p2';
    if (mode === 'lost') env.lose = 'p2';
    if (mode === 'concurrent') env.concurrent = 'p1';
    const result = await applyReviewedDocuments(BASE, shown);
    assert.ok(result.error); assert.deepEqual(result.applied, ['docs/flow-1.md']);
    assert.equal(env.files.has('docs/flow-1.md'), true);
    assert.equal(env.files.has('docs/flow-3.md'), false);
    assert.equal(env.posts().length, mode === 'concurrent' ? 1 : 2);
    if (mode !== 'concurrent') assert.equal(result.unconfirmed, 'docs/flow-2.md');
    if (mode === 'lost') {
      assert.equal(env.files.has('docs/flow-2.md'), true, 'an unacknowledged write is not reported as confirmed');
      const next = await reviewDocumentProposals(BASE, env.conversation);
      assert.deepEqual(next.documents.map(d => d.proposal.id), ['p3'], 'reload reads the authoritative states');
    }
  } finally { env.close(); }
});

for (const language of ['en', 'es']) test(`one UI confirmation applies only the selected reviewed documents (${language})`, async () => {
  const env = environment(), driver = hookHost(), storage = new Map(); env.language = language;
  const originals = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = () => 1; globalThis.clearTimeout = () => {};
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) };
  globalThis.document = { documentElement: {} };
  const t = (key, params) => translate({ en, es }, language, key, params);
  const tree = el(I18nProvider, null, el(ProjectWorkspace, { project: 'own' }, el(ProposalBatch, { conversation: env.conversation, base: BASE })));
  const button = text => driver.host.elements.find(e => e.type === 'button' && e.props.children === text)?.props;
  try {
    await driver.render(tree);
    button(t('planning.batch.review', { count: 3 })).onClick(); let html = await driver.render(tree);
    assert.ok(html.includes('Synthetic document 1') && html.includes('Synthetic document 3'));
    assert.equal(env.posts().length, 0);
    assert.equal(button(t('planning.batch.apply', { count: 3 })).disabled, true);
    const checks = () => driver.host.elements.filter(e => e.type === 'input' && e.props.type === 'checkbox');
    checks().at(-1).props.onChange({ target: { checked: true } }); await driver.render(tree);
    checks()[1].props.onChange({ target: { checked: false } }); await driver.render(tree);
    assert.equal(button(t('planning.batch.apply', { count: 2 })).disabled, true, 'selection changes reset consent');
    checks().at(-1).props.onChange({ target: { checked: true } }); await driver.render(tree);
    const action = button(t('planning.batch.apply', { count: 2 }));
    action.onClick(); action.onClick(); html = await driver.render(tree);
    assert.equal(env.posts().length, 2, 'double click does not replay the sequence');
    assert.ok(html.includes(t('planning.batch.done', { count: 2 })));
    assert.equal(env.files.has('docs/flow-2.md'), false);
    assert.ok(env.posts().every(r => r.url.endsWith('/apply')));
  } finally {
    driver.close(); env.close(); Object.assign(globalThis, originals);
    for (const key of ['localStorage', 'sessionStorage', 'document']) delete globalThis[key];
  }
});
