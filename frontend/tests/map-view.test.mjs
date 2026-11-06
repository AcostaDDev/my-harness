// P002-T021: the SVG map view rendered with React (server markup), its binding to the existing router and browser
// history, and the synthetic fixture. No browser, DOM, API or service is started.
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const { I18nProvider } = await import('../src/Language.tsx');
const { MapView } = await import('../src/map/MapView.tsx');
const { mapLevel, mapNavigation, mapParent, mapPath, mapRoute, forgetViews, recallView, rememberView } = await import('../src/map/routes.ts');
const { MapController } = await import('../src/map/controller.ts');
const { DEEP, SCENARIOS, SIZES, fixtureLevel } = await import('../src/map/fixture/data.ts');
const { FIXTURE_TEXT } = await import('../src/map/fixture/text.ts');
const { FIXTURE_BASE } = await import('../src/map/fixture/FixtureApp.tsx');
const { STATUS_CLASSES } = await import('../src/map/status.ts');
const { boundsOf } = await import('../src/map/layout.ts');
const { parse } = await import('../src/router.ts');

const tasksRoute = { name: 'phase', project: DEEP.project, phase: DEEP.phase };
const stepsRoute = { name: 'task', project: DEEP.project, phase: DEEP.phase, task: DEEP.task };

function view(level, { language = 'en', motion, viewKey = '/k', onEnter = () => {}, onLeave, controllerRef } = {}) {
  return renderToStaticMarkup(el(I18nProvider, { fixed: language }, el(MapView, {
    viewKey, label: 'map', nodes: level.nodes, edges: level.edges, arrangement: level.arrangement,
    hrefOf: route => mapPath(route, FIXTURE_BASE), onEnter, onLeave, motion, controllerRef,
  })));
}
const nodesOf = html => [...html.matchAll(/<(a|g) [^>]*data-node="([^"]+)"[^>]*>/g)].map(match => ({ tag: match[1], id: match[2], html: match[0] }));
const attr = (html, name) => html.match(new RegExp(`${name}="([^"]*)"`))?.[1];
const decode = text => text.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');

test('every node is a focusable, labelled SVG element and exactly one is in the tab order', () => {
  for (const language of ['en', 'es']) {
    const level = fixtureLevel('normal', tasksRoute);
    const html = view(level, { language });
    const nodes = nodesOf(html);
    assert.equal(nodes.length, level.nodes.length);
    assert.equal(nodes.filter(node => attr(node.html, 'tabindex') === '0').length, 1, 'roving tabindex');
    assert.ok(nodes.every(node => ['0', '-1'].includes(attr(node.html, 'tabindex'))));
    for (const node of nodes) {
      const data = level.nodes.find(item => item.id === node.id);
      const label = decode(attr(node.html, 'aria-label'));
      assert.ok(label.startsWith(`${language === 'en' ? 'Task' : 'Tarea'} ${data.code}: `), label);
      assert.ok(label.includes(data.title), label);
      assert.ok(decode(attr(node.html, 'aria-description')).includes(data.status), 'raw status code in the description');
      // Enterable nodes are real links to the existing route (under the fixture base).
      assert.equal(node.tag, 'a');
      assert.equal(attr(node.html, 'href'), `${FIXTURE_BASE}/projects/atlas/phases/P002/tasks/${encodeURIComponent(data.code)}`);
    }
    assert.match(html, /role="toolbar"/);
    assert.match(html, /aria-describedby="[^"]+-help"/);
  }
});

test('nodes without a deeper level are focusable labelled images, not links', () => {
  const html = view(fixtureLevel('normal', stepsRoute));
  const nodes = nodesOf(html);
  assert.ok(nodes.length && nodes.every(node => node.tag === 'g' && attr(node.html, 'role') === 'img' && !attr(node.html, 'href')));
  assert.ok(nodes.every(node => decode(attr(node.html, 'aria-description')).endsWith('No deeper level.')));
});

test('the six classes and unknown are drawn with icon, colour class and status text in both languages', () => {
  for (const [route, scenario] of [[{ name: 'home' }, 'normal'], [{ name: 'phases', project: DEEP.project }, 'normal'], [tasksRoute, 'normal'], [stepsRoute, 'normal'], [tasksRoute, 'budget']]) {
    const level = fixtureLevel(scenario, route);
    for (const language of ['en', 'es']) {
      const html = view(level, { language });
      for (const cls of STATUS_CLASSES) {
        assert.match(html, new RegExp(`class="map-node map-status-${cls}"`), `${route.name} ${cls}`);
        assert.match(html, new RegExp(`<symbol id="[^"]+-icon-${cls}"`), cls);
        assert.match(html, new RegExp(`<use href="#[^"]+-icon-${cls}"`), cls);
        if (cls === 'unknown') continue;
        const text = translate({ en, es }, language, `map.status.${cls}`);
        assert.match(html, new RegExp(`class="map-label map-status-text" x="14" y="\\d+">${text}</text>`), `${cls} ${language}`);
      }
      assert.match(html, /map-status-text[^>]*>(Unknown|Desconocido): (LEGACY_HOLD|X_FUTURE_STATE)</, 'unknown shows the raw code');
    }
  }
});

