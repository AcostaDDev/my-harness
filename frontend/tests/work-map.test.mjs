// P002-T022: the product work map L0–L3 over T020's projections. Pure modules (view toggle, status classes,
// adapters, loader, activity poll, announcements) and the real `WorkMap`/`Page` rendered on the server with a
// synthetic T020 projection (`map/fixture/projections.ts`) behind a fake fetch. No browser, service or network.
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { hookHost } from './helpers/render-hooks.mjs';
import { translate, plural } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };
import table from '../src/status-classes.json' with { type: 'json' };

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ServiceModeContext } = await import('../src/ServiceMode.tsx');
const { Page } = await import('../src/Page.tsx');
const { Status, MapStatusBadge } = await import('../src/ui.tsx');
const { WorkMap } = await import('../src/map/WorkMap.tsx');
const { archiveTrail } = await import('../src/Shell.tsx');
delete globalThis.__tsxHookHarness;
const { syntheticMap, respond, DEEP, PROJECTION_SIZES } = await import('../src/map/fixture/projections.ts');
const { projectsView, phasesView, tasksView, stepsView, chatsOf, routeProject, duration } = await import('../src/map/projection.ts');
const { LevelLoader, MAX_PAGES } = await import('../src/map/loader.ts');
const { ActivityPoller, changedScopes, ACTIVE_MS, IDLE_MS } = await import('../src/map/refresh.ts');
const { Announcer, statusChanges, ANNOUNCE_GAP_MS } = await import('../src/map/announce.ts');
const { viewParam, viewOf, withView, chooseView, rememberedView, rememberView, forgetViewMemory, VIEW_STORAGE } = await import('../src/map/view-mode.ts');
const { listStatusClass, statusClass } = await import('../src/status-class.ts');
const { navigate } = await import('../src/navigation.tsx');
const { parse, href, trail } = await import('../src/router.ts');
const { mapLevel } = await import('../src/map/routes.ts');
const { MapView } = await import('../src/map/MapView.tsx');
const { clearShapes } = await import('../src/map/shapes.ts');
const { pageGestures } = await import('../src/map/controller.ts');
const { ManagedError } = await import('../src/managed-api.ts');

const texts = language => ({ t: (key, params) => translate({ en, es }, language, key, params), n: (key, count, params) => plural({ en, es }, language, key, count, params), language });
const T = texts('en');
const decode = text => text.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const nodeIds = html => [...html.matchAll(/data-node="([^"]+)"/g)].map(match => match[1]);
const flatten = classes => Object.fromEntries(Object.entries(classes).flatMap(([cls, codes]) => codes.map(code => [code, cls])));
const tick = () => new Promise(resolve => setImmediate(resolve));

function fakeTimers() {
  const timers = new Map();
  let id = 0;
  return {
    timers,
    setTimeout(callback, ms) { timers.set(++id, { callback, ms }); return id; },
    clearTimeout(handle) { timers.delete(handle); },
    /** Runs every pending timer once (in creation order). */
    async fire() { const due = [...timers.entries()]; timers.clear(); for (const [, { callback }] of due) callback(); await tick(); await tick(); },
  };
}

/** Browser-like globals: location/history with listeners, storage, document visibility and a fetch over `map`. */
function browser(map, { path = '/', search = '', storage = new Map(), throwStorage = false, archive = false, failing = () => false, answer } = {}) {
  const requests = [], pushes = [], listeners = new Set();
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const timers = fakeTimers();
  globalThis.setTimeout = timers.setTimeout; globalThis.clearTimeout = timers.clearTimeout;
  globalThis.window = {
    location: { pathname: path, search },
    history: {
      pushState(_s, _t, next) { pushes.push(next); const url = new URL(next, 'http://x'); window.location.pathname = url.pathname; window.location.search = url.search; },
      replaceState(_s, _t, next) { const url = new URL(next, 'http://x'); window.location.pathname = url.pathname; window.location.search = url.search; },
    },
    addEventListener(type, listener) { if (type === 'popstate') listeners.add(listener); },
    removeEventListener(type, listener) { listeners.delete(listener); },
    confirm: () => true, dispatchEvent() {},
  };
  globalThis.document = { documentElement: {}, activeElement: null, visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
  const store = {
    getItem: key => { if (throwStorage) throw new Error('blocked'); return key === 'harness-language' ? 'en' : storage.get(key) ?? null; },
    setItem: (key, value) => { if (throwStorage) throw new Error('blocked'); storage.set(key, value); },
    removeItem: key => storage.delete(key),
  };
  globalThis.localStorage = store; globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, method: options?.method ?? 'GET' });
    if (url === '/api/managed/preferences') return Response.json({ status: 'missing' });
    if (options?.method && options.method !== 'GET') return Response.json({ detail: { code: 'refused' } }, { status: 409 });
    if (failing(url)) return Response.json({ detail: { code: 'unavailable', message: 'Synthetic outage' } }, { status: 503 });
    const custom = answer?.(url);
    if (custom) return Response.json(custom.body, { status: custom.status });
    const reply = respond(map, url);
    return Response.json(reply.body, { status: reply.status });
  };
  return {
    requests, pushes, timers, storage,
    reads: prefix => requests.filter(item => item.url.startsWith(prefix)).length,
    back(next) { const url = new URL(next, 'http://x'); window.location.pathname = url.pathname; window.location.search = url.search; listeners.forEach(listener => listener()); },
    close() {
      Object.assign(globalThis, original);
      for (const key of ['window', 'document', 'localStorage', 'sessionStorage']) delete globalThis[key];
    },
  };
}

function pollDeps() {
  const timers = fakeTimers();
  const visibility = new Set();
  const state = { hidden: false, reads: [] };
  return {
    timers, state,
    deps: () => ({
      fetchActivity: async scopes => { state.reads.push(scopes); return state.activity ? state.activity(scopes) : state.map.activity(scopes); },
      setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, hidden: () => state.hidden,
      onVisibility: listener => { visibility.add(listener); return () => visibility.delete(listener); },
    }),
    visibility,
    setHidden(value) { state.hidden = value; visibility.forEach(listener => listener()); },
  };
}

// --- view toggle and navigation --------------------------------------------------------------------------------

test('?view selects map or list on the same path; the choice is remembered, and storage failures fall back to memory', () => {
  const env = browser(syntheticMap(), { path: '/projects/atlas/phases' });
  try {
    forgetViewMemory();
    assert.equal(viewParam('?view=list'), 'list');
    assert.equal(viewParam('?view=LIST'), undefined, 'only the exact values');
    assert.equal(viewParam('?view=graph'), undefined);
    assert.equal(viewOf(''), 'map', 'map is the default');
    assert.equal(withView('/projects/atlas/phases', '?a=1', 'list'), '/projects/atlas/phases?a=1&view=list');
    chooseView('/projects/atlas/phases', '', 'list');
    assert.deepEqual(env.pushes, ['/projects/atlas/phases?view=list'], 'a history entry: Back/Forward replay it');
    assert.equal(env.storage.get(VIEW_STORAGE), 'list');
    assert.equal(viewOf(''), 'list', 'a direct link without the parameter uses the remembered choice');
    assert.equal(viewOf('?view=map'), 'map', 'the parameter wins');
    // Same path and query: no duplicate entry; a different query is a navigation.
    navigate('/projects/atlas/phases?view=list');
    assert.equal(env.pushes.length, 1);
    navigate('/projects/atlas/phases?view=map');
    assert.equal(env.pushes.length, 2);
  } finally { env.close(); }
  const blocked = browser(syntheticMap(), { throwStorage: true });
  try {
    forgetViewMemory();
    assert.equal(rememberedView(), undefined);
    assert.equal(viewOf(''), 'map');
    chooseView('/', '', 'list');
    assert.equal(viewOf(''), 'list', 'kept in page memory when storage throws');
  } finally { blocked.close(); forgetViewMemory(); }
});

test('the invocation route round-trips and is not a map level; the check route stays an operational page', () => {
  const route = { name: 'invocation', project: 'atlas', invocation: 'inv #1' };
  assert.equal(href(route), '/projects/atlas/invocations/inv%20%231');
  assert.deepEqual(parse(href(route)), route);
  assert.equal(mapLevel(route), undefined);
  assert.equal(mapLevel(parse('/projects/atlas/phases/P002/check')), undefined);
  for (const [path, level] of [['/', 0], ['/projects/atlas/phases', 1], ['/projects/atlas/phases/P002', 2], ['/projects/atlas/phases/P002/tasks/T', 3], ['/projects/atlas/phases/P002/tasks/T/runs/r', 3]])
    assert.equal(mapLevel(parse(path)), level, path);
  assert.deepEqual(trail(route, T.t).map(item => item.label), ['Projects', 'atlas', 'Invocation inv #1']);
  // Archives keep the map trail from the archive home, the project leading to its phases.
  const crumbs = archiveTrail(parse('/projects/kp-atlas/phases/P002'), T.t);
  assert.deepEqual(crumbs.map(item => item.label), [en['archive.title'], 'kp-atlas', 'Phases', 'P002']);
  assert.deepEqual(crumbs[1].to, { name: 'phases', project: 'kp-atlas' });
  assert.deepEqual(archiveTrail(parse('/projects/p/settings'), T.t).map(item => item.label), [en['archive.title']]);
});

