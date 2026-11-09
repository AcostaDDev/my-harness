import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ReviewerTalk } = await import('../src/ReviewerTalk.tsx');
const { ChatElement, useChatElement } = await import('../src/ChatElement.tsx');
const { Chat } = await import('../src/Chat.tsx');
const { ProjectWorkspace } = await import('../src/workspace.tsx');
const { RouteBase } = await import('../src/navigation.tsx');
const { WorkMap, reviewerTarget } = await import('../src/map/WorkMap.tsx');
const { ProductFixture } = await import('../src/map/fixture/ProductFixture.tsx');
const { MapLevelSwitch } = await import('../src/map/LevelSwitch.tsx');
const { InvocationPage } = await import('../src/map/InvocationPage.tsx');
const { saveElement, loadElement } = await import('../src/chat-element.ts');
delete globalThis.__tsxHookHarness;
const { syntheticMap, respond, DEEP } = await import('../src/map/fixture/projections.ts');
const { chatFixture } = await import('../src/map/fixture/chat.ts');

const target = { kind: 'task', target: 'P002-T001' };
const value = (revision = 'accepted-1') => ({ label: 'P002-T001 — Synthetic task', reason: null,
  reference: { kind: 'task', project: 'knowledge-synthetic', stable_id: 'stable-task', revision_id: revision } });
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function setup(respond) {
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const storage = new Map(), requests = [], pushes = [];
  globalThis.sessionStorage = { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) };
  globalThis.localStorage = { getItem: () => 'en', setItem() {} };
  globalThis.document = { documentElement: { lang: '' } };
  globalThis.window = { location: { pathname: '/__fixture/projects/synthetic/phases/P002' },
    history: { pushState(_s, _t, path) { pushes.push(path); window.location.pathname = path; }, replaceState() {} },
    addEventListener() {}, removeEventListener() {} };
  globalThis.setTimeout = () => 1; globalThis.clearTimeout = () => {};
  globalThis.fetch = async (path, init) => {
    const request = { path, method: init?.method ?? 'GET', body: init?.body && JSON.parse(init.body), headers: init?.headers };
    requests.push(request);
    return await respond(request) ?? Response.json([]);
  };
  const env = hookHost();
  const tree = (child, language = 'en') => el(I18nProvider, { fixed: language }, el(RouteBase.Provider, { value: '/__fixture' }, child));
  return { ...env, tree, requests, pushes, storage,
    button: label => env.host.elements.find(e => e.type === 'button' && e.props.children === label),
    close() { env.close(); Object.assign(globalThis, original); } };
}

function setupMap({ legacy = false, archive = false, projectionArchive = archive, registered = DEEP.registered,
  project = DEEP.key, task = 'P002-T004' } = {}) {
  const map = syntheticMap('review', { legacy, archive }), chat = chatFixture(map), timers = new Map();
  const env = setup(({ path, method, body }) => {
    if (!path.startsWith('/api/managed/map/')) {
      const reply = chat(path, method, body);
      return reply && Response.json(reply.body, { status: reply.status });
    }
    const reply = respond(map, path);
    // Keep a registered identity even under archive flags to test each availability guard independently.
    if (reply.body.project) reply.body = { ...reply.body,
      read_only_archive: projectionArchive === true || projectionArchive === reply.body.level,
      project: { ...reply.body.project, registered_project_id: registered } };
    return Response.json(reply.body, { status: reply.status });
  });
  const route = { name: 'task', project, phase: 'P002', task };
  const pollerDeps = () => ({ fetchActivity: async scopes => map.activity(scopes), hidden: () => false,
    onVisibility: () => () => {}, setTimeout(callback) { timers.set(callback, callback); return callback; },
    clearTimeout: handle => timers.delete(handle) });
  const tree = env.tree(el(WorkMap, { route, archive, canRespond: !archive, pollerDeps }));
  return { ...env, map, chat, mapTree: tree, async poll() {
    const due = [...timers.values()]; timers.clear(); due.forEach(callback => callback()); await tick(); await tick();
  } };
}

