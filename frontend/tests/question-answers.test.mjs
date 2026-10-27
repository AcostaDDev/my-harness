import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import { translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

// OT002: question-first answers driven through real server renders and recorded requests. Synthetic
// conversation only; no browser, service or model is involved.
globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ProjectWorkspace } = await import('../src/workspace.tsx');
const { QuestionAnswers } = await import('../src/pages/Answers.tsx');
const { ImportPage } = await import('../src/pages/Planning.tsx');
delete globalThis.__tsxHookHarness;

const id = n => String(n).repeat(12).slice(0, 12) + 'e'.repeat(52);
const short = n => id(n).slice(0, 12);
const question = (n, text, blocking = true) => ({ id: id(n), text, blocking, deferred: null });
const BASE = '/projects/own/planning/c1';
const answeredTurn = (number, questions, message = 'Start') => ({ id: `t${number}`, number, status: 'ANSWERED', run_id: `run-${number}`, run_status: 'COMPLETED',
  message, context_sha256: 'a'.repeat(64), request_sha256: 'b'.repeat(64), drafts: [], user_edits: [], documents: [], actor: {},
  result: { status: 'ANSWERED', result: { answer: 'Synthetic answer', questions, drafts: [], pending: [] } }, created_at: '2026-10-27T10:00:00Z', finished_at: null });
const queuedTurn = (number, message) => ({ ...answeredTurn(number, []), status: 'QUEUED', run_status: 'QUEUED', result: null, message });

function conversation(overrides = {}) {
  const questions = [question(1, 'Which database will it use?'), question(2, 'Which deploy target?', false), question(3, 'Which license?')];
  return { id: 'c1', project_id: 'own', root: '/synthetic/own', kind: 'onboarding', title: 'Synthetic intake', phase: null, brief: null,
    source: {}, known: {}, log: [], questions, pending: ['Confirm the CI provider'], actor: {}, version: 4, created_at: '', updated_at: '',
    created: false, turns: [answeredTurn(1, questions)], proposals: [], actions: ['message', 'edit_draft', 'defer_question'], operation: null, ...overrides };
}

function environment(language = 'en') {
  const driver = hookHost(), session = new Map(), local = new Map([['harness-ui-language', language]]), requests = [];
  const originals = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const catalog = language === 'en' ? en : es;
  const env = { ...driver, requests, local, catalog, fail: null, conversation: conversation() };
  env.t = (key, params) => translate({ en, es }, language, key, params);
  globalThis.setTimeout = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.document = { documentElement: {}, getElementById: () => null };
  const store = map => ({ getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, String(value)), removeItem: key => map.delete(key) });
  globalThis.localStorage = store(local);
  globalThis.sessionStorage = store(session);
  globalThis.window = { location: { pathname: '/projects/own/onboarding/c1', search: '' }, dispatchEvent() {}, history: { pushState() {}, replaceState() {} }, scrollTo() {} };
  globalThis.fetch = async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : undefined;
    requests.push({ path, body, key: options?.headers?.['Idempotency-Key'] });
    if (path === '/api/managed/preferences') return Response.json({ version: 1, ui_language: language, default_work_language: 'en' });
    if (body !== undefined && env.fail) { const status = env.fail; env.fail = null;
      return Response.json({ detail: { code: status === 409 ? 'version_conflict' : 'boom', diagnostic: `Synthetic ${status}.` } }, { status }); }
    if (path === `/api/managed${BASE}/messages`) return Response.json({ id: 9, run_id: 'run-new', status: 'QUEUED' });
    if (path === `/api/managed${BASE}/questions/defer`) return Response.json({ ok: true });
    if (path === `/api/managed${BASE}`) return Response.json(env.conversation);
    if (path === `/api/managed${BASE}/drafts`) return Response.json({ drafts: [], allowed: { fixed: [], required: [], patterns: [] }, invalid: [], foreign: [], foreign_truncated: false });
    if (path === '/api/managed/projects/own/onboarding') return Response.json({ refusal: null, operation: null });
    if (path === '/api/managed/projects/own/planning') return Response.json([{ id: 'c1', kind: 'onboarding', title: 'Synthetic intake', turns: 1, version: 4 }]);
    if (path.startsWith('/api/managed/runs/') && path.includes('/events')) return Response.json({ items: [], cursor: 0, has_more: false });
    if (path.startsWith('/api/managed/runs/')) return Response.json({ detail: { code: 'not_found' } }, { status: 404 });
    assert.fail('Unexpected request: ' + path);
  };
  env.tree = () => el(I18nProvider, null, el(ProjectWorkspace, { project: 'own' }, el(QuestionAnswers, { conversation: env.conversation, base: BASE })));
  env.show = () => driver.render(env.tree());
  env.type = async (n, value) => {
    const field = env.host.elements.find(e => e.type === 'textarea' && e.props.id === `answer-${short(n)}`);
    assert.ok(field, `field ${n}`);
    assert.ok(!field.props.readOnly, `field ${n} is editable`);
    field.props.onChange({ target: { value } });
    return env.show();
  };
  env.field = n => env.host.elements.find(e => e.type === 'textarea' && e.props.id === `answer-${short(n)}`);
  env.select = async n => { env.host.elements.find(e => e.type === 'input' && e.props.id === `answer-${short(n)}-select`).props.onChange({ target: { checked: true } }); return env.show(); };
  env.buttons = text => env.host.elements.filter(e => e.type === 'button' && e.props.children === text);
  env.click = async (text, index = 0) => {
    const button = env.buttons(text)[index];
    assert.ok(button, text);
    assert.ok(!button.props.disabled, `${text} is enabled`);
    button.props.onClick();
    await new Promise(resolve => setImmediate(resolve));
    return env.show();
  };
  env.preview = () => env.host.elements.find(e => e.type === 'pre' && e.props.className === 'answers-preview')?.props.children;
  env.posts = () => requests.filter(r => r.body !== undefined);
  env.close = () => { driver.close(); Object.assign(globalThis, originals); for (const key of ['document', 'window', 'sessionStorage', 'localStorage']) delete globalThis[key]; };
  return env;
}