// --- shared Status ----------------------------------------------------------------------------------------------

test('shared Status shows the six classes and unknown with icon, translated text and the raw code', () => {
  const driver = hookHost();
  try { statusCases(); } finally { driver.close(); }
});

function statusCases() {
  for (const language of ['en', 'es']) {
    const html = value => renderToStaticMarkup(el(I18nProvider, { fixed: language }, el(Status, value)));
    const cases = [['COMMITTED', 'done'], ['EXECUTING', 'progress'], ['ACCEPTANCE_READY', 'waiting'], ['REVISION_LIMIT', 'failed'],
      ['STOPPED', 'inactive'], ['CANCELLED', 'inactive'], ['REPETITIVE', 'failed'], ['MYSTERY', 'unknown']];
    for (const [code, cls] of cases) {
      const markup = html({ value: code });
      assert.match(markup, new RegExp(`class="status status-${cls}"`), code);
      assert.match(markup, /<svg class="status-icon"/, 'an icon, never colour alone');
      assert.match(markup, new RegExp(`title="${code}"`));
      if (cls === 'unknown') assert.match(markup, new RegExp(language === 'en' ? `Unknown: ${code}` : `Desconocido: ${code}`));
      else assert.match(markup, new RegExp(`class="visually-hidden"> \\(${code}\\)`), 'raw code for assistive technology');
    }
    assert.match(html({ value: 'READY_TO_CLOSE', kind: 'phase' }), /status-waiting/);
    assert.match(html({ value: 'BLOCKED', kind: 'phase' }), /status-failed/);
    // The map badge shows T020's class as projected, never recomputed from the code.
    const badge = renderToStaticMarkup(el(I18nProvider, { fixed: language }, el(MapStatusBadge, { status: { code: 'COMMITTED', class: 'failed' } })));
    assert.match(badge, /status-failed/);
  }
  // Pending (no run) is a projected class; the lists never meet it as a code.
  assert.equal(statusClass('run', null), 'unknown');
}

test('the list status table equals T020 mapping per entity and the list merges run and attempt without conflict', () => {
  const run = flatten(table.run), attempt = flatten(table.attempt), phase = flatten(table.phase);
  for (const [code, cls] of Object.entries(run)) assert.equal(listStatusClass('run', code), cls, code);
  for (const [code, cls] of Object.entries(attempt)) assert.equal(listStatusClass('run', code), run[code] ?? cls, code);
  for (const [code, cls] of Object.entries(phase)) assert.equal(listStatusClass('phase', code), cls, code);
  assert.equal(listStatusClass('run', 'ABANDONED'), 'unknown', 'a phase code is not a run code');
  for (const code of Object.keys(run).filter(code => code in attempt)) assert.equal(run[code], attempt[code], code);
  // Every class but `unknown` is reachable from the persisted list vocabularies (pending comes from projections).
  const classes = new Set([...Object.values(run), ...Object.values(attempt), ...Object.values(phase)]);
  assert.deepEqual([...classes].sort(), ['done', 'failed', 'inactive', 'progress', 'waiting']);
});

// --- adapters ---------------------------------------------------------------------------------------------------

test('L0–L3 adapters keep T020 classes, counters, circles, chat lane and bubbles; absence is "not observed"', () => {
  const map = syntheticMap('review');
  const projects = projectsView([map.projects()], false, T);
  assert.equal(projects.nodes.length, PROJECTION_SIZES.review.projects);
  const deep = projects.nodes[0];
  assert.equal(deep.statusClass, 'progress');
  assert.equal(deep.badge, 'Autonomous');
  assert.equal(deep.counter, `Phases 1/${PROJECTION_SIZES.review.phases}`);
  assert.deepEqual(deep.to, { name: 'phases', project: 'atlas' }, 'ordinary mode enters the configured project');
  assert.deepEqual(projects.nodes[4].counter, 'Phases: not observed', 'no zero for an absent counter');
  // Two active invocations stay two actors: E on the task lane and R on the chat lane.
  const active = deep.actors.filter(actor => actor.active).map(actor => [actor.role, !!actor.chat]);
  assert.deepEqual(active, [['R', true], ['E', false], ['H', false]].filter(([role]) => role !== 'H').concat(deep.actors.find(a => a.role === 'H').active ? [['H', false]] : []));
  assert.deepEqual(deep.actors.map(actor => actor.role), ['R', 'E', 'J', 'H'], 'J only where T020 shows it (judge profile)');
  assert.ok(!projects.nodes[1].actors.some(actor => actor.role === 'J'), 'no judge profile, no judge history: no J');
  assert.equal(deep.requests, PROJECTION_SIZES.review.inbox);
  assert.deepEqual(deep.actors.find(actor => actor.role === 'E').target, { name: 'invocation', project: 'atlas', invocation: 'inv-atlas-executor-2' });
  // Archives use the map key; nothing is configured there.
  const archived = syntheticMap('review', { archive: true });
  assert.equal(routeProject(archived.projects().items[0], true), DEEP.key);

  const phases = phasesView([map.phases('atlas')], 'atlas', T);
  const open = phases.nodes.find(node => node.id === DEEP.phase);
  assert.ok(open.actors?.length, 'circles on the active phase');
  assert.ok(phases.nodes.filter(node => node.id !== DEEP.phase && node.statusClass === 'done').every(node => !node.actors), 'idle phases carry no circles');
  assert.deepEqual(open.slots.map(slot => slot.key), ['plan', 'check', 'close']);
  assert.equal(phases.edges.every(edge => edge.kind === 'sequence'), true);
  assert.ok(phases.nodes.some(node => node.statusClass === 'unknown' && node.counter === 'Tasks: not observed'));

  const tasks = tasksView([map.tasks('atlas', DEEP.phase)], 'atlas', DEEP.phase, T);
  const task = tasks.nodes.find(node => node.id === DEEP.task);
  assert.equal(task.counter, 'Attempt 2/3');
  assert.ok(tasks.nodes.some(node => node.counter === 'No runs'));
  assert.ok(tasks.nodes.some(node => node.counter === 'Attempts: not observed'));
  // T020 `source` depends on `target`: the engine draws prerequisite → dependent.
  const dependency = map.tasks('atlas', DEEP.phase).edges.find(edge => edge.kind === 'depends_on');
  assert.ok(tasks.edges.some(edge => edge.kind === 'depends_on' && edge.from === dependency.target && edge.to === dependency.source));
  assert.ok(tasks.edges.some(edge => edge.kind === 'replaces'));
  for (const cls of ['done', 'progress', 'waiting', 'failed', 'pending', 'inactive', 'unknown'])
    assert.ok(tasks.nodes.some(node => node.statusClass === cls), `L2 covers ${cls}`);

  const steps = stepsView([map.steps('atlas', map.deepRun)], 'atlas', T);
  assert.deepEqual(steps.nodes.slice(0, 4).map(node => node.code), ['Executor #1', 'Format', 'Validate', 'Reviewer #1']);
  assert.equal(steps.nodes.at(-1).code, 'Commit');
  const running = steps.nodes.find(node => node.actors?.[0].active && node.actors[0].role === 'E');
  assert.equal(running.counter, 'Duration: not observed');
  assert.equal(running.requests, 1, 'the permission raised by the running executor sits on it');
  assert.ok(steps.nodes.some(node => node.actors?.[0].role === 'J'), 'a judge invocation is a J step');
  assert.ok(steps.nodes.every(node => !node.to), 'steps are the deepest map level here; circles open the invocation');
  assert.equal(duration(41234, 'es'), '41,2 s');
  assert.equal(duration(61234, 'en'), '1 min 1 s');
  assert.equal(duration(850, 'en'), '850 ms');
});

// --- loader -----------------------------------------------------------------------------------------------------

