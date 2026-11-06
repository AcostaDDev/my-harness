// P002-T021 re-review round 1: the real MapView crossing level changes. Views are rendered with the hook host's
// opt-in lifecycle (layout effects and memoized values across commits), the fixture's router binding under its base
// and a fake `window.history`, so every navigation is a real `pushState` through `navigation.tsx`. Synthetic data only.
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { MapView, layoutOf } = await import('../src/map/MapView.tsx');
const { forgetViews, mapNavigation, mapPath } = await import('../src/map/routes.ts');
const { GESTURE_GAP_MS, pageGestures } = await import('../src/map/controller.ts');
const { toScreen } = await import('../src/map/camera.ts');
const { fixtureLevel } = await import('../src/map/fixture/data.ts');
const { FIXTURE_BASE } = await import('../src/map/fixture/FixtureApp.tsx');
delete globalThis.__tsxHookHarness;

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const levels = new Map();
const levelAt = path => levels.get(path) ?? levels.set(path, fixtureLevel('normal', mapNavigation(path, FIXTURE_BASE).route)).get(path);

function setup(motion) {
  forgetViews();
  pageGestures.end();
  levels.clear();
  const pushes = [], frames = [];
  globalThis.window = {
    location: { pathname: `${FIXTURE_BASE}/` },
    history: { pushState(_s, _t, path) { pushes.push(path); window.location.pathname = path; }, replaceState() {} },
    addEventListener() {}, removeEventListener() {},
  };
  globalThis.document = { documentElement: {}, activeElement: null };
  globalThis.requestAnimationFrame = callback => frames.push(callback);
  globalThis.cancelAnimationFrame = () => {};
  const controllerRef = {};
  let driver = hookHost();
  driver.host.lifecycle = true;
  const app = () => {
    const path = window.location.pathname;
    const nav = mapNavigation(path, FIXTURE_BASE);
    const level = levelAt(path);
    return el(I18nProvider, { fixed: 'en' }, el(MapView, {
      viewKey: path, label: 'map', nodes: level.nodes, edges: level.edges, arrangement: level.arrangement, motion,
      hrefOf: route => mapPath(route, FIXTURE_BASE), controllerRef,
      onEnter: node => nav.enter(node.to, node.id), onLeave: nav.parent ? nav.leave : undefined,
    }));
  };
  let shown = '';
  const env = {
    pushes, frames, controllerRef,
    /** Commits the current location, as React does between two events of a burst after a navigation. */
    async commit() { if (shown !== window.location.pathname) { shown = window.location.pathname; await driver.render(app()); } },
    async remount() { driver.close(); driver = hookHost(); driver.host.lifecycle = true; shown = window.location.pathname; await driver.render(app()); },
    /** Screen centre of a card of the level on screen. */
    centre(id) {
      const level = levelAt(window.location.pathname);
      const rect = layoutOf(level.nodes, level.edges, level.arrangement).nodes.find(node => node.id === id);
      return toScreen(controllerRef.current.camera, [rect.x + rect.width / 2, rect.y + rect.height / 2]);
    },
    wheel(dy, [x, y]) { controllerRef.current.wheel({ dx: 0, dy, x, y, ctrl: false, shift: false, mode: 0 }); },
    flush(now) { for (const frame of frames.splice(0)) frame(now); },
    close() { driver.close(); delete globalThis.window; delete globalThis.document; delete globalThis.requestAnimationFrame; delete globalThis.cancelAnimationFrame; forgetViews(); pageGestures.end(); },
  };
  return env;
}

test('reduced motion: a wheel burst enters one level and stays there; after a pause the next burst enters the next', async () => {
  const env = setup('reduce');
  try {
    await env.commit();
    const at = env.centre('project:atlas');
    for (let i = 0; i < 25; i++) { env.wheel(-120, at); await env.commit(); }
    assert.deepEqual(env.pushes, [`${FIXTURE_BASE}/projects/atlas/phases`], 'one history entry for the burst');
    assert.ok(Object.values(env.controllerRef.current.camera).every(Number.isFinite), 'finite camera on the new level');

    await sleep(GESTURE_GAP_MS + 50);
    const phase = env.centre('phase:atlas:P002');
    for (let i = 0; i < 25; i++) { env.wheel(-120, phase); await env.commit(); }
    assert.deepEqual(env.pushes, [`${FIXTURE_BASE}/projects/atlas/phases`, `${FIXTURE_BASE}/projects/atlas/phases/P002`]);

    // Leaving: one zoom-out burst returns one level, even though the parent is also zoomable out to its minimum.
    await sleep(GESTURE_GAP_MS + 50);
    for (let i = 0; i < 80; i++) { env.wheel(200, [400, 300]); await env.commit(); }
    assert.deepEqual(env.pushes.slice(2), [`${FIXTURE_BASE}/projects/atlas/phases`]);
  } finally { env.close(); }
});