test('real WorkMap opens a canonical task without runs with its removable task tag and no implicit bindings', async () => {
  const env = setupMap();
  let selection;
  try {
    const html = await env.render(env.mapTree);
    assert.match(html, /This task has no runs yet/);
    assert.ok(env.button('Talk to the reviewer'));
    env.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
    selection = loadElement('atlas', 'synthetic-chat-1');
    assert.deepEqual(selection.target, { kind: 'task', target: 'P002-T004' });
    assert.deepEqual(selection.value.reference, { kind: 'task', project: DEEP.key,
      stable_id: 'synthetic-P002-T004', revision_id: 'synthetic-accepted-1' });
    assert.equal(env.requests.find(r => r.path.includes('chat-context')).path,
      '/api/managed/projects/atlas/chat-context?kind=task&target=P002-T004');
    assert.deepEqual(env.requests.filter(r => r.method !== 'GET').map(r => [r.path, r.body]), [
      ['/api/managed/projects/atlas/conversations', { title: 'Reviewer conversation', phase_id: null, task_run_id: null }],
    ]);
    assert.equal(env.requests.some(r => r.path.includes('/steps')), false);
    assert.equal(env.map.runs('atlas', 'P002', 'P002-T004').latest_run_id, null);
    assert.equal(env.pushes.at(-1), '/__fixture/projects/atlas/chat/synthetic-chat-1');
  } finally { env.close(); }
  // Navigation mounts the real destination on a fresh hook host, retaining the selected context.
  const destination = setup(({ path, method, body }) => {
    const reply = env.chat(path, method, body);
    return reply && Response.json(reply.body, { status: reply.status });
  });
  try {
    saveElement('atlas', 'synthetic-chat-1', selection);
    const tree = destination.tree(el(ProjectWorkspace, { project: 'atlas' }, el(Chat, { conversation: 'synthetic-chat-1' })));
    assert.match(await destination.render(tree), /P002-T004/);
    assert.ok(destination.button('Remove context'));
    destination.button('Remove context').props.onClick();
    assert.doesNotMatch(await destination.render(tree), /P002-T004/);
    assert.equal(loadElement('atlas', 'synthetic-chat-1'), undefined);
  } finally { destination.close(); }
});

test('real WorkMap opens legacy tasks without runs as untagged, unbound conversations', async () => {
  const env = setupMap({ legacy: true });
  try {
    assert.match(await env.render(env.mapTree), /This task has no runs yet/);
    assert.ok(env.button('Talk to the reviewer'));
    env.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
    assert.equal(env.requests.some(r => r.path.includes('chat-context')), false);
    assert.deepEqual(loadElement('atlas', 'synthetic-chat-1').value, { reference: null, label: null, reason: 'legacy' });
    assert.deepEqual(env.requests.filter(r => r.method !== 'GET').map(r => r.body), [
      { title: 'Reviewer conversation', phase_id: null, task_run_id: null },
    ]);
    assert.equal(env.pushes.at(-1), '/__fixture/projects/atlas/chat/synthetic-chat-1');
  } finally { env.close(); }
});

test('real WorkMap requires a server-verified registered project and respects archive guards with and without runs', async () => {
  for (const options of [{ archive: true, projectionArchive: false }, { projectionArchive: true }, { registered: null },
    { task: 'P002-T005', projectionArchive: 'runs' }, { task: 'P002-T005', projectionArchive: 'steps' }]) {
    const env = setupMap(options);
    try {
      const html = await env.render(env.mapTree);
      if (!options.task) assert.match(html, /This task has no runs yet/);
      assert.equal(env.button('Talk to the reviewer'), undefined, JSON.stringify(options));
      assert.equal(env.requests.some(r => r.path.includes('chat-context') || r.method !== 'GET'), false);
      assert.deepEqual(env.pushes, []);
    } finally { env.close(); }
  }
});