test('a level loader keeps one read in flight, pages on demand, recovers from cursor_stale and ignores late answers', async () => {
  const map = syntheticMap('budget');
  const calls = [];
  const gates = [];
  const fetcher = path => new Promise((resolve, reject) => {
    calls.push(path);
    gates.push(() => { const answer = respond(map, path); answer.status === 200 ? resolve(answer.body)
      : reject(new ManagedError(answer.status, 'x', answer.body.detail.code)); });
  });
  const release = async () => { gates.shift()(); await tick(); };
  const states = [];
  const path = '/map/projects/atlas/phases/P002/tasks?limit=30';
  const loader = new LevelLoader(path, fetcher, state => states.push(state));
  loader.reload();
  loader.reload();
  assert.equal(calls.length, 1, 'no overlapping read: the second reload is queued');
  await release();
  assert.equal(calls.length, 2, 'the queued reload runs once');
  await release();
  assert.equal(loader.state.pages.length, 1);
  assert.equal(loader.state.pages[0].items.length, 30);
  assert.ok(loader.canLoadMore);
  loader.loadMore();
  await release();
  assert.equal(loader.state.pages.length, 2);
  assert.match(calls[2], /cursor=c1\.1\.30/);
  // A writer advances the version: the next page's cursor is stale; old pages are discarded and the first page reread.
  map.bump();
  loader.loadMore();
  await release();
  assert.equal(loader.state.recovered, true);
  assert.equal(loader.state.pages.length, 1, 'later pages discarded at once');
  assert.equal(calls.length, 5, 'the first page is reread right after the stale cursor');
  assert.doesNotMatch(calls[4], /cursor=/);
  await release();
  assert.equal(loader.state.pages.length, 1);
  assert.equal(loader.state.pages[0].version.endsWith('.2'), true);
  assert.equal(loader.state.recovered, false);
  // Memory is bounded by a window, never by cutting the history: past it the oldest page is dropped and counted.
  const capped = new LevelLoader('/map/projects/atlas/phases/P002/tasks?limit=1', fetcher, () => {}, 2);
  capped.reload(); await release(); capped.loadMore(); await release(); capped.loadMore(); await release();
  assert.equal(capped.state.pages.length, 2, `at most ${2} pages held here (default ${MAX_PAGES})`);
  assert.equal(capped.state.skipped, 1);
  assert.equal(capped.canLoadMore, true, 'the next page stays reachable');
  // A disposed loader (the level changed) applies nothing that arrives later.
  let disposed = false;
  const late = new LevelLoader('/map/projects', fetcher, () => { if (disposed) assert.fail('late answer applied'); });
  late.reload();
  const before = late.state;
  late.dispose();
  disposed = true;
  await release();
  assert.equal(late.state, before);
  // 404 is a missing element, not an empty level.
  const missing = new LevelLoader('/map/projects/nobody/phases', fetcher, () => {});
  missing.reload(); await release();
  assert.equal(missing.state.missing, true);
});

// --- activity poll ----------------------------------------------------------------------------------------------

test('activity polling: 2 s active, 10 s idle, paused while hidden, no overlap, scope changes, and a clean stop', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  const results = [];
  const poller = new ActivityPoller(poll.deps(), result => results.push(result));
  poller.setScopes(['s1.fixture.projects']);
  poller.start();
  assert.equal(poll.timers.timers.size, 1);
  assert.equal([...poll.timers.timers.values()][0].ms, ACTIVE_MS, 'first read after the active interval');
  await poll.timers.fire();
  assert.equal(poll.state.reads.length, 1);
  assert.deepEqual(poll.state.reads[0], ['s1.fixture.projects'], 'one aggregated read');
  assert.equal([...poll.timers.timers.values()][0].ms, 2000, 'active work: 2 s');
  map.bump({ finish: true });
  await poll.timers.fire();
  assert.equal([...poll.timers.timers.values()][0].ms, 10000, 'idle: 10 s');
  assert.equal(results.length, 2);
  // Hidden: no read and no timer; visible again: one read at once.
  poll.setHidden(true);
  assert.equal(poll.timers.timers.size, 0);
  assert.equal(poller.isPaused, true);
  poll.setHidden(false);
  await tick(); await tick();
  assert.equal(poll.state.reads.length, 3);
  // A slow read never overlaps the next one, and a result for superseded scopes is dropped.
  let resolve;
  poll.state.activity = scopes => new Promise(done => { resolve = () => done(map.activity(scopes)); });
  await poll.timers.fire();
  assert.equal(poll.state.reads.length, 4);
  assert.equal(poll.timers.timers.size, 0, 'nothing scheduled while a read is in flight');
  poller.setScopes(['s1.fixture.phases.kp-atlas']);
  resolve(); await tick(); await tick();
  assert.equal(results.length, 3, 'the read for the old scopes is not reported');
  assert.equal(poll.timers.timers.size, 1);
  delete poll.state.activity;
  poller.stop();
  assert.equal(poll.timers.timers.size, 0, 'stop clears the timer');
  assert.equal(poll.visibility.size, 0, 'and the visibility listener');
  // A response that disables polling (archives) stops it.
  const archived = pollDeps();
  archived.state.map = syntheticMap('review', { archive: true });
  const off = new ActivityPoller(archived.deps(), () => assert.fail('archive results are not used'));
  off.setScopes(['s1.fixture.projects']); off.start();
  await archived.timers.fire();
  assert.equal(off.running, false);
  assert.equal(archived.timers.timers.size, 0);
  // Changed and vanished scopes.
  const activity = map.activity(['s1.fixture.projects', 's1.other']);
  assert.deepEqual(changedScopes(activity, { 's1.fixture.projects': 'v1.old', 's1.other': 'v1.x', 's1.unrequested': 'v' }), ['s1.fixture.projects', 's1.other']);
  assert.deepEqual(changedScopes(activity, { 's1.fixture.projects': activity.scopes[0].version }), []);
});

// --- announcements ----------------------------------------------------------------------------------------------

test('status changes are announced politely at most once every 10 s, summarised, and never for a first snapshot', () => {
  let now = 0;
  const timers = fakeTimers();
  const said = [];
  const announcer = new Announcer({ now: () => now, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout }, changes => said.push(changes));
  const snap = entries => new Map(entries.map(([id, status]) => [id, { code: id, status, label: status }]));
  assert.deepEqual(statusChanges(undefined, snap([['A', 'progress|EXECUTING']])), [], 'first snapshot');
  assert.deepEqual(statusChanges(snap([['A', 'progress|X']]), snap([['A', 'progress|X'], ['B', 'done|Y']])), [], 'new elements are not changes');
  announcer.push(statusChanges(snap([['A', 'progress|EXECUTING']]), snap([['A', 'failed|BLOCKED']])));
  assert.equal(said.length, 1);
  now = 3000;
  announcer.push([{ id: 'B', code: 'B', status: 'done|C', label: 'Done' }]);
  announcer.push([{ id: 'B', code: 'B', status: 'failed|F', label: 'Failed' }, { id: 'C', code: 'C', status: 'done|C', label: 'Done' }]);
  assert.equal(said.length, 1, 'throttled');
  assert.equal(timers.timers.size, 1);
  assert.equal([...timers.timers.values()][0].ms, ANNOUNCE_GAP_MS - 3000);
  now = 10000;
  const [[due, { callback }]] = timers.timers.entries();
  timers.timers.delete(due);
  callback();
  assert.deepEqual(said[1].map(change => [change.id, change.label]), [['B', 'Failed'], ['C', 'Done']], 'accumulated; latest status wins');
  announcer.push([{ id: 'D', code: 'D', status: 'x', label: 'x' }]);
  announcer.dispose();
  assert.equal(timers.timers.size, 0, 'dispose clears the pending timer');
});

// --- rendered map -----------------------------------------------------------------------------------------------

async function renderMap(route, { map = syntheticMap('review'), archive = false, canRespond = !archive, language = 'en', poll, display, failing, answer } = {}) {
  const env = browser(map, { path: href(route), archive, failing, answer });
  const driver = hookHost();
  const tree = () => el(I18nProvider, { fixed: language }, el(ServiceModeContext.Provider, { value: { read_only_archive: archive } },
    el(WorkMap, { route: parse(window.location.pathname), archive, canRespond, pollerDeps: poll?.deps, display })));
  const html = await driver.render(tree());
  return { env, driver, map, html, rerender: () => driver.render(tree()), close() { driver.close(); env.close(); pageGestures.end(); } };
}