test('markup does not depend on the input order and shapes do not move with the camera', () => {
  forgetViews();
  const level = fixtureLevel('budget', tasksRoute);
  const reference = view(level);
  const shuffled = { ...level, nodes: [...level.nodes].reverse(), edges: [...level.edges].reverse() };
  assert.equal(view(shuffled), reference, 'same DOM for reordered data');
  assert.equal(view(level), reference, 'same DOM on refresh');
  rememberView('/moved', { camera: { x: -420, y: 133, k: 0.7 } });
  const moved = view(level, { viewKey: '/moved' });
  const world = html => html.replace(/<g transform="translate\([^"]*\) scale\([^"]*\)">/, '<g transform="CAMERA">');
  assert.notEqual(moved, reference);
  assert.equal(world(moved), world(reference), 'only the world transform differs');
  forgetViews();
});

test('depends_on and replaces edges are drawn distinctly and named in the node description', () => {
  const level = fixtureLevel('normal', tasksRoute);
  const html = view(level);
  assert.ok(level.edges.some(edge => edge.kind === 'replaces') && level.edges.some(edge => edge.kind === 'depends_on'));
  assert.match(html, /<g class="map-edge map-edge-depends_on">/);
  assert.match(html, /<g class="map-edge map-edge-replaces">/);
  assert.match(html, /<g class="map-edges" aria-hidden="true">/);
  const replaced = level.edges.find(edge => edge.kind === 'replaces');
  const target = nodesOf(html).find(node => node.id === replaced.to);
  const code = level.nodes.find(node => node.id === replaced.from).code;
  assert.ok(decode(attr(target.html, 'aria-description')).includes(`Replaces ${code}`));
});

test('reduced motion: static activity marks and an immediate enter; otherwise the camera finishes the zoom first', () => {
  const level = fixtureLevel('normal', { name: 'home' });
  assert.match(view(level, { motion: 'reduce' }), /class="map" data-motion="reduce"/);
  assert.match(view(level, { motion: 'allow' }), /class="map" data-motion="allow"/);
  assert.match(view(level), /data-motion="allow"/, 'without a stated preference the server render allows motion');
  assert.match(view(level), /class="map-rays"/, 'an active actor has rays');

  const frames = [];
  globalThis.requestAnimationFrame = callback => frames.push(callback);
  globalThis.cancelAnimationFrame = () => {};
  try {
    for (const motion of ['reduce', 'allow']) {
      const entered = [], controllerRef = {};
      view(level, { motion, controllerRef, onEnter: node => entered.push(node.id) });
      frames.length = 0;
      controllerRef.current.enter('project:atlas');
      if (motion === 'reduce') { assert.deepEqual(entered, ['project:atlas']); assert.equal(frames.length, 0); continue; }
      assert.deepEqual(entered, [], 'the transition runs before navigating');
      const start = performance.now();
      frames.shift()(start + 100);
      assert.deepEqual(entered, []);
      frames.shift()(start + 400);
      assert.deepEqual(entered, ['project:atlas']);
      controllerRef.current.enter('project:atlas');
      assert.equal(frames.filter(Boolean).length <= 1 && entered.length, 1, 'no duplicate navigation while locked');
    }
  } finally { delete globalThis.requestAnimationFrame; delete globalThis.cancelAnimationFrame; }
});

test('map levels map onto the existing routes; Escape and zoom-out go to the parent level', () => {
  assert.deepEqual([{ name: 'home' }, { name: 'phases', project: 'p' }, { name: 'phase', project: 'p', phase: 'P1' },
    { name: 'task', project: 'p', phase: 'P1', task: 'T' }, { name: 'run', project: 'p', phase: 'P1', task: 'T', run: 'r' },
    { name: 'phase', project: 'p', phase: 'P1', section: 'check' }, { name: 'project', project: 'p' }].map(mapLevel), [0, 1, 2, 3, 3, undefined, undefined]);
  assert.deepEqual(mapParent({ name: 'phases', project: 'p' }), { name: 'home' });
  assert.deepEqual(mapParent({ name: 'phase', project: 'p', phase: 'P1' }), { name: 'phases', project: 'p' });
  assert.deepEqual(mapParent({ name: 'run', project: 'p', phase: 'P1', task: 'T', run: 'r' }), { name: 'phase', project: 'p', phase: 'P1' });
  assert.equal(mapParent({ name: 'home' }), undefined);
  for (const route of [{ name: 'home' }, { name: 'phases', project: 'bitácora-001' }, { name: 'task', project: 'p', phase: 'v1.2', task: 'P#1?x' }]) {
    assert.deepEqual(mapRoute(mapPath(route)), route);
    assert.deepEqual(mapRoute(mapPath(route, FIXTURE_BASE), FIXTURE_BASE), route);
    assert.deepEqual(mapRoute(mapPath(route, FIXTURE_BASE), FIXTURE_BASE), parse(mapPath(route)));
  }
  assert.equal(mapPath({ name: 'home' }, FIXTURE_BASE), '/__map-fixture/');
  assert.equal(mapRoute('/projects/p/phases', FIXTURE_BASE).name, 'not-found', 'outside the base is not a fixture level');
});