test('real WorkMap refreshes the talk target when the first run appears and when a step is selected', async () => {
  const env = setupMap();
  try {
    await env.render(env.mapTree);
    assert.ok(env.button('Talk to the reviewer'));
    env.map.startRun('P002-T004');
    await env.poll();
    assert.doesNotMatch(await env.render(env.mapTree), /This task has no runs yet/);
    env.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
    assert.deepEqual(loadElement('atlas', 'synthetic-chat-1').target, { kind: 'run', target: 'run-P002-T004' });
    env.host.elements.find(e => e.props['data-node']).props.onFocus();
    await env.render(env.mapTree);
    env.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
    assert.deepEqual(loadElement('atlas', 'synthetic-chat-2').target, {
      kind: 'step', target: 'run-P002-T004', step_key: env.map.steps('atlas', 'run-P002-T004').items[0].key,
    });
    assert.ok(env.requests.filter(r => r.method !== 'GET').every(r => r.path.endsWith('/conversations')));
  } finally { env.close(); }
});

test('separate reviewer button creates an unbound conversation, carries only a verified reference and stays under its base', async () => {
  const env = setup(({ path, body }) => path.includes('chat-context') ? Response.json(value())
    : body?.title ? Response.json({ id: 'c1' }) : undefined);
  try {
    const tree = env.tree(el(ReviewerTalk, { project: 'synthetic', target }));
    await env.render(tree);
    env.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
    assert.equal(env.pushes.at(-1), '/__fixture/projects/synthetic/chat/c1');
    assert.deepEqual(env.requests[1].body, { title: 'Reviewer conversation', phase_id: null, task_run_id: null });
    assert.deepEqual(loadElement('synthetic', 'c1'), { target, value: value() });
    assert.equal(env.requests[1].headers['X-My-Harness'], '1');
    assert.ok(env.requests[1].headers['Idempotency-Key']);
  } finally { env.close(); }
});

test('a late selection response after changing the selected element never creates or navigates a conversation', async () => {
  const held = deferred();
  const env = setup(({ path }) => path.includes('chat-context') ? held.promise : undefined);
  try {
    await env.render(env.tree(el(ReviewerTalk, { project: 'synthetic', target })));
    env.button('Talk to the reviewer').props.onClick();
    await env.render(env.tree(el(ReviewerTalk, { project: 'synthetic', target: { kind: 'phase', target: 'P002' } })));
    held.resolve(Response.json(value())); await tick(); await tick();
    assert.equal(env.requests.length, 1); assert.deepEqual(env.pushes, []);
  } finally { env.close(); }
});

test('removing the tag clears its reference and refresh locator, restores composer focus and ignores late refresh', async () => {
  const held = deferred(); let state, focus = 0;
  const env = setup(() => held.promise);
  saveElement('synthetic', 'c1', { target, value: value() });
  function Probe() { state = useChatElement('synthetic', 'c1'); return el(ChatElement, { state, onRemove: () => focus++ }); }
  try {
    const tree = env.tree(el(Probe));
    let html = await env.render(tree); assert.match(html, /Synthetic task/);
    state.markStale(); html = await env.render(tree); assert.match(html, /Refresh the tag or remove/);
    env.button('Refresh context tag').props.onClick();
    env.button('Remove context').props.onClick();
    held.resolve(Response.json(value('accepted-2'))); await tick();
    html = await env.render(tree);
    assert.equal(state.reference, undefined); assert.equal(state.selection, undefined);
    assert.equal(loadElement('synthetic', 'c1'), undefined); assert.equal(focus, 1);
    assert.doesNotMatch(html, /Synthetic task|accepted-2/);
  } finally { env.close(); }
});