test('every level renders from its T020 read with labelled nodes, one tab stop, and overlays kept out of the tab order', async () => {
  for (const [route, count] of [[{ name: 'home' }, 6], [{ name: 'phases', project: 'atlas' }, 8], [{ name: 'phase', project: 'atlas', phase: 'P002' }, 12],
    [{ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' }, undefined]]) {
    const view = await renderMap(route);
    try {
      const ids = nodeIds(view.html);
      if (count) assert.equal(ids.length, count, route.name);
      else assert.ok(ids.length > 4);
      assert.equal((view.html.match(/class="map-node[^"]*"[^>]*tabindex="0"|tabindex="0"[^>]*class="map-node/g) ?? []).length, 1, 'roving tabindex');
      for (const overlay of view.html.matchAll(/<(?:a|g) [^>]*class="(?:map-actor[^"]*|map-bubble|map-actor-requests|map-details)"[^>]*>/g))
        assert.match(overlay[0], /tabindex="-1"|role="img"/, overlay[0]);
      assert.match(view.html, /aria-live="polite"/);
      assert.match(view.html, /class="map-inspector"/);
      const reads = view.env.requests.map(request => request.url);
      assert.ok(reads.every(url => url.startsWith('/api/managed/map/')), reads.join(' '));
    } finally { view.close(); }
  }
});

test('the bottom-sheet toggle controls the inspector body it shows or hides, on the map and in the table', async () => {
  for (const display of [undefined, 'table']) {
    const view = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' }, { display });
    try {
      const toggle = view.html.match(/<button type="button" class="button-quiet map-sheet-toggle" aria-expanded="(true|false)" aria-controls="([^"]+)">([^<]*)<\/button>/);
      assert.ok(toggle, 'the toggle names what it controls');
      assert.equal(toggle[1], 'false', 'closed until something is selected');
      assert.equal(toggle[3], en['map.inspector.expand']);
      const body = view.html.match(/<div class="map-inspector-body" id="([^"]+)">/);
      assert.equal(body?.[1], toggle[2], 'aria-controls is the body that a closed sheet hides on narrow screens');
      assert.ok(view.html.indexOf(toggle[0]) < view.html.indexOf(body[0]), 'the toggle precedes the body in the Tab order');
    } finally { view.close(); }
  }
});

test('L3 shows the latest run by default and a paged selector; choosing a run is its own navigation', async () => {
  const view = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' }, { map: syntheticMap('budget') });
  try {
    const reads = view.env.requests.map(request => request.url);
    assert.ok(reads.includes('/api/managed/map/projects/atlas/phases/P002/tasks/P002-T005/runs'));
    assert.ok(reads.includes(`/api/managed/map/projects/atlas/runs/${view.map.deepRun}/steps`), 'steps of latest_run_id');
    assert.equal(nodeIds(view.html).filter(id => !id.startsWith('chat:')).length, PROJECTION_SIZES.budget.steps);
    assert.deepEqual(nodeIds(view.html).filter(id => id.startsWith('chat:')), ['chat:inv-atlas-chat-1'], 'the run’s chat lane, from the same read');
    const select = view.driver.host.elements.find(element => element.type === 'select');
    assert.equal(select.props.value, view.map.deepRun);
    const options = view.driver.host.elements.filter(element => element.type === 'option');
    assert.equal(options.length, PROJECTION_SIZES.budget.runs);
    select.props.onChange({ target: { value: 'run-atlas-010' } });
    assert.deepEqual(view.env.pushes, ['/projects/atlas/phases/P002/tasks/P002-T005/runs/run-atlas-010']);
    assert.match(view.html, /Harness attempt|This level/);
  } finally { view.close(); }
});

test('selecting a step fills the inspector with separate attempts, rounds, turns, requested and reported models', async () => {
  const view = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' });
  try {
    const node = view.driver.host.elements.find(element => element.props['data-node'] === '000001.0000');
    node.props.onFocus();
    const html = decode(await view.rerender());
    for (const label of ['Harness attempt', 'Revision round', 'Native turns', 'Requested model', 'Reported model', 'Tool calls', 'Knowledge deliveries', 'Observed steps'])
      assert.match(html, new RegExp(label), label);
    assert.match(html, /claude-synthetic-reported/);
    assert.match(html, /Steps not projected \(earlier run\)/);
    // A Codex reviewer step reports no model or denials: shown as not observed with the client's reason.
    view.driver.host.elements.find(element => element.props['data-node'] === '000002.0000').props.onFocus();
    const reviewer = decode(await view.rerender());
    assert.match(reviewer, /not observed \(<code>not_reported_by_client<\/code>\)/);
    assert.doesNotMatch(reviewer, /Reported model<\/dt><dd>0/);
  } finally { view.close(); }
});

test('a circle opens its invocation and a bubble opens T017 requests over the map; neither navigates the card', async () => {
  const view = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' });
  try {
    const elements = () => view.driver.host.elements;
    const click = { detail: 1, button: 0, preventDefault() {}, stopPropagation() {} };
    // Circle: a separate SVG link to the latest invocation in the element.
    const circle = elements().find(element => element.props['data-actor'] === 'E' && element.props.href?.endsWith('inv-atlas-executor-2'));
    assert.equal(circle.props.href, '/projects/atlas/invocations/inv-atlas-executor-2');
    circle.props.onClick(click);
    // Only the invocation: the card link (which would push the task route) never ran.
    assert.deepEqual(view.env.pushes, ['/projects/atlas/invocations/inv-atlas-executor-2']);
    // Browser Back returns to the level, which is read again from its projection.
    view.env.back('/projects/atlas/phases/P002');
    await view.rerender();
    // Bubble: opens the panel without any navigation; the item is read by identity from T017.
    view.env.pushes.length = 0;
    const bubble = elements().find(element => element.props.className === 'map-bubble' && element.props.transform?.includes?.('translate'));
    assert.ok(bubble, 'node bubble');
    bubble.props.onClick(click);
    const html = decode(await view.rerender());
    assert.deepEqual(view.env.pushes, [], 'no navigation, neither the card nor the panel');
    assert.match(html, /Requests of P002-T005/);
    // Two requests listed: the owner picks one; it is re-read from the inbox by its identity only.
    const open = elements().filter(element => element.type === 'button' && element.props.className === 'map-request-open');
    assert.equal(open.length, 2);
    open[0].props.onClick();
    const conversation = decode(await view.rerender());
    const itemReads = view.env.requests.filter(request => request.url.startsWith('/api/managed/inbox/'));
    assert.deepEqual(itemReads.map(request => request.url), ['/api/managed/inbox/run-permission%3A000?project=kp-atlas']);
    assert.match(conversation, /Synthetic context line/);
    assert.match(conversation, /type="checkbox"/, 'T017 confirmation, not a free composer');
    assert.doesNotMatch(conversation, /<textarea/, 'a permission request has no free text composer');
  } finally { view.close(); }
});

test('a request that changed is re-read and shows its current state instead of applying the old one', async () => {
  const map = syntheticMap('review');
  const view = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' }, { map });
  try {
    const click = { detail: 1, button: 0, preventDefault() {}, stopPropagation() {} };
    // The executor circle's own bubble holds one request: the conversation opens directly.
    view.driver.host.elements.find(element => element.props.className === 'map-actor-requests' && element.props['aria-label'].includes('executor')).props.onClick(click);
    const first = decode(await view.rerender());
    assert.match(first, /type="checkbox"/, 'the current read offers the guarded T017 decision');
    // The run finished meanwhile: the permission is resolved, so no grant/deny control is offered from the old read.
    map.bump({ finish: true });
    const timer = [...view.env.timers.timers.values()].find(entry => entry.ms === 4000);
    assert.ok(timer, 'T017 conversation re-reads the item');
    view.env.timers.timers.clear();
    timer.callback();
    await tick(); await tick();
    const html = decode(await view.rerender());
    assert.match(html, /GRANTED/);
    assert.doesNotMatch(html, /type="checkbox"/);
    assert.equal(view.env.requests.filter(request => request.method !== 'GET').length, 0, 'nothing was sent');
  } finally { view.close(); }
});

test('L0 aggregates and truncated lists read the element list with its exact scope; executor and judge get no free composer', async () => {
  const map = syntheticMap('budget');
  const view = await renderMap({ name: 'home' }, { map });
  try {
    const click = { detail: 1, button: 0, preventDefault() {}, stopPropagation() {} };
    view.driver.host.elements.find(element => element.props.className === 'map-bubble').props.onClick(click);
    const html = decode(await view.rerender());
    assert.match(html, /300 requests waiting/);
    const lists = view.env.requests.filter(request => request.url.startsWith('/api/managed/map/projects/kp-atlas/bubbles'));
    assert.deepEqual(lists.map(request => request.url), ['/api/managed/map/projects/kp-atlas/bubbles'], 'the whole project, no scope');
    assert.equal(view.driver.host.elements.filter(element => element.props.className === 'map-request-open').length, 50, 'bounded pages, never the whole history');
    assert.ok(!view.env.requests.some(request => request.url.startsWith('/api/managed/inbox?')), 'no unattributed inbox page');
  } finally { view.close(); }
  const phase = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' }, { map: syntheticMap('budget') });
  try {
    const click = { detail: 1, button: 0, preventDefault() {}, stopPropagation() {} };
    phase.driver.host.elements.find(element => element.props.className === 'map-bubble').props.onClick(click);
    const html = decode(await phase.rerender());
    const buttons = phase.driver.host.elements.filter(element => element.props.className === 'map-request-open');
    assert.equal(buttons.length, 50, 'items_truncated: the element list replaces the 20 listed identities, not added to them');
    assert.deepEqual(phase.env.requests.filter(request => request.url.includes('/bubbles')).map(request => request.url),
      ['/api/managed/map/projects/kp-atlas/bubbles?phase=P002&task=P002-T005']);
    assert.doesNotMatch(html, /<textarea/);
  } finally { phase.close(); }
});