test('with the transition: the burst finishes the zoom, navigates once and its tail is ignored on the next level', async () => {
  const env = setup('allow');
  try {
    await env.commit();
    const at = env.centre('project:atlas');
    for (let i = 0; i < 12; i++) env.wheel(-120, at);
    assert.deepEqual(env.pushes, [], 'nothing navigates before the camera transition ends');
    const start = performance.now();
    env.flush(start + 100);
    assert.deepEqual(env.pushes, []);
    env.flush(start + 400);
    assert.deepEqual(env.pushes, [`${FIXTURE_BASE}/projects/atlas/phases`]);
    await env.commit();
    for (let i = 0; i < 12; i++) { env.wheel(-120, [500, 300]); env.flush(performance.now() + 400); await env.commit(); }
    assert.equal(env.pushes.length, 1, 'the rest of the burst does not enter a phase');
  } finally { env.close(); }
});

test('a view remounted for the next level keeps ignoring the navigating burst', async () => {
  const env = setup('reduce');
  try {
    await env.commit();
    const at = env.centre('project:atlas');
    let i = 0;
    for (; i < 25 && !env.pushes.length; i++) env.wheel(-120, at);
    assert.equal(env.pushes.length, 1);
    await env.remount();
    for (; i < 40; i++) env.wheel(-120, env.centre('phase:atlas:P002'));
    assert.equal(env.pushes.length, 1);
  } finally { env.close(); }
});

test('Escape and its auto-repeat leave one level; a fresh Escape leaves the next', async () => {
  const env = setup('reduce');
  window.location.pathname = `${FIXTURE_BASE}/projects/atlas/phases/P002`;
  const key = (repeat = false) => ({ key: 'Escape', shift: false, ctrl: false, meta: false, alt: false, repeat });
  try {
    await env.commit();
    env.controllerRef.current.key(key());
    await env.commit();
    for (let i = 0; i < 8; i++) { env.controllerRef.current.key(key(true)); await env.commit(); }
    assert.deepEqual(env.pushes, [`${FIXTURE_BASE}/projects/atlas/phases`]);
    env.controllerRef.current.key(key());
    await env.commit();
    assert.deepEqual(env.pushes, [`${FIXTURE_BASE}/projects/atlas/phases`, `${FIXTURE_BASE}/`]);
  } finally { env.close(); }
});

test('a held key whose first auto-repeat arrives after 300 ms navigates once across the level change', async () => {
  const env = setup('reduce');
  window.location.pathname = `${FIXTURE_BASE}/projects/atlas/phases/P002`;
  const key = (name, repeat = false) => ({ key: name, shift: false, ctrl: false, meta: false, alt: false, repeat });
  const late = GESTURE_GAP_MS + 200;
  try {
    await env.commit();
    // Escape held: leave at once, first repeat 500 ms later on the parent level.
    env.controllerRef.current.key(key('Escape'));
    await env.commit();
    await sleep(late);
    assert.equal(env.controllerRef.current.key(key('Escape', true)), true);
    await env.commit();
    assert.deepEqual(env.pushes, [`${FIXTURE_BASE}/projects/atlas/phases`]);

    // + held over the focused phase: zooms until it enters P002, then a late repeat on the task level does nothing.
    assert.equal(env.controllerRef.current.key(key('+'), 'phase:atlas:P002'), true);
    for (let i = 0; i < 40 && env.pushes.length < 2; i++) { env.controllerRef.current.key(key('+', true), 'phase:atlas:P002'); await env.commit(); }
    assert.deepEqual(env.pushes.at(-1), `${FIXTURE_BASE}/projects/atlas/phases/P002`);
    await env.commit();
    const camera = env.controllerRef.current.camera;
    await sleep(late);
    assert.equal(env.controllerRef.current.key(key('+', true), 'task:atlas:P002:P002-T005'), true);
    assert.deepEqual(env.controllerRef.current.camera, camera);
    assert.equal(env.pushes.length, 2);

    // Enter activation (keyboard click on the focused link), then a late repeat on the step level is consumed.
    assert.equal(env.controllerRef.current.key(key('Enter'), 'task:atlas:P002:P002-T005'), false);
    env.controllerRef.current.enter('task:atlas:P002:P002-T005', 'key');
    await env.commit();
    assert.deepEqual(env.pushes.at(-1), `${FIXTURE_BASE}/projects/atlas/phases/P002/tasks/P002-T005`);
    await sleep(late);
    assert.equal(env.controllerRef.current.key(key('Enter', true)), true, 'consumed: the link on the new level is not activated');
    // A fresh Escape works immediately.
    env.controllerRef.current.key(key('Escape'));
    await env.commit();
    assert.deepEqual(env.pushes.at(-1), `${FIXTURE_BASE}/projects/atlas/phases/P002`);
    assert.equal(env.pushes.length, 4);
  } finally { env.close(); }
});