test('an explicit refresh replaces the visible revision, and legacy and archive entry points attach no tag', async () => {
  let state;
  const env = setup(({ body }) => body?.title ? Response.json({ id: 'legacy-chat' }) : Response.json(value('accepted-2')));
  saveElement('synthetic', 'c1', { target, value: value() });
  function Probe() { state = useChatElement('synthetic', 'c1'); return el(ChatElement, { state }); }
  try {
    const tree = env.tree(el(Probe)); await env.render(tree);
    await state.refresh(); const html = await env.render(tree);
    assert.match(html, /accepted-2/); assert.equal(state.reference.revision_id, 'accepted-2');
  } finally { env.close(); }
  const legacy = setup(({ body }) => body?.title ? Response.json({ id: 'legacy-chat' }) : undefined);
  try {
    await legacy.render(legacy.tree(el(ReviewerTalk, { project: 'synthetic', target, legacy: true })));
    legacy.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
    assert.equal(legacy.requests.length, 1);
    assert.equal(loadElement('synthetic', 'legacy-chat').value.reason, 'legacy');
  } finally { legacy.close(); }
  const archive = setup(() => { throw new Error('Archive must make no request'); });
  try { const html = await archive.render(archive.tree(el(ReviewerTalk, { project: 'synthetic', target, archive: true })));
    assert.doesNotMatch(html, /Talk to the reviewer/); assert.equal(archive.requests.length, 0);
  } finally { archive.close(); }
});

test('real composer sends the element, blocks stale resend until refresh, and removal omits it from every request field', async () => {
  let refuse = true;
  const conversation = { id: 'c1', project_id: 'synthetic', title: 'Synthetic conversation', version: 0,
    phase: null, task_run_id: null, turns: [], proposals: [], actions: ['message'] };
  const env = setup(({ path, body }) => {
    if (path.includes('chat-context')) return Response.json(value('accepted-2'));
    if (path.endsWith('/messages')) return refuse
      ? Response.json({ detail: { code: 'element_stale', diagnostic: 'Synthetic stale selection' } }, { status: 409 })
      : Response.json({ id: 1, run_id: 'chat-run', status: 'QUEUED' });
    if (path === '/api/managed/conversations/c1') return Response.json(conversation);
    if (path.includes('/runs?')) return Response.json({ items: [], offset: 0, next_offset: null });
    if (path === '/api/managed/runs/chat-run') return Response.json({ id: 'chat-run', project_id: 'synthetic', phase_id: 'CHAT', task_id: 'CHAT' });
    return Response.json([]);
  });
  saveElement('synthetic', 'c1', { target, value: value() });
  const tree = env.tree(el(ProjectWorkspace, { project: 'synthetic' }, el(Chat, { conversation: 'c1' })));
  const enter = async text => { env.host.elements.find(e => e.type === 'textarea' && e.props.maxLength === 20000).props.onChange({ target: { value: text } }); await env.render(tree); };
  const submit = () => env.host.elements.filter(e => e.type === 'form').at(-1).props.onSubmit({ preventDefault() {} });
  try {
    await env.render(tree); await enter('Explain this task'); submit(); await tick(); await tick();
    let html = await env.render(tree); assert.match(html, /This context changed/);
    const sent = env.requests.find(r => r.path.endsWith('/messages'));
    assert.deepEqual(sent.body.element, value().reference);
    assert.equal(env.host.elements.filter(e => e.type === 'form').at(-1).props.children.at(-1)?.props.disabled, true);
    env.button('Refresh context tag').props.onClick(); await tick(); await env.render(tree);
    assert.equal(env.host.elements.filter(e => e.type === 'form').at(-1).props.children.at(-1)?.props.disabled, false);
    env.button('Remove context').props.onClick(); await env.render(tree);
    refuse = false; submit(); await tick(); await tick(); await env.render(tree);
    const last = env.requests.filter(r => r.path.endsWith('/messages')).at(-1).body;
    assert.deepEqual(last, { expected_version: 0, text: 'Explain this task', documents: null, run_ids: [] });
    assert.equal(JSON.stringify(last).includes('stable-task'), false);
  } finally { env.close(); }
});