test('polling reloads a level only when its version changes, from the first page, and stops when unmounted', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  const view = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' }, { map, poll });
  try {
    const level = '/api/managed/map/projects/atlas/phases/P002/tasks';
    assert.equal(view.env.reads(level), 1);
    await poll.timers.fire();
    await view.rerender();
    assert.equal(poll.state.reads.length, 1);
    assert.deepEqual(poll.state.reads[0], ['s1.fixture.tasks.kp-atlas.P002'], 'the scope in view');
    assert.equal(view.env.reads(level), 1, 'same version: no reload');
    map.bump({ finish: true });
    await poll.timers.fire();
    await view.rerender();
    assert.equal(view.env.reads(level), 2, 'changed version: the level snapshot is reloaded');
    assert.ok(view.env.requests.filter(request => request.url.startsWith(level)).every(request => !request.url.includes('cursor=')));
  } finally {
    view.close();
    assert.equal(poll.timers.timers.size, 0, 'timers cleared on unmount');
    assert.equal(poll.visibility.size, 0);
  }
});

test('the archive map polls nothing, mounts no action and opens requests read-only', async () => {
  const map = syntheticMap('review', { archive: true });
  const poll = pollDeps();
  poll.state.map = map;
  const view = await renderMap({ name: 'phase', project: DEEP.key, phase: 'P002' }, { map, archive: true, poll });
  try {
    assert.equal(poll.timers.timers.size, 0, 'no activity timer');
    assert.equal(poll.state.reads.length, 0);
    const click = { detail: 1, button: 0, preventDefault() {}, stopPropagation() {} };
    view.driver.host.elements.find(element => element.props.className === 'map-actor-requests' && element.props['aria-label'].includes('executor')).props.onClick(click);
    const html = decode(await view.rerender());
    assert.match(html, /Read-only: answers are not possible here/);
    assert.match(html, /Synthetic context line/, 'the item is read (read-only)');
    assert.doesNotMatch(html, /type="checkbox"|<textarea|Mark as read|Grant/);
    assert.equal(view.env.timers.timers.size, 0, 'no timer at all (the T017 panel does not poll in archives)');
    assert.ok(view.env.requests.every(request => request.method === 'GET'));
    assert.ok(view.env.requests.every(request => /^\/api\/managed\/(map|inbox)\//.test(request.url)), 'no registry, checkout or configuration read');
  } finally { view.close(); }
});

test('the home page is the map by default and the existing list one toggle away; check stays operational', async () => {
  const map = syntheticMap('review');
  for (const [path, search, expect] of [['/', '', /data-node=/], ['/projects/atlas/phases/P002/check', '', /./]]) {
    const env = browser(map, { path, search });
    const driver = hookHost();
    try {
      forgetViewMemory();
      const html = await driver.render(el(I18nProvider, { fixed: 'en' }, el(ServiceModeContext.Provider, { value: { read_only_archive: false, configuration_mode: 'READY' } }, el(Page, { route: parse(path) }))));
      assert.match(html, expect);
      if (path === '/') {
        assert.match(html, /role="group" aria-label="View"/);
        assert.match(html, /aria-pressed="true"[^>]*><span aria-hidden="true" class="map-view-mark map-view-map"/);
        const list = driver.host.elements.find(element => element.type === 'button' && element.props['aria-pressed'] === false);
        list.props.onClick();
        assert.deepEqual(env.pushes, ['/?view=list']);
      } else {
        assert.doesNotMatch(html, /role="group" aria-label="View"/, 'no toggle on the check page');
        assert.ok(!env.requests.some(request => request.url.startsWith('/api/managed/map/')));
      }
    } finally { driver.close(); env.close(); forgetViewMemory(); }
  }
});

test('Spanish renders the same map and inspector texts from the catalogue', async () => {
  const view = await renderMap({ name: 'home' }, { language: 'es' });
  try {
    const html = decode(view.html);
    assert.match(html, /Autónomo/);
    assert.match(html, /Fases 1\/8/);
    assert.match(html, /Fases: no observado/);
    assert.match(html, /Proyecto atlas/);
  } finally { view.close(); }
});

test('a version change that alters a status in view is announced in the polite live region', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  const view = await renderMap({ name: 'home' }, { map, poll });
  try {
    assert.match(view.html, /aria-live="polite"><\/p>/, 'nothing announced for the first read');
    map.bump({ finish: true });
    await poll.timers.fire();
    const html = decode(await view.rerender());
    assert.match(html, /aria-live="polite">1 change in view: atlas: Waiting for you\.<\/p>/);
  } finally { view.close(); }
});

test('?view=list renders the existing page with its controls and reads no map projection', async () => {
  const map = syntheticMap('review');
  const env = browser(map, { path: '/projects/atlas/phases', search: '?view=list' });
  const driver = hookHost();
  try {
    const html = await driver.render(el(I18nProvider, { fixed: 'en' }, el(ServiceModeContext.Provider, { value: { read_only_archive: false, configuration_mode: 'READY' } },
      el(Page, { route: parse('/projects/atlas/phases') }))));
    assert.match(html, /aria-pressed="true"[^>]*><span aria-hidden="true" class="map-view-mark map-view-list"/);
    assert.ok(env.requests.some(request => request.url === '/api/managed/projects/atlas/phases'), 'the existing phases page reads its own API');
    assert.ok(!env.requests.some(request => request.url.startsWith('/api/managed/map/')));
    assert.match(html, /Phases/);
  } finally { driver.close(); env.close(); forgetViewMemory(); }
});

test('a circle target opens the existing L4 read header, not a missing page, with owner links and no trace graph', async () => {
  for (const archive of [false, true]) {
    const map = syntheticMap('review', { archive });
    const project = archive ? DEEP.key : 'atlas';
    const path = `/projects/${project}/invocations/inv-atlas-executor-2`;
    const env = browser(map, { path });
    const driver = hookHost();
    try {
      const html = decode(await driver.render(el(I18nProvider, { fixed: 'en' }, el(ServiceModeContext.Provider, { value: { read_only_archive: archive, configuration_mode: 'READY' } },
        el(Page, { route: parse(path) })))));
      assert.match(html, /Executor invocation/);
      assert.match(html, new RegExp(`href="/projects/${project}/phases/P002/tasks/P002-T005"`), 'owner breadcrumb links');
      assert.match(html, /The step-by-step trace of the invocation is not shown on this page/);
      assert.doesNotMatch(html, /data-node=/, 'no trace graph here');
      assert.deepEqual(env.requests.filter(request => request.url.startsWith('/api/managed/map/')).map(request => request.url),
        [`/api/managed/map/projects/${project}/invocations/inv-atlas-executor-2`]);
      assert.equal(/Read again/.test(html), !archive, 'archives read once, without a refresh control');
      assert.equal(env.timers.timers.size, 0);
    } finally { driver.close(); env.close(); }
  }
});

// --- review corrections (P002-T022 review, D314) --------------------------------------------------------------

const CLICK = { detail: 1, button: 0, preventDefault() {}, stopPropagation() {} };
const timersOf = poll => [...poll.timers.timers.values()];

test('a stored choice never overrides the last choice of this page when only writing it failed', () => {
  forgetViewMemory();
  const original = globalThis.localStorage;
  const writes = [];
  globalThis.localStorage = { getItem: key => key === VIEW_STORAGE ? 'map' : null, setItem: (key, value) => { writes.push([key, value]); throw new Error('quota'); }, removeItem() {} };
  try {
    assert.equal(viewOf(''), 'map', 'the stored choice applies before any choice in this page');
    rememberView('list');
    assert.deepEqual(writes, [[VIEW_STORAGE, 'list']], 'the write was attempted');
    assert.equal(viewOf(''), 'list', 'the failed write keeps the choice of this page');
    assert.equal(viewOf('?view=map'), 'map', 'the explicit parameter still wins');
  } finally { globalThis.localStorage = original; forgetViewMemory(); }
});

test('the loader window keeps memory bounded yet reaches pages after the fifth, and recovers from cursor_stale there', async () => {
  const map = syntheticMap('budget');
  const calls = [];
  const fetcher = async path => { calls.push(path); const answer = respond(map, path); if (answer.status !== 200) throw new ManagedError(answer.status, 'x', answer.body.detail.code); return answer.body; };
  const states = [];
  const loader = new LevelLoader('/map/projects/atlas/phases/P002/tasks?limit=1', fetcher, state => states.push(state));
  loader.reload(); await tick();
  const first = loader.state.pages[0];
  for (let i = 0; i < MAX_PAGES + 2; i++) { assert.ok(loader.canLoadMore, `page ${i + 2} is reachable`); loader.loadMore(); await tick(); }
  assert.equal(loader.state.pages.length, MAX_PAGES, 'at most MAX_PAGES pages held');
  assert.equal(loader.state.skipped, 3, 'the dropped pages are counted, not hidden silently');
  assert.deepEqual(loader.state.pages.map(page => page.items[0].code), ['P002-T004', 'P002-T005', 'P002-T006', 'P002-T007', 'P002-T008'],
    'the window moved on to the items after the fifth page');
  assert.equal(loader.state.head, first, 'the first page (its head fields) is kept apart');
  assert.ok(loader.canLoadMore, 'a valid cursor stays usable');
  // A writer supersedes the version past the threshold: the first page is shown again and reread.
  states.length = 0;
  map.bump();
  loader.loadMore(); await tick(); await tick();
  const shown = states.find(state => state.recovered);
  assert.ok(shown, 'the recovery is signalled');
  assert.deepEqual([shown.skipped, shown.pages.length, shown.pages[0]], [0, 1, first], 'the window falls back to the first page at once');
  const done = loader.state;
  assert.equal(done.pages.length, 1);
  assert.equal(done.recovered, false);
  assert.doesNotMatch(calls.at(-1), /cursor=/, 'recovered from the first page');
  assert.ok(done.pages[0].version.endsWith('.2'));
});

test('a task without runs keeps following its run selector: the first run appears without navigation or reload', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  const route = { name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T004' };
  const view = await renderMap(route, { map, poll });
  try {
    const runs = '/api/managed/map/projects/atlas/phases/P002/tasks/P002-T004/runs';
    assert.match(decode(view.html), /This task has no runs yet\./);
    assert.equal(view.env.reads(runs), 1);
    assert.equal(poll.timers.timers.size, 1, 'the run selector scope is followed');
    await poll.timers.fire();
    assert.deepEqual(poll.state.reads[0], ['s1.fixture.runs.kp-atlas.P002.P002-T004']);
    assert.equal(view.env.reads(runs), 1, 'same version: nothing reread');
    map.startRun('P002-T004');
    await poll.timers.fire();
    const html = decode(await view.rerender());
    assert.equal(view.env.reads(runs), 2, 'the changed selector is reread once');
    assert.equal(view.env.reads('/api/managed/map/projects/atlas/runs/run-P002-T004/steps'), 1, 'and its first run is read');
    assert.doesNotMatch(html, /This task has no runs yet/);
    assert.equal(nodeIds(html).length, 1);
    assert.deepEqual(view.env.pushes, [], 'no navigation');
    assert.equal(poll.timers.timers.size, 1, 'still one timer');
    await poll.timers.fire();
    assert.deepEqual([...poll.state.reads.at(-1)].sort(), ['s1.fixture.runs.kp-atlas.P002.P002-T004', 's1.fixture.steps.kp-atlas.run-P002-T004'], 'one aggregated read of both scopes');
  } finally {
    view.close();
    assert.equal(poll.timers.timers.size, 0);
  }
});

test('a failed first read can be retried from the view, and a failed poll says the map may be out of date until it recovers', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  let down = true;
  const level = '/api/managed/map/projects/atlas/phases/P002/tasks';
  const view = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' }, { map, poll, failing: url => down && url.startsWith(level) });
  try {
    assert.match(decode(view.html), /role="alert"[^>]*>503[^<]*Synthetic outage/);
    assert.equal(poll.timers.timers.size, 0, 'nothing known to follow yet');
    down = false;
    const retry = view.driver.host.elements.find(element => element.type === 'button' && element.props.children === 'Read again');
    assert.ok(retry, 'a retry control');
    retry.props.onClick();
    let html = decode(await view.rerender());
    assert.equal(view.env.reads(level), 2, 'one more read');
    assert.equal(nodeIds(html).length, 12);
    assert.equal(poll.timers.timers.size, 1, 'the poll starts once the scope is known');
    // The poll fails: reported as possibly out of date, retried later on one timer; then it recovers.
    poll.state.activity = () => Promise.reject(new Error('Synthetic poll outage'));
    await poll.timers.fire();
    html = decode(await view.rerender());
    assert.match(html, /Activity could not be read \(Synthetic poll outage\); the map may be out of date/);
    assert.equal(poll.timers.timers.size, 1);
    assert.equal(timersOf(poll)[0].ms, IDLE_MS, 'retried at the idle interval');
    delete poll.state.activity;
    await poll.timers.fire();
    html = decode(await view.rerender());
    assert.doesNotMatch(html, /Activity could not be read/);
    assert.equal(poll.timers.timers.size, 1, 'no duplicate timer');
    assert.equal(poll.state.reads.length, 2, 'no duplicate poll');
    assert.equal(view.env.reads(level), 2, 'no duplicate level read');
  } finally { view.close(); }
});