for (const language of ['en', 'es']) test(`one answer is sent alone, as one turn, with its question and marker (${language})`, async () => {
  const env = environment(language);
  try {
    let html = await env.show();
    assert.ok(html.includes(env.t('answers.title')));
    assert.ok(html.indexOf(env.t('answers.kind.blocking')) < html.indexOf(env.t('answers.kind.informative')), 'blocking questions come first');
    assert.ok(html.includes('Confirm the CI provider') && html.includes(env.t('planning.pending')), 'declared pending items are listed apart');
    await env.type(1, 'PostgreSQL 16');
    await env.type(2, 'Fly.io');
    assert.deepEqual(env.posts(), [], 'typing never calls the service');
    await env.click(env.t('answers.review_one'), 0);
    const text = env.preview();
    assert.match(text, new RegExp(`\\[q:${short(1)}\\] ${env.t('answers.message.blocking')}: Which database will it use\\?\\n${env.t('answers.message.answer')}:\\nPostgreSQL 16`));
    assert.ok(!text.includes('Fly.io'));
    await env.click(env.t('answers.review.send'));
    const posts = env.posts();
    assert.equal(posts.length, 1);
    assert.equal(posts[0].path, `/api/managed${BASE}/messages`);
    assert.deepEqual(posts[0].body, { expected_version: 4, text });
    assert.ok(posts[0].key, 'sent with an idempotency key');
    html = await env.show();
    assert.ok(html.includes(env.t('answers.sent')));
    assert.equal(env.field(2).props.value, 'Fly.io', 'the other draft stays');
  } finally { env.close(); }
});