test('phase, task, run and deterministic step selections address their own element', () => {
  assert.deepEqual(reviewerTarget({ level: 1, item: { code: 'P002' } }, { name: 'phases', project: 'p' }), { kind: 'phase', target: 'P002' });
  assert.deepEqual(reviewerTarget(undefined, { name: 'task', project: 'p', phase: 'P002', task: 'P002-T001' }), target);
  assert.deepEqual(reviewerTarget(undefined, { name: 'run' }, 'r1'), { kind: 'run', target: 'r1' });
  assert.deepEqual(reviewerTarget({ level: 3, item: { kind: 'harness', key: '999999.0000' } }, { name: 'run' }, 'r1'),
    { kind: 'step', target: 'r1', step_key: '999999.0000' });
});

test('English and Spanish tags expose ordinary keyboard buttons and explain legacy without a selection', async () => {
  for (const [language, include, remove, legacy] of [
    ['en', 'will be included', 'Remove context', 'no accepted canonical knowledge'],
    ['es', 'Se incluirá', 'Quitar contexto', 'no tiene conocimiento canónico aceptado'],
  ]) {
    const env = setup(() => { throw new Error('Rendering a tag makes no read'); });
    try {
      const state = { selection: { value: value() }, reference: value().reference, remove() {}, refresh() {}, stale: false, loading: false, error: '' };
      let html = await env.render(env.tree(el(ChatElement, { state }), language));
      assert.ok(html.includes(include));
      assert.ok(env.button(remove)); assert.equal(env.button(remove).props.type, 'button');
      assert.match(html, /role="status" aria-live="polite"/);
      html = await env.render(env.tree(el(ChatElement, { state: { ...state, reference: undefined, selection: { value: { reference: null, label: null, reason: 'legacy' } } } }), language));
      assert.ok(html.includes(legacy)); assert.doesNotMatch(html, /<button/);
    } finally { env.close(); }
  }
});

test('the prepared visual fixture simulates context refresh and turn removal entirely in memory', () => {
  const map = syntheticMap(), respond = chatFixture(map);
  const selection = respond('/api/managed/projects/atlas/chat-context?kind=task&target=P002-T005').body;
  const conversation = respond('/api/managed/projects/atlas/conversations', 'POST', { title: 'Synthetic' }).body;
  const path = `/api/managed/conversations/${conversation.id}/messages`;
  map.bump();
  assert.equal(respond(path, 'POST', { element: selection.reference, text: 'Old' }).status, 409);
  const fresh = respond('/api/managed/projects/atlas/chat-context?kind=task&target=P002-T005').body;
  assert.equal(respond(path, 'POST', { element: fresh.reference, text: 'Fresh' }).status, 202);
  assert.equal(respond(path, 'POST', { text: 'No tag' }).status, 202);
  const read = respond(`/api/managed/conversations/${conversation.id}`).body;
  assert.equal(read.turns[0].element.reference.revision_id, fresh.reference.revision_id);
  assert.equal(read.turns[1].element, null);
});

test('ProductFixture replaces loaded canonical map and invocation reads when legacy is enabled', async t => {
  const env = setup(({ path }) => { throw new Error(`Unexpected real fetch: ${path}`); });
  window.fetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = (path, init) => { requests.push(path); return window.fetch(path, init); };
  globalThis.setTimeout = (callback, delay) => { if (delay === 60) queueMicrotask(callback); return 1; };
  env.host.lifecycle = true;
  env.host.keyed = new Set([MapLevelSwitch, InvocationPage]);
  let settings = { source: 'product', product: 'review', archive: false, language: 'en', theme: 'light' };
  const change = patch => { settings = { ...settings, ...patch }; };
  const tree = () => env.tree(el(ProductFixture, { settings, change }), settings.language);
  const toggle = checked => env.host.elements.find(e => e.type === 'input' && e.props.type === 'checkbox')
    .props.onChange({ target: { checked } });
  try {
    for (const [entry, path] of [
      ['L3 task', '/phases/P002/tasks/P002-T004'],
      ['L4 invocation', '/invocations/inv-atlas-executor-2'],
    ]) {
      await t.test(entry, async () => {
        change({ language: 'en', theme: 'light' });
        if (entry === 'L4 invocation') toggle(false);
        window.location.pathname = '/__map-fixture/projects/atlas' + path;
        await env.render(tree());
        assert.ok(env.button('Talk to the reviewer'), 'canonical entry loaded before toggling');
        requests.length = 0;
        toggle(true);
        await env.render(tree());
        env.button('Talk to the reviewer').props.onClick(); await tick(); await tick();
        assert.equal(requests.some(path => path.includes('/chat-context?')), false);
        const html = await env.render(tree());
        assert.match(html, /This legacy project has no accepted canonical knowledge/);
        assert.doesNotMatch(html, /Remove context/);

        change({ theme: 'dark' });
        assert.match(await env.render(tree()), /0 turns/);
        change({ language: 'es' });
        assert.match(await env.render(tree()), /0 turnos/);
        const detail = await (await fetch('/api/managed/conversations/synthetic-chat-1')).json();
        assert.equal(detail.id, 'synthetic-chat-1');
        assert.deepEqual(detail.turns, []);
      });
    }
  } finally { env.close(); }
});