function fakeWindow(pathname) {
  const pushes = [];
  globalThis.window = {
    location: { pathname },
    history: { pushState(_state, _title, path) { pushes.push(path); window.location.pathname = path; }, replaceState(_state, _title, path) { window.location.pathname = path; } },
    addEventListener() {}, removeEventListener() {},
  };
  return pushes;
}

test('zoom-enter and leave go through the shared router and history, once per navigation', () => {
  forgetViews();
  const pushes = fakeWindow(`${FIXTURE_BASE}/`);
  try {
    const level = fixtureLevel('normal', { name: 'home' });
    const nav = mapNavigation(window.location.pathname, FIXTURE_BASE);
    const byId = new Map(level.nodes.map(node => [node.id, node]));
    const rect = { x: 0, y: 0, width: 224, height: 124 };
    const controller = new MapController({
      nodes: [{ id: 'project:atlas', rect, enterable: true }], bounds: boundsOf([rect]), viewport: { width: 1000, height: 600 }, canLeave: !!nav.parent,
      handlers: { camera() {}, focus() {}, enter: id => nav.enter(byId.get(id).to, id), leave: () => nav.leave() },
    });
    for (let i = 0; i < 50; i++) controller.wheel({ dx: 0, dy: -120, x: 500, y: 300, ctrl: false, shift: false, mode: 0 });
    assert.deepEqual(pushes, [`${FIXTURE_BASE}/projects/atlas/phases`], 'one history entry for a continuous zoom');
    nav.enter(byId.get('project:atlas').to, 'project:atlas');
    assert.equal(pushes.length, 1, 'navigating to the current path adds nothing');
    assert.equal(recallView(`${FIXTURE_BASE}/`).focus, 'project:atlas', 'the parent will focus the entered node again');

    const inner = mapNavigation(window.location.pathname, FIXTURE_BASE);
    assert.equal(inner.level, 1);
    inner.leave();
    assert.deepEqual(pushes.at(-1), `${FIXTURE_BASE}/`);
    assert.equal(mapNavigation(`${FIXTURE_BASE}/`, FIXTURE_BASE).parent, undefined);
    mapNavigation(`${FIXTURE_BASE}/`, FIXTURE_BASE).leave();
    assert.equal(pushes.length, 2, 'the top level has nowhere to go');
  } finally { delete globalThis.window; forgetViews(); }
});

test('the fixture is reproducible, follows the D309 sizes and covers every class at every level', () => {
  const routes = [{ name: 'home' }, { name: 'phases', project: DEEP.project }, tasksRoute, stepsRoute,
    { name: 'run', project: DEEP.project, phase: DEEP.phase, task: DEEP.task, run: DEEP.run }];
  for (const scenario of SCENARIOS) {
    const counts = routes.map(route => fixtureLevel(scenario, route).nodes.length);
    const size = SIZES[scenario];
    assert.deepEqual(counts, [size.projects, size.phases, size.tasks, size.steps, size.steps], scenario);
    for (const route of routes) {
      const level = fixtureLevel(scenario, route);
      assert.equal(JSON.stringify(fixtureLevel(scenario, route)), JSON.stringify(level), 'deterministic');
      assert.deepEqual(new Set(level.nodes.map(node => node.statusClass)), new Set(STATUS_CLASSES), `${scenario} ${route.name}`);
      assert.equal(new Set(level.nodes.map(node => node.id)).size, level.nodes.length, 'unique identities');
    }
  }
  assert.deepEqual(SIZES.budget, { projects: 25, phases: 40, tasks: 80, steps: 40 });
  assert.equal(SIZES.stress.tasks, 200);
  // Leaf siblings (D309): only the deep path has children.
  assert.equal(fixtureLevel('budget', { name: 'phases', project: 'cobalt-002' }).nodes.length, 0);
  assert.equal(fixtureLevel('budget', { name: 'phase', project: DEEP.project, phase: 'P003' }).nodes.length, 0);
  assert.equal(fixtureLevel('normal', { name: 'chat', project: 'atlas' }), undefined);
  const titles = fixtureLevel('stress', tasksRoute).nodes.map(node => node.title).join(' ');
  for (const sample of ['ñ', '¿', '«', '—', '…', 'Ł', 'ť', 'ő', 'О', '日']) assert.ok(titles.includes(sample), sample);
});

test('fixture texts have English and Spanish with the same keys and fields', () => {
  const fields = text => [...text.matchAll(/\{([a-z_]+)\}/g)].map(match => match[1]).sort();
  assert.deepEqual(Object.keys(FIXTURE_TEXT.es).sort(), Object.keys(FIXTURE_TEXT.en).sort());
  for (const [key, text] of Object.entries(FIXTURE_TEXT.en)) {
    assert.ok(text.trim() && FIXTURE_TEXT.es[key].trim() && FIXTURE_TEXT.es[key] !== text, key);
    assert.deepEqual(fields(FIXTURE_TEXT.es[key]), fields(text), key);
  }
});