test('a selected set and all prepared answers each go in exactly one request', async () => {
  const env = environment();
  try {
    await env.show();
    await env.type(1, 'A1'); await env.type(2, 'A2'); await env.type(3, 'A3');
    await env.select(1); await env.select(3);
    await env.click(env.t('answers.review_selected', { count: 2 }));
    assert.deepEqual([...env.preview().matchAll(/\[q:([0-9a-f]{12})\]/g)].map(m => m[1]), [short(1), short(3)]);
    await env.click(env.t('answers.review.back'));
    await env.click(env.t('answers.review_all', { count: 3 }));
    const text = env.preview();
    assert.deepEqual([...text.matchAll(/\[q:([0-9a-f]{12})\]/g)].map(m => m[1]), [short(1), short(3), short(2)], 'blocking first, as shown');
    // Optional context goes after the answers, in the same message.
    env.host.elements.find(e => e.type === 'textarea' && !e.props.id && !e.props.readOnly).props.onChange({ target: { value: 'Small team.' } });
    await env.show();
    assert.match(env.preview(), new RegExp(`${env.t('answers.message.context')}:\\nSmall team\\.$`));
    await env.click(env.t('answers.review.send'));
    assert.equal(env.posts().length, 1, 'one turn, never one hidden call per question');
    assert.equal(env.posts()[0].body.text.match(/\[q:/g).length, 3);
  } finally { env.close(); }
});

test('after a partial submission the sent answer waits, the rest stays editable and nothing resends while queued', async () => {
  const env = environment();
  try {
    await env.show();
    await env.type(1, 'PostgreSQL'); await env.type(3, 'MIT');
    await env.click(env.t('answers.review_one'), 0);
    const text = env.preview();
    await env.click(env.t('answers.review.send'));
    // The next poll shows the queued turn that carries the first answer.
    env.conversation = conversation({ version: 5, actions: ['edit_draft', 'defer_question'], turns: [...env.conversation.turns, queuedTurn(2, text)] });
    const html = await env.show();
    assert.ok(env.field(1).props.readOnly, 'a sent answer is not edited while it waits');
    assert.ok(html.includes(env.t('answers.state.awaiting', { turn: 2 })));
    assert.ok(html.includes(env.t('answers.running')));
    assert.equal(env.field(3).props.value, 'MIT');
    assert.ok(!env.field(3).props.readOnly, 'drafts can still be prepared during a turn');
    await env.type(3, 'MIT, with notice');
    await env.click(env.t('answers.review_all', { count: 1 }));
    assert.equal(env.buttons(env.t('answers.review.send'))[0].props.disabled, true, 'no submission while a turn is queued');
    assert.equal(env.posts().length, 1);
    // The turn fails: the answer is not reviewed; it is shown as such and can be sent again explicitly.
    env.conversation = conversation({ version: 6, turns: [...env.conversation.turns.slice(0, 1), { ...queuedTurn(2, text), status: 'FAILED', run_status: 'FAILED' }] });
    const failed = await env.show();
    assert.ok(failed.includes(env.t('answers.state.unreviewed', { turn: 2 })));
    assert.ok(!env.field(1).props.readOnly);
  } finally { env.close(); }
});

test('the aggregate limit refuses an oversized batch without cutting or splitting it', async () => {
  const env = environment();
  try {
    await env.show();
    await env.type(1, 'x'.repeat(12000)); await env.type(3, 'y'.repeat(9000));
    const html = await env.click(env.t('answers.review_all', { count: 2 }));
    assert.ok(html.includes(env.t('answers.review.over', { size: [...env.preview()].length, limit: 20000 })));
    assert.equal(env.buttons(env.t('answers.review.send'))[0].props.disabled, true);
    await env.click(env.t('answers.review.back'));
    await env.click(env.t('answers.review_one'), 0);
    assert.equal(env.buttons(env.t('answers.review.send'))[0].props.disabled, false, 'a smaller batch fits');
    assert.deepEqual(env.posts(), []);
  } finally { env.close(); }
});

test('drafts survive a reload and request errors; a conflict keeps them and says so', async () => {
  let env = environment();
  try {
    await env.show();
    await env.type(1, 'Kept across reloads');
    const saved = env.local.get('harness-planning-answers-v1:own:c1');
    env.close();
    env = environment();
    env.local.set('harness-planning-answers-v1:own:c1', saved);
    await env.show();
    assert.equal(env.field(1).props.value, 'Kept across reloads');
    await env.click(env.t('answers.review_one'), 0);
    env.fail = 409;
    let html = await env.click(env.t('answers.review.send'));
    assert.ok(html.includes(env.t('answers.review.conflict', { error: 'Synthetic 409.' })));
    assert.equal(env.field(1).props.value, 'Kept across reloads');
    env.fail = 500;
    html = await env.click(env.t('answers.review.send'));
    assert.ok(html.includes('Synthetic 500.'), 'other failures surface in the workspace');
    assert.equal(env.field(1).props.value, 'Kept across reloads');
    assert.equal(env.posts().length, 2);
  } finally { env.close(); }
});

test('a new question set never attaches a draft to a different question; a version change asks for a new review', async () => {
  const env = environment();
  try {
    await env.show();
    await env.type(1, 'Draft for the old question');
    await env.click(env.t('answers.review_one'), 0);
    env.conversation = conversation({ version: 5 });
    let html = await env.show();
    assert.ok(html.includes(env.t('answers.review.stale')));
    assert.equal(env.buttons(env.t('answers.review.send'))[0].props.disabled, true);
    await env.click(env.t('answers.review.again'));
    assert.equal(env.buttons(env.t('answers.review.send'))[0].props.disabled, false);
    await env.click(env.t('answers.review.back'));
    // The reviewer answers a turn sent elsewhere: question 1 is gone and question 4 appears.
    const next = [question(4, 'Which region?'), question(3, 'Which license?')];
    env.conversation = conversation({ version: 7, questions: next, turns: [...env.conversation.turns, answeredTurn(2, next, 'other message')] });
    html = await env.show();
    assert.equal(env.field(4).props.value, '', 'the new question starts empty');
    assert.ok(html.includes(env.t('answers.earlier.title')) && html.includes('Draft for the old question'));
    assert.ok(html.includes(env.t('answers.earlier.turn', { turn: 1 })));
    // Including it is explicit and labels it as an earlier question.
    env.host.elements.find(e => e.type === 'input' && e.props.type === 'checkbox' && !e.props.id).props.onChange({ target: { checked: true } });
    await env.show();
    await env.click(env.t('answers.review_selected', { count: 1 }));
    assert.match(env.preview(), new RegExp(`\\[q:${short(1)}\\] ${env.t('answers.message.earlier')}: Which database will it use\\?`));
    assert.deepEqual(env.posts(), []);
  } finally { env.close(); }
});

test('a double click sends one request and deferral stays a separate action with its reason', async () => {
  const env = environment();
  try {
    await env.show();
    await env.type(1, 'Once');
    await env.click(env.t('answers.review_one'), 0);
    const send = env.buttons(env.t('answers.review.send'))[0];
    send.props.onClick(); send.props.onClick();
    await new Promise(resolve => setImmediate(resolve));
    await env.show();
    assert.equal(env.posts().length, 1);
    const defer = env.buttons(env.t('planning.question.defer'));
    assert.equal(defer.length, 2, 'only open blocking questions offer deferral');
    assert.equal(defer[0].props.disabled, true, 'a deferral needs a reason');
    const reason = env.host.elements.filter(e => e.type === 'input' && e.props.maxLength === 2000)[0];
    reason.props.onChange({ target: { value: 'Decide after the pilot' } });
    await env.show();
    await env.click(env.t('planning.question.defer'), 0);
    const deferral = env.posts().at(-1);
    assert.equal(deferral.path, `/api/managed${BASE}/questions/defer`);
    assert.deepEqual(deferral.body, { expected_version: 4, question_id: id(1), reason: 'Decide after the pilot' });
  } finally { env.close(); }
});

test('a confirmed conversation shows its questions without any mutation control', async () => {
  const env = environment();
  try {
    env.conversation = conversation({ created: true, actions: [] });
    const html = await env.show();
    assert.ok(html.includes('Which database will it use?') && html.includes(env.t('answers.closed')));
    assert.equal(env.host.elements.filter(e => e.type === 'textarea' || e.type === 'button' || e.type === 'input').length, 0);
  } finally { env.close(); }
});

for (const language of ['en', 'es']) test(`onboarding puts the questions before the free composer, in reading order (${language})`, async () => {
  const env = environment(language);
  try {
    env.tree = () => el(I18nProvider, null, el(ProjectWorkspace, { project: 'own' }, el(ImportPage, { conversation: 'c1' })));
    const html = await env.show();
    const answers = html.indexOf('id="answers-title"');
    const composer = html.indexOf(env.t('planning.message.other'));
    const rail = html.indexOf('class="workbench-aside"');
    assert.ok(answers > 0 && composer > answers, 'questions first, then the conversation and its composer');
    assert.ok(rail > composer, 'the rail follows the main column in the document');
    assert.ok(html.includes(env.t('planning.message.other_hint')));
    assert.ok(html.includes(env.t('activity.title.turn', { number: 1 })));
    assert.deepEqual(env.posts(), []);
  } finally { env.close(); }
});

for (const language of ['en', 'es']) test(`failed-turn documents are labelled as rejected rather than applicable drafts (${language})`, async () => {
  const env = environment(language);
  try {
    const answered = answeredTurn(1, []);
    answered.result.result.drafts = [{ path: 'AGENTS.md', reason: 'Synthetic valid draft' }];
    const failed = { ...answeredTurn(2, []), status: 'FAILED', run_status: 'STOPPED' };
    failed.result = { status: 'FAILED', reasons: ['Synthetic invalid profile'], result: {
      answer: 'Rejected synthetic output', drafts: [{ path: 'docs/ARCHITECTURE.md', reason: 'Rejected draft' }] } };
    env.conversation = conversation({ turns: [answered, failed], questions: [] });
    env.tree = () => el(I18nProvider, null, el(ProjectWorkspace, { project: 'own' }, el(ImportPage, { conversation: 'c1' })));
    const html = await env.show();
    assert.ok(html.includes(env.t('planning.turn.drafts')));
    assert.ok(html.includes(env.t('planning.turn.rejected_drafts')));
    assert.ok(html.includes('Synthetic invalid profile') && html.includes('docs/ARCHITECTURE.md'));
    assert.deepEqual(env.posts(), []);
  } finally { env.close(); }
});