test('synthetic conversation lists expose numeric turn counts that the real Chat renders', async () => {
  const reply = chatFixture(syntheticMap());
  const list = '/api/managed/projects/atlas/conversations';
  const summaries = [];
  for (const count of [0, 1, 3]) {
    const title = `Conversation with ${count}`;
    const { body: { id } } = reply(list, 'POST', { title });
    const detail = `/api/managed/conversations/${id}`;
    const messages = Array.from({ length: count }, (_, i) => `Message ${i + 1}`);
    for (const text of messages) assert.equal(reply(`${detail}/messages`, 'POST', { text }).status, 202);
    const { body } = reply(detail);
    assert.deepEqual(body.turns.map(turn => turn.message), messages);
    summaries.push({ id, title, phase_id: null, phase_code: null, task_run_id: null, turns: count,
      version: count, created_at: body.created_at, updated_at: body.updated_at });
  }
  assert.deepEqual(reply(list).body, summaries);

  const env = setup(({ path, method, body }) => {
    const result = reply(path, method, body);
    return result && Response.json(result.body, { status: result.status });
  });
  try {
    const html = await env.render(env.tree(el(ProjectWorkspace, { project: 'atlas' }, el(Chat))));
    assert.deepEqual([...html.matchAll(/class="link-meta">([^<]+)</g)].map(match => match[1]), ['0 turns', '1 turn', '3 turns']);
  } finally { env.close(); }
});

test('an uncertain submitted envelope locks tag edits until its exact request has an outcome', async () => {
  const held = deferred();
  const conversation = { id: 'c1', project_id: 'synthetic', title: 'Synthetic conversation', version: 0,
    phase: null, task_run_id: null, turns: [], proposals: [], actions: ['message'] };
  const env = setup(({ path }) => path.endsWith('/messages') ? held.promise
    : path === '/api/managed/conversations/c1' ? Response.json(conversation)
    : path.includes('/runs?') ? Response.json({ items: [], offset: 0, next_offset: null }) : Response.json([]));
  saveElement('synthetic', 'c1', { target, value: value() });
  const tree = env.tree(el(ProjectWorkspace, { project: 'synthetic' }, el(Chat, { conversation: 'c1' })));
  try {
    await env.render(tree);
    env.host.elements.find(e => e.type === 'textarea' && e.props.maxLength === 20000).props.onChange({ target: { value: 'Synthetic request' } });
    await env.render(tree);
    env.host.elements.filter(e => e.type === 'form').at(-1).props.onSubmit({ preventDefault() {} });
    await env.render(tree);
    assert.equal(env.button('Remove context').props.disabled, true);
    assert.equal(env.button('Refresh context tag').props.disabled, true);
    held.resolve(Response.json({ detail: { code: 'element_stale' } }, { status: 409 })); await tick(); await tick();
    await env.render(tree);
    assert.equal(env.button('Remove context').props.disabled, false);
  } finally { env.close(); }
});