test('a circle request bubble keeps its own actor on every page, and a truncated step keeps its own attempt', async () => {
  const map = syntheticMap('budget');
  const home = await renderMap({ name: 'home' }, { map });
  try {
    home.driver.host.elements.find(element => element.props.className === 'map-actor-requests' && element.props['aria-label'].includes('executor')).props.onClick(CLICK);
    let html = decode(await home.rerender());
    assert.match(html, /75 requests waiting/, 'the E count');
    const listed = () => home.driver.host.elements.filter(element => element.props.className === 'map-request-open').map(element => element.props.children);
    assert.equal(listed().length, 50);
    assert.ok(listed().every(text => text === 'Task permission request'), 'only E items, never R clarifications');
    home.driver.host.elements.find(element => element.type === 'button' && element.props.children === 'Load more').props.onClick();
    html = decode(await home.rerender());
    assert.equal(listed().length, 75, 'every E item, and only those');
    assert.ok(listed().every(text => text === 'Task permission request'));
    const lists = home.env.requests.filter(request => request.url.includes('/bubbles')).map(request => request.url);
    assert.equal(lists.length, 2);
    assert.ok(lists.every(url => url.includes('circle=E')), 'the circle is kept while paging');
    assert.match(lists[1], /cursor=/);
  } finally { home.close(); }
  const steps = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' }, { map: syntheticMap('budget') });
  try {
    const running = steps.driver.host.elements.find(element => element.props.className === 'map-bubble' && element.props['aria-label'] === '75 requests waiting.');
    assert.ok(running, 'the running executor step bubble (75 > 20 listed)');
    running.props.onClick(CLICK);
    await steps.rerender();
    assert.deepEqual(steps.env.requests.filter(request => request.url.includes('/bubbles')).map(request => request.url),
      [`/api/managed/map/projects/kp-atlas/bubbles?run=${steps.map.deepRun}&attempt=att-atlas-6`], 'the step’s run and attempt, not the whole run');
    const items = steps.driver.host.elements.filter(element => element.props.className === 'map-request-open');
    assert.equal(items.length, 50);
    assert.ok(items.every(element => element.props.children === 'Task permission request'));
  } finally { steps.close(); }
});

test('the archive table reaches every step’s details, invocations and requests from the keyboard, read-only', async () => {
  const map = syntheticMap('review', { archive: true });
  const poll = pollDeps();
  poll.state.map = map;
  const view = await renderMap({ name: 'task', project: DEEP.key, phase: 'P002', task: 'P002-T005' }, { map, archive: true, poll, display: 'table' });
  try {
    const html = decode(view.html);
    assert.doesNotMatch(html, /data-node=/, 'no SVG needed');
    const details = view.driver.host.elements.filter(element => element.type === 'button' && /^Details of /.test(element.props.children));
    assert.equal(details.length, view.driver.host.elements.filter(element => element.type === 'tr').length - 1, 'one control per row (header excluded)');
    assert.ok(details.length > 4);
    const invocations = [...html.matchAll(/href="(\/projects\/kp-atlas\/invocations\/[^"]+)"/g)].map(match => match[1]);
    assert.ok(invocations.includes('/projects/kp-atlas/invocations/inv-atlas-executor-2'), 'the running executor invocation');
    assert.ok(invocations.length >= 4, 'every step actor opens its invocation');
    details.find(button => button.props.children === 'Details of Executor #1').props.onClick();
    const inspected = decode(await view.rerender());
    for (const label of ['Harness attempt', 'Revision round', 'Native turns', 'Requested model', 'Observed steps']) assert.match(inspected, new RegExp(label), label);
    assert.match(inspected, /aria-pressed="true"[^>]*>Details of Executor #1/);
    // The running executor row opens its own requests, read-only.
    view.driver.host.elements.find(element => element.type === 'button' && element.props.children === '1 request waiting.').props.onClick();
    const requests = decode(await view.rerender());
    assert.match(requests, /Requests of Executor #/);
    assert.match(requests, /Read-only: answers are not possible here/);
    assert.doesNotMatch(requests, /type="checkbox"|<textarea|Grant/);
    assert.equal(view.env.timers.timers.size, 0, 'no timer');
    assert.equal(poll.timers.timers.size, 0);
    assert.ok(view.env.requests.every(request => request.method === 'GET' && /^\/api\/managed\/(map|inbox)\//.test(request.url)));
  } finally { view.close(); }
});

test('concurrent invocations stay separate circles: a reviewer and a chat on R, and the chat lane of the run shown at L3', async () => {
  const map = syntheticMap('review', { reviewer: true });
  const task = tasksView([map.tasks('atlas', DEEP.phase)], 'atlas', DEEP.phase, T).nodes.find(node => node.id === DEEP.task);
  const lanes = task.actors.filter(actor => actor.role === 'R');
  assert.deepEqual(lanes.map(actor => [actor.active, !!actor.chat, actor.target?.invocation]), [[true, false, 'inv-atlas-reviewer-3'], [true, true, 'inv-atlas-chat-1']]);
  assert.equal(task.actors.filter(actor => actor.role === 'J').length, 1, 'J as T020 shows it, once');
  assert.equal(task.actors.filter(actor => actor.role === 'H').length, 1, 'H stays one circle');
  assert.equal(lanes.filter(actor => actor.requests).length, 1, 'the circle’s requests on one actor only');
  const card = projectsView([map.projects()], false, T).nodes[0];
  assert.equal(card.actors.filter(actor => actor.role === 'R' && actor.active).length, 2);

  const level = await renderMap({ name: 'phase', project: 'atlas', phase: 'P002' }, { map });
  try {
    const anchors = level.driver.host.elements.filter(element => element.props['data-actor'] === 'R' && element.props.href);
    const hrefs = anchors.map(element => element.props.href);
    assert.ok(hrefs.includes('/projects/atlas/invocations/inv-atlas-reviewer-3'), 'the review is drawn');
    assert.ok(hrefs.includes('/projects/atlas/invocations/inv-atlas-chat-1'), 'beside the chat');
    assert.match(decode(level.html), /Open the reviewer chat invocation/);
    assert.match(level.html, /class="map-label map-chat-label"/);
  } finally { level.close(); }

  const poll = pollDeps();
  const plain = syntheticMap('review');
  poll.state.map = plain;
  const steps = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' }, { map: plain, poll });
  try {
    // Re-review: the lane comes with the run's steps read (its own snapshot), not with a later activity read.
    const html = decode(steps.html);
    assert.equal(poll.state.reads.length, 0, 'no activity read yet');
    assert.ok(nodeIds(html).includes('chat:inv-atlas-chat-1'), 'the chat attached to the run is its own lane');
    assert.match(steps.html, /href="\/projects\/atlas\/invocations\/inv-atlas-chat-1"[^>]*data-actor="R"|data-actor="R"[^>]*href="\/projects\/atlas\/invocations\/inv-atlas-chat-1"/, 'opening the chat invocation (rendered)');
    const view = stepsView([plain.steps('atlas', plain.deepRun)], 'atlas', T, plain.steps('atlas', plain.deepRun).chats);
    assert.ok(view.edges.every(edge => !edge.from.startsWith('chat:') && !edge.to.startsWith('chat:')), 'not part of the step sequence');
    assert.equal(view.nodes.filter(node => node.id.startsWith('chat:')).length, 1);
    assert.equal(view.nodes.length, stepsView([plain.steps('atlas', plain.deepRun)], 'atlas', T).nodes.length + 1, 'no task step fabricated');
    steps.driver.host.elements.find(element => element.props['data-node'] === 'chat:inv-atlas-chat-1').props.onFocus();
    const inspected = decode(await steps.rerender());
    assert.match(inspected, /A conversation attached to this run; it is not a step of the run\./);
    assert.match(inspected, /Chat · Chat · reviewer|Chat · /);
    // Another run's view never shows it.
    assert.deepEqual(chatsOf(plain.activity([]).active_invocations, DEEP.key, 'run-atlas-010'), []);
  } finally { steps.close(); }
});

test('evidence links open the run page with its evidence even when the map is the remembered view, and after a reload', async () => {
  const map = syntheticMap('review');
  const storage = new Map([[VIEW_STORAGE, 'map']]);
  const runPath = `/projects/atlas/phases/P002/tasks/P002-T005/runs/${map.deepRun}`;
  const ordinary = { read_only_archive: false, configuration_mode: 'READY' };
  const page = (env, mode = ordinary) => { const driver = hookHost(); return { driver, render: () => driver.render(el(I18nProvider, { fixed: 'en' }, el(ServiceModeContext.Provider, { value: mode }, el(Page, { route: parse(window.location.pathname) })))) }; };
  forgetViewMemory();
  let env = browser(map, { path: runPath, storage });
  let host = page(env);
  try {
    let html = decode(await host.render());
    assert.match(html, /data-node=/, 'the map is the remembered view');
    const link = host.driver.host.elements.find(element => element.type === 'a' && element.props.children === 'Run evidence');
    assert.equal(link.props.href, `${runPath}?view=list`, 'the summary link is not the current path');
    link.props.onClick({ button: 0, preventDefault() {}, defaultPrevented: false });
    assert.deepEqual(env.pushes, [`${runPath}?view=list`]);
    // The test hook host keys state by position, so the page the navigation mounts is rendered on a fresh host.
    host.driver.close();
    host = page(env);
    html = decode(await host.render());
    assert.match(html, /aria-pressed="true"[^>]*><span aria-hidden="true" class="map-view-mark map-view-list"/, 'the existing run page is mounted');
    assert.ok(env.requests.some(request => request.url.startsWith(`/api/managed/runs/${map.deepRun}`)), 'its own run read');
    assert.equal(storage.get(VIEW_STORAGE), 'map', 'the remembered choice is unchanged');
    assert.equal(viewOf(''), 'map', 'cards and breadcrumbs keep entering the map');
  } finally { host.driver.close(); env.close(); forgetViewMemory(); }
  // Reloading the link mounts the list again.
  env = browser(map, { path: runPath, search: '?view=list', storage });
  host = page(env);
  try {
    const html = decode(await host.render());
    assert.match(html, /aria-pressed="true"[^>]*><span aria-hidden="true" class="map-view-mark map-view-list"/);
    assert.ok(!env.requests.some(request => request.url.startsWith('/api/managed/map/')));
  } finally { host.driver.close(); env.close(); forgetViewMemory(); }
  // The invocation header links there too; archives open their run consultation; the short URL keeps the view.
  for (const archive of [false, true]) {
    const project = archive ? DEEP.key : 'atlas';
    env = browser(syntheticMap('review', { archive }), { path: `/projects/${project}/invocations/inv-atlas-executor-2`, storage });
    host = page(env, { read_only_archive: archive, configuration_mode: 'READY' });
    try {
      const html = decode(await host.render());
      assert.match(html, new RegExp(`href="${archive ? `/runs/${map.deepRun}"` : `${runPath.replace('atlas', project)}\\?view=list"`}>Run evidence`), String(archive));
    } finally { host.driver.close(); env.close(); }
  }
  let resolved = 0;  // the short URL's own read; the run page mounted afterwards answers like a missing run
  env = browser(map, { path: `/runs/${map.deepRun}`, search: '?view=list', answer: url => url === `/api/managed/runs/${map.deepRun}` && !resolved++
    ? { status: 200, body: { id: map.deepRun, project_id: 'atlas', phase_id: 'P002', task_id: 'P002-T005' } } : undefined });
  host = page(env);
  try {
    await host.render();
    assert.equal(`${window.location.pathname}${window.location.search}`, `${runPath}?view=list`, 'the short URL resolves and keeps ?view=list');
  } finally { host.driver.close(); env.close(); forgetViewMemory(); }
});

// --- re-review corrections (T022 §10) --------------------------------------------------------------------------

const rendered = (html, text) => new RegExp(`<button[^>]*>${text}</button>`).test(html);

test('a failed run selector reread after a valid empty read is shown with a mounted "Read again"; retrying shows the first run in place', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  const runs = '/api/managed/map/projects/atlas/phases/P002/tasks/P002-T004/runs';
  const steps = '/api/managed/map/projects/atlas/runs/run-P002-T004/steps';
  let down = false;
  const view = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T004' }, { map, poll, failing: url => down && url.startsWith(runs) });
  try {
    assert.match(decode(view.html), /This task has no runs yet\./);
    assert.ok(!rendered(view.html, 'Read again'), 'a valid empty read offers no retry');
    const timers = view.env.timers.timers.size;
    // Its first run is created; activity announces the selector's change and the reread fails.
    map.startRun('P002-T004');
    down = true;
    await poll.timers.fire();
    let html = decode(await view.rerender());
    assert.equal(view.env.reads(runs), 2, 'the announced change is reread once');
    assert.match(html, /class="state state-stale">[^<]*503[^<]*Synthetic outage/, 'the failure is in the rendered HTML');
    assert.ok(rendered(html, 'Read again'), 'with a mounted retry control');
    assert.match(html, /This task has no runs yet\./, 'the last empty read stays, marked possibly out of date');
    assert.equal(view.env.reads(steps), 0);
    assert.equal(poll.timers.timers.size, 1, 'the poll keeps one timer');
    // Retry from the view: one selector read, one read of the first run, no navigation or reload.
    down = false;
    view.driver.host.elements.find(element => element.type === 'button' && element.props.children === 'Read again').props.onClick();
    html = decode(await view.rerender());
    assert.equal(view.env.reads(runs), 3, 'one more selector read');
    assert.equal(view.env.reads(steps), 1, 'and one read of the first run');
    assert.doesNotMatch(html, /This task has no runs yet|Synthetic outage/);
    assert.ok(!rendered(html, 'Read again'), 'the retry is gone once a read works');
    assert.equal(nodeIds(html).length, 1, 'the first run is drawn');
    assert.deepEqual(view.env.pushes, [], 'no navigation');
    assert.equal(poll.timers.timers.size, 1, 'no duplicate poll timer');
    assert.equal(view.env.timers.timers.size, timers, 'no other timer');
    await poll.timers.fire();
    assert.deepEqual([...poll.state.reads.at(-1)].sort(), ['s1.fixture.runs.kp-atlas.P002.P002-T004', 's1.fixture.steps.kp-atlas.run-P002-T004'], 'one aggregated read of both scopes');
    assert.equal(poll.state.reads.length, 2, 'no duplicate poll');
    assert.equal(view.env.reads(runs), 3, 'nothing reread at the same version');
    assert.equal(view.env.reads(steps), 1);
  } finally {
    view.close();
    assert.equal(poll.timers.timers.size, 0);
  }

  // Archives keep polling nothing: the failed read and its retry are the only reads, with no timer at all.
  const archived = syntheticMap('review', { archive: true });
  const quiet = pollDeps();
  quiet.state.map = archived;
  let failed = true;
  const consult = await renderMap({ name: 'task', project: DEEP.key, phase: 'P002', task: 'P002-T004' },
    { map: archived, archive: true, poll: quiet, failing: url => failed && url.includes('/tasks/P002-T004/runs') });
  try {
    assert.match(decode(consult.html), /role="alert"[^>]*>503[^<]*Synthetic outage/);
    assert.ok(rendered(consult.html, 'Read again'));
    failed = false;
    consult.driver.host.elements.find(element => element.type === 'button' && element.props.children === 'Read again').props.onClick();
    const html = decode(await consult.rerender());
    assert.match(html, /The archive records no run of this task\./);
    assert.ok(!rendered(html, 'Read again'));
    assert.equal(quiet.timers.timers.size, 0, 'no poll timer');
    assert.equal(quiet.state.reads.length, 0, 'no activity read');
    assert.equal(consult.env.timers.timers.size, 0, 'no timer at all');
    assert.ok(consult.env.requests.every(request => request.method === 'GET'));
  } finally { consult.close(); }
});

test('L3 takes its chat lane from the run’s steps read: a truncated global activity list hides nothing, and an ended chat leaves', async () => {
  const map = syntheticMap('review');
  const poll = pollDeps();
  poll.state.map = map;
  const steps = `/api/managed/map/projects/atlas/runs/${map.deepRun}/steps`;
  const chats = html => nodeIds(html).filter(id => id.startsWith('chat:'));
  const view = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' }, { map, poll });
  try {
    assert.deepEqual(chats(view.html), ['chat:inv-atlas-chat-1'], 'from the first steps read');
    const count = nodeIds(view.html).length;
    // The next activity lists 50 invocations of other projects and says it is truncated; no version changed.
    poll.state.activity = scopes => {
      const base = map.activity(scopes);
      return { ...base, active_invocations_truncated: true, active_invocations: Array.from({ length: 50 }, (_, i) => ({ ...base.active_invocations[0],
        invocation_id: `inv-other-${i}`, attempt_id: `att-other-${i}`, run_id: `run-other-chat-${i}`, role: 'chat', circle: 'R', lane: 'chat', chat: true,
        project_id: `kp-other-${i}`, scope: { phase: DEEP.phase, task: DEEP.task, run_id: i === 0 ? map.deepRun : `run-other-${i}` } })) };
    };
    await poll.timers.fire();
    let html = await view.rerender();
    assert.equal(poll.state.reads.length, 1);
    assert.equal(view.env.reads(steps), 1, 'same version: nothing reread');
    assert.deepEqual(chats(html), ['chat:inv-atlas-chat-1'], 'still drawn: absence from a truncated list proves nothing');
    assert.equal(nodeIds(html).length, count, 'another project’s chat naming the same run id is never drawn');
    // The chat ends: the run's version changes, its steps are reread once and the lane is empty.
    delete poll.state.activity;
    map.endChat();
    await poll.timers.fire();
    html = await view.rerender();
    assert.equal(view.env.reads(steps), 2, 'the changed run is reread once');
    assert.deepEqual(chats(html), [], 'the ended chat leaves the lane');
    assert.equal(nodeIds(html).length, count - 1, 'the run’s steps stay');
    assert.equal(poll.timers.timers.size, 1, 'one timer');
    assert.deepEqual(view.env.pushes, [], 'no navigation');
  } finally { view.close(); }

  // Another run of the task shows no chat (the fixture's chat is attached to the latest run only).
  const fresh = syntheticMap('review');
  const other = fresh.runs('atlas', DEEP.phase, DEEP.task).items[1].run_id;
  const earlier = await renderMap({ name: 'run', project: 'atlas', phase: 'P002', task: 'P002-T005', run: other }, { map: fresh });
  try {
    assert.ok(nodeIds(earlier.html).length > 0);
    assert.deepEqual(chats(earlier.html), [], `run ${other} has none`);
  } finally { earlier.close(); }

  // Coverage: a cut list says so; a listed chat of another project or run is never drawn.
  const crowded = syntheticMap('review');
  const [chat] = crowded.steps('atlas', crowded.deepRun).chats;
  const listed = [...Array.from({ length: 19 }, (_, i) => ({ ...chat, invocation_id: `inv-atlas-chat-x${i}`, attempt_id: `att-chat-x${i}` })),
    { ...chat, invocation_id: 'inv-foreign-chat', project_id: 'kp-other' }, { ...chat, invocation_id: 'inv-other-run-chat', scope: { ...chat.scope, run_id: 'run-other' } }];
  const answer = url => url.startsWith(`/api/managed/map/projects/atlas/runs/${crowded.deepRun}/steps`)
    ? { status: 200, body: { ...crowded.steps('atlas', crowded.deepRun), chats: [chat, ...listed].slice(0, 20), chats_truncated: true } } : undefined;
  const cut = await renderMap({ name: 'task', project: 'atlas', phase: 'P002', task: 'P002-T005' }, { map: crowded, answer });
  try {
    const drawn = chats(cut.html);
    assert.equal(drawn.length, 20, 'the 20 listed chats of this run and project');
    assert.ok(!drawn.includes('chat:inv-foreign-chat') && !drawn.includes('chat:inv-other-run-chat'));
    assert.match(decode(cut.html), /Only the first 20 active chats attached to this run are shown; more are active\./);
  } finally { cut.close(); }
});

test('an archive’s L3 shows the persisted chat from its single steps read, on the map and in the table: no poll, timer or write', async () => {
  const map = syntheticMap('review', { archive: true });
  for (const display of ['map', 'table']) {
    const poll = pollDeps();
    poll.state.map = map;
    const view = await renderMap({ name: 'task', project: DEEP.key, phase: 'P002', task: 'P002-T005' }, { map, archive: true, poll, display });
    try {
      const html = decode(view.html);
      const target = `/projects/${DEEP.key}/invocations/inv-atlas-chat-1`;
      if (display === 'map') assert.ok(nodeIds(html).includes('chat:inv-atlas-chat-1'), 'its own lane node');
      else assert.match(html, /<td><span class="mono">Chat<\/span><\/td>/, 'its own table row');
      assert.ok(html.includes(`href="${target}"`), `${display}: opening its persisted invocation`);
      assert.equal(view.env.reads(`/api/managed/map/projects/${DEEP.key}/runs/${map.deepRun}/steps`), 1, 'one steps read');
      assert.equal(view.env.reads('/api/managed/map/activity'), 0, 'no activity read');
      assert.equal(poll.state.reads.length, 0, 'no poll');
      assert.equal(poll.timers.timers.size, 0, 'no poll timer');
      assert.equal(view.env.timers.timers.size, 0, 'no timer at all');
      assert.ok(view.env.requests.every(request => request.method === 'GET'), 'no write');
      assert.ok(view.env.requests.every(request => request.url.startsWith('/api/managed/map/')), 'map reads only (no checkout or configuration)');
    } finally { view.close(); }
  }
});
