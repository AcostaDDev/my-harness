// P002-T021: pure parts of the work-map engine — seeds, layered layout, camera, interaction controller, labels and
// rough.js shapes. Synthetic data only; no browser, DOM or service.
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { seedOf } from '../src/map/seed.ts';
import { boundsOf, gridLayout, layeredLayout } from '../src/map/layout.ts';
import { clampPan, coverage, fit, limits, PAN_MARGIN, toScreen, toWorld, zoomAt, between } from '../src/map/camera.ts';
import { ENTER_COVERAGE, GESTURE_GAP_MS, GestureGuard, KEY_PAN, LEAVE_PRESSURE, MapController, NAVIGATION_LOCK_MS, PRESSURE_WINDOW_MS, neighbour } from '../src/map/controller.ts';
import { accessibleDescription, accessibleName, statusText, wrapTitle } from '../src/map/labels.ts';
import { cachedShapes, cardShape, clearShapes, edgeShape } from '../src/map/shapes.ts';
import { STATUS_CLASSES, statusClassOf } from '../src/map/status.ts';
import { transitionMs } from '../src/map/motion.ts';
import { plural, translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const t = language => (key, params) => translate({ en, es }, language, key, params);
const n = language => (key, count, params) => plural({ en, es }, language, key, count, params);

function permutations(items, count, seed = 7) {
  const out = [];
  let state = seed;
  const next = () => (state = (state * 1103515245 + 12345) % 2147483648) / 2147483648;
  for (let i = 0; i < count; i++) {
    const copy = [...items];
    for (let j = copy.length - 1; j > 0; j--) { const k = Math.floor(next() * (j + 1)); [copy[j], copy[k]] = [copy[k], copy[j]]; }
    out.push(copy);
  }
  return out;
}

test('seeds are deterministic, positive 31-bit integers that differ between identities', () => {
  // Pinned values: changing the derivation would redraw every map, so it must be a deliberate change.
  assert.equal(seedOf('task:atlas:P002:P002-T005'), seedOf('task:atlas:P002:P002-T005'));
  assert.equal(seedOf(''), 2166136261 % 2147483647 + 1, 'FNV-1a offset basis');
  assert.equal(seedOf('card:task:atlas:P002:P002-T005'), 183977079);
  const seeds = new Set();
  for (let i = 0; i < 20000; i++) {
    const seed = seedOf(`task:project-${i % 37}:P${i % 11}:T${i}`);
    assert.ok(Number.isInteger(seed) && seed >= 1 && seed <= 2 ** 31 - 1);
    seeds.add(seed);
  }
  assert.ok(seeds.size >= 19990, `collisions: ${20000 - seeds.size}`);
  assert.notEqual(seedOf('card:a'), seedOf('card:b'));
});

test('rough shapes depend only on identity and size: same output in any order, after a cache flush, never jittering', () => {
  clearShapes();
  const a1 = cardShape('task:a', 208, 112), b1 = cardShape('task:b', 208, 112);
  clearShapes();
  const b2 = cardShape('task:b', 208, 112), a2 = cardShape('task:a', 208, 112);
  assert.deepEqual(a2, a1);
  assert.deepEqual(b2, b1);
  assert.notDeepEqual(a1, b1);
  assert.ok(a1.some(path => path.fill) && a1.some(path => !path.fill), 'a filled card and its hand-drawn outline');
  assert.match(a1[0].d, /^M[\d. -]+/);
  const edge = edgeShape('a->b:depends_on', [[0, 0], [100, 50], [200, 40]]);
  assert.deepEqual(edgeShape('a->b:depends_on', [[0, 0], [100, 50], [200, 40]]), edge);
  assert.ok(edge.line.length && edge.head.length);
});

test('the shape cache is bounded (TM15)', () => {
  clearShapes();
  for (let i = 0; i < 4100; i++) cardShape(`task:${i}`, 100, 50);
  assert.equal(cachedShapes(), 4000);
  clearShapes();
});

const graph = {
  nodes: ['A', 'B', 'C', 'D', 'E', 'F'].map(id => ({ id })),
  edges: [
    { from: 'A', to: 'B', kind: 'depends_on' }, { from: 'B', to: 'C', kind: 'depends_on' },
    { from: 'A', to: 'C', kind: 'depends_on' }, { from: 'C', to: 'D', kind: 'depends_on' },
    { from: 'B', to: 'E', kind: 'replaces' },
  ],
};

test('layered layout: longest-path layers, dummy points on long edges, edge kinds kept and no overlaps', () => {
  const layout = layeredLayout(graph.nodes, graph.edges);
  const at = Object.fromEntries(layout.nodes.map(node => [node.id, node]));
  assert.deepEqual(['A', 'B', 'C', 'D', 'E'].map(id => at[id].layer), [0, 1, 2, 3, 2]);
  assert.ok(at.A.x < at.B.x && at.B.x < at.C.x && at.C.x < at.D.x, 'left to right');
  const long = layout.edges.find(edge => edge.from === 'A' && edge.to === 'C');
  assert.equal(long.points.length, 3, 'one dummy point for the skipped layer');
  assert.equal(long.points[0][0], at.A.x + at.A.width);
  assert.equal(long.points.at(-1)[0], at.C.x);
  assert.equal(layout.edges.find(edge => edge.to === 'E').kind, 'replaces');
  // F has no edges: it is packed below the graph.
  assert.ok(at.F.y >= Math.max(...['A', 'B', 'C', 'D', 'E'].map(id => at[id].y + at[id].height)));
  for (const a of layout.nodes) for (const b of layout.nodes) {
    if (a.id < b.id) assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y, `${a.id}/${b.id} overlap`);
  }
  assert.deepEqual(layout.bounds, boundsOf(layout.nodes));
});

test('layout does not depend on the order of nodes or edges', () => {
  const reference = JSON.stringify(layeredLayout(graph.nodes, graph.edges));
  const nodeOrders = permutations(graph.nodes, 6), edgeOrders = permutations(graph.edges, 6, 11);
  nodeOrders.forEach((nodes, i) => assert.equal(JSON.stringify(layeredLayout(nodes, edgeOrders[i])), reference));
  const grid = JSON.stringify(gridLayout(graph.nodes));
  for (const nodes of permutations(graph.nodes, 4)) assert.equal(JSON.stringify(gridLayout(nodes)), grid);
});

test('layout survives cycles, duplicates, self-loops and unknown endpoints', () => {
  const layout = layeredLayout([{ id: 'x' }, { id: 'y' }, { id: 'z' }, { id: 'x' }], [
    { from: 'x', to: 'y', kind: 'depends_on' }, { from: 'y', to: 'z', kind: 'depends_on' }, { from: 'z', to: 'x', kind: 'depends_on' },
    { from: 'x', to: 'y', kind: 'depends_on' }, { from: 'x', to: 'x', kind: 'depends_on' }, { from: 'x', to: 'ghost', kind: 'depends_on' },
  ]);
  assert.deepEqual(layout.nodes.map(node => node.id), ['x', 'y', 'z']);
  assert.equal(layout.edges.length, 3);
  assert.equal(layout.edges.filter(edge => edge.reversed).length, 1);
  const reversed = layout.edges.find(edge => edge.reversed);
  const target = layout.nodes.find(node => node.id === reversed.to);
  assert.equal(reversed.points.at(-1)[0], target.x + target.width, 'a reversed edge still ends at its real target');
});

test('a deep dependency chain lays out without recursion limits', () => {
  const nodes = Array.from({ length: 5000 }, (_, i) => ({ id: `t${String(i).padStart(5, '0')}` }));
  const edges = nodes.slice(1).map((node, i) => ({ from: nodes[i].id, to: node.id, kind: 'depends_on' }));
  const layout = layeredLayout(nodes, edges);
  assert.equal(Math.max(...layout.nodes.map(node => node.layer)), 4999);
});

test('camera: screen/world round trip, fitting, zoom around a fixed point, limits and pan clamp', () => {
  const bounds = { x: 0, y: 0, width: 1000, height: 500 }, viewport = { width: 800, height: 600 };
  const camera = fit(bounds, viewport);
  assert.deepEqual(toScreen(camera, [500, 250]).map(Math.round), [400, 300], 'content centred');
  assert.ok(Math.abs(camera.k - (800 - 96) / 1000) < 1e-9);
  const point = [123, 456];
  assert.deepEqual(toWorld(camera, toScreen(camera, point)).map(v => Math.round(v * 1e6) / 1e6), point);
  const range = limits(bounds, viewport);
  const zoomed = zoomAt(camera, 2, [200, 100], range);
  assert.deepEqual(toWorld(zoomed, [200, 100]).map(v => Math.round(v * 1e6)), toWorld(camera, [200, 100]).map(v => Math.round(v * 1e6)));
  assert.equal(zoomAt(camera, 1000, [0, 0], range).k, range.max);
  assert.equal(zoomAt(camera, 1e-6, [0, 0], range).k, range.min);
  assert.ok(range.min <= camera.k * 0.5 + 1e-9);
  const far = clampPan({ ...camera, x: 1e6, y: -1e6 }, bounds, viewport);
  const [left] = toScreen(far, [0, 0]), [, bottom] = toScreen(far, [1000, 500]);
  assert.ok(left <= viewport.width - PAN_MARGIN + 1e-6 && bottom >= PAN_MARGIN - 1e-6, 'content stays reachable');
  assert.deepEqual(between(camera, zoomed, 0), camera);
  assert.deepEqual(between(camera, zoomed, 1), zoomed);
  assert.ok(Math.abs(coverage({ x: 0, y: 0, k: 2 }, { x: 0, y: 0, width: 200, height: 100 }, viewport) - 0.5) < 1e-9);
});

function harness({ canLeave = true } = {}) {
  let now = 1000;
  const events = [];
  const nodes = [
    { id: 'a', rect: { x: 0, y: 0, width: 200, height: 100 }, enterable: true },
    { id: 'b', rect: { x: 300, y: 0, width: 200, height: 100 }, enterable: true },
    { id: 'c', rect: { x: 0, y: 200, width: 200, height: 100 }, enterable: false },
  ];
  const controller = new MapController({
    nodes, bounds: boundsOf(nodes.map(node => node.rect)), viewport: { width: 1000, height: 600 }, canLeave,
    now: () => now, guard: new GestureGuard(),
    handlers: {
      camera: camera => events.push(['camera', camera]), focus: id => events.push(['focus', id]),
      enter: id => events.push(['enter', id]), leave: () => events.push(['leave']),
    },
  });
  const centre = id => { const rect = nodes.find(node => node.id === id).rect; return toScreen(controller.camera, [rect.x + rect.width / 2, rect.y + rect.height / 2]); };
  return { controller, events, nodes, centre, tick: ms => { now += ms; }, of: kind => events.filter(event => event[0] === kind) };
}
const key = (key, extra = {}) => ({ key, shift: false, ctrl: false, meta: false, alt: false, ...extra });

test('a press below the drag threshold is a click; a drag pans and cancels the click that follows it', () => {
  const { controller, of } = harness();
  const start = controller.camera;
  controller.pointerDown(1, 100, 100, false);
  controller.pointerMove(1, 103, 101);
  assert.deepEqual(controller.camera, start, 'below 5 px nothing moves');
  controller.pointerUp(1);
  assert.equal(controller.takeClick(false), true);

  controller.pointerDown(1, 100, 100, false);
  controller.pointerMove(1, 130, 110);
  controller.pointerMove(1, 140, 120);
  controller.pointerUp(1);
  assert.deepEqual([controller.camera.x - start.x, controller.camera.y - start.y], [40, 20], 'the whole travel pans');
  assert.equal(controller.takeClick(false), false, 'the click ending a drag does not navigate');
  assert.equal(of('enter').length, 0);
  // Touch needs a longer travel before it pans.
  const before = controller.camera;
  controller.pointerDown(2, 0, 0, true);
  controller.pointerMove(2, 8, 0);
  assert.deepEqual(controller.camera, before);
  controller.pointerUp(2);
  assert.equal(controller.takeClick(false), true);
});

test('a keyboard activation is never mistaken for the end of a drag', () => {
  const { controller } = harness();
  controller.pointerDown(1, 0, 0, false);
  controller.pointerMove(1, 50, 0);
  controller.pointerUp(1);
  assert.equal(controller.takeClick(true), true);
});

test('zooming into an enterable node past the threshold enters it exactly once', () => {
  const { controller, of, centre, tick } = harness();
  for (let i = 0; i < 40; i++) controller.wheel({ dx: 0, dy: -120, ...Object.fromEntries([['x', centre('a')[0]], ['y', centre('a')[1]]]), ctrl: false, shift: false, mode: 0 });
  assert.deepEqual(of('enter'), [['enter', 'a']]);
  assert.ok(coverage(controller.camera, { x: 0, y: 0, width: 200, height: 100 }, { width: 1000, height: 600 }) >= ENTER_COVERAGE);
  assert.equal(controller.takeClick(true), false, 'no click navigates while the navigation is pending');
  tick(NAVIGATION_LOCK_MS + 1);
  controller.zoom(1.1, centre('a'));
  assert.equal(of('enter').length, 2, 'the lock only lasts until the route changes or it expires');
});

test('zoom never enters a node without a deeper level, nor through the empty background', () => {
  const { controller, of, centre } = harness();
  for (let i = 0; i < 40; i++) controller.zoom(1.2, centre('c'));
  for (let i = 0; i < 40; i++) controller.zoom(1.2, [990, 590]);
  assert.equal(of('enter').length, 0);
});

test('zooming out past the minimum leaves once; isolated or slow zoom-outs do not', () => {
  const { controller, of, tick } = harness();
  const out = () => controller.wheel({ dx: 0, dy: 100, x: 500, y: 300, ctrl: false, shift: false, mode: 0 });
  for (let i = 0; i < 30 && controller.camera.k > controller.limits.min; i++) out();
  assert.equal(controller.camera.k, controller.limits.min);
  assert.equal(of('leave').length, 0, 'reaching the minimum is not leaving');
  const steps = Math.ceil(LEAVE_PRESSURE / -Math.log(Math.exp(-100 * 0.0015)));
  for (let i = 0; i < steps - 1; i++) { out(); tick(PRESSURE_WINDOW_MS + 1); }
  assert.equal(of('leave').length, 0, 'pressure fades between slow zoom-outs');
  for (let i = 0; i < steps + 3; i++) out();
  assert.deepEqual(of('leave'), [['leave']]);
});

test('without a parent, Escape and zoom-out do nothing and Escape is not consumed', () => {
  const { controller, of } = harness({ canLeave: false });
  assert.equal(controller.key(key('Escape')), false);
  for (let i = 0; i < 60; i++) controller.zoom(0.5, [500, 300]);
  assert.equal(of('leave').length, 0);
});

test('keyboard: arrows move focus spatially, Shift pans, + and − zoom, 0 fits, Escape leaves', () => {
  const { controller, of } = harness();
  assert.equal(controller.key(key('ArrowRight'), 'a'), true);
  assert.deepEqual(of('focus').at(-1), ['focus', 'b']);
  controller.key(key('ArrowDown'), 'a');
  assert.deepEqual(of('focus').at(-1), ['focus', 'c']);
  controller.key(key('ArrowLeft'), 'a');
  assert.deepEqual(of('focus').at(-1), ['focus', 'c'], 'nothing to the left: focus stays');
  controller.key(key('End'));
  assert.deepEqual(of('focus').at(-1), ['focus', 'c']);
  controller.key(key('Home'));
  assert.deepEqual(of('focus').at(-1), ['focus', 'a']);
  const before = controller.camera;
  controller.key(key('ArrowRight', { shift: true }), 'a');
  assert.equal(controller.camera.x, before.x - KEY_PAN);
  const k = controller.camera.k;
  controller.key(key('+'), 'a');
  assert.ok(controller.camera.k > k);
  controller.key(key('-'), 'a');
  assert.ok(Math.abs(controller.camera.k - k) < 1e-9);
  controller.key(key('0'));
  assert.deepEqual(controller.camera, fit(controller['bounds'], { width: 1000, height: 600 }));
  assert.equal(controller.key(key('+', { ctrl: true })), false, 'browser shortcuts are left alone');
  assert.equal(controller.key(key('Escape')), true);
  assert.deepEqual(of('leave'), [['leave']]);
  assert.equal(neighbour([], 'missing', 'left'), undefined);
});

test('keyboard focus pans the camera to reveal an off-screen node', () => {
  const { controller } = harness();
  controller.set({ x: -2000, y: 0, k: 1 });
  controller.focus('a');
  const [x] = toScreen(controller.camera, [0, 0]);
  assert.ok(x >= 0 && x + 200 <= 1000);
});

test('a two-finger pinch zooms around its midpoint and cancels the click', () => {
  const { controller } = harness();
  const start = controller.camera;
  controller.pointerDown(1, 400, 300, true);
  controller.pointerDown(2, 500, 300, true);
  const world = toWorld(controller.camera, [450, 300]);
  controller.pointerMove(2, 600, 300);
  assert.ok(Math.abs(controller.camera.k / start.k - 2) < 1e-9, 'finger distance 100 → 200');
  const [x, y] = toScreen(controller.camera, world);
  assert.ok(Math.abs(x - 500) < 1e-6 && Math.abs(y - 300) < 1e-6, 'the pinched point follows the moving midpoint');
  controller.pointerUp(1);
  controller.pointerUp(2);
  assert.equal(controller.takeClick(false), false);
});

test('reset releases the navigation lock and keeps a given camera', () => {
  const { controller, of, centre } = harness();
  controller.enter('a');
  controller.enter('b');
  assert.equal(of('enter').length, 1);
  const camera = { x: 10, y: 20, k: 1 };
  controller.reset({ nodes: [{ id: 'b', rect: { x: 0, y: 0, width: 200, height: 100 }, enterable: true }], bounds: { x: 0, y: 0, width: 200, height: 100 }, viewport: { width: 1000, height: 600 }, camera, canLeave: true });
  assert.deepEqual(controller.camera, camera);
  controller.enter('b');
  assert.deepEqual(of('enter').at(-1), ['enter', 'b']);
  void centre;
});

test('a resize fits the view again until someone moves it, then only keeps the content reachable', () => {
  const { controller } = harness();
  controller.resize({ width: 375, height: 500 });
  assert.deepEqual(controller.camera, fit(controller['bounds'], { width: 375, height: 500 }), 'still the fitted view');
  controller.pan(30, 0);
  const moved = controller.camera;
  controller.resize({ width: 1200, height: 700 });
  assert.deepEqual(controller.camera, moved, 'a moved view stays where the user left it');
  controller.key(key('0'));
  controller.resize({ width: 800, height: 500 });
  assert.deepEqual(controller.camera, fit(controller['bounds'], { width: 800, height: 500 }));
});

test('reduced motion makes the enter transition immediate', () => {
  assert.equal(transitionMs(true), 0);
  assert.ok(transitionMs(false) > 0 && transitionMs(false) <= 300);
});

test('labels: accessible names carry kind, code, title, status text, active actors and requests in en and es', () => {
  const node = { kind: 'task', code: 'P002-T005', title: 'Añadir reseñas', statusClass: 'waiting', status: 'WAITING_FOR_OWNER',
    actors: [{ role: 'R', active: true }, { role: 'E', active: false }], requests: 2 };
  assert.equal(accessibleName(node, t('en'), n('en')), 'Task P002-T005: Añadir reseñas. Waiting for you. Active: reviewer. 2 requests waiting.');
  assert.equal(accessibleName(node, t('es'), n('es')), 'Tarea P002-T005: Añadir reseñas. Te espera. Activo: revisor. 2 solicitudes pendientes.');
  assert.equal(accessibleDescription(node, { dependsOn: ['P002-T001'], replaces: ['P002-T003'] }, false, t('en')),
    'Status code: WAITING_FOR_OWNER. Depends on P002-T001. Replaces P002-T003. No deeper level.');
  assert.equal(statusText({ statusClass: 'mystery', status: 'LEGACY_HOLD' }, t('es')), 'Desconocido: LEGACY_HOLD');
  for (const cls of STATUS_CLASSES.filter(cls => cls !== 'unknown')) {
    assert.notEqual(statusText({ statusClass: cls, status: 'X' }, t('en')), statusText({ statusClass: cls, status: 'X' }, t('es')), cls);
  }
  assert.equal(statusClassOf('RUNNING'), 'unknown', 'raw persisted values are never guessed into a class');
});

test('titles wrap at word boundaries into two lines with an ellipsis when cut', () => {
  assert.deepEqual(wrapTitle('Small task', 21, 2), ['Small task']);
  assert.deepEqual(wrapTitle('Revisar contratos de la API pública', 21, 2), ['Revisar contratos de', 'la API pública']);
  assert.deepEqual(wrapTitle('Document the archive restore path in detail with every edge case', 21, 2), ['Document the archive', 'restore path in…']);
  assert.deepEqual(wrapTitle('Supercalifragilisticexpialidocious', 21, 2), ['Supercalifragilistic…']);
  for (const line of wrapTitle('a '.repeat(80), 21, 2)) assert.ok(line.length <= 21);
});

// Re-review round 1, finding 1: "fit" must show every card of the accepted level sizes, also on a phone.
const { layoutOf } = await import('../src/map/MapView.tsx');
const { DEEP, fixtureLevel } = await import('../src/map/fixture/data.ts');

function inView(controller, rects, viewport, slack = 1e-6) {
  return rects.filter(rect => {
    const [x1, y1] = toScreen(controller.camera, [rect.x, rect.y]);
    const [x2, y2] = toScreen(controller.camera, [rect.x + rect.width, rect.y + rect.height]);
    return x1 >= -slack && y1 >= -slack && x2 <= viewport.width + slack && y2 <= viewport.height + slack;
  }).length;
}

test('fit shows every card of the D309-size levels on a 375 × 500 phone: initial, fit button, 0 key and resize', () => {
  const phone = { width: 375, height: 500 }, desktop = { width: 1000, height: 600 };
  const levels = {
    'L1 40 phases': fixtureLevel('budget', { name: 'phases', project: DEEP.project }),
    'L2 80 tasks': fixtureLevel('budget', { name: 'phase', project: DEEP.project, phase: DEEP.phase }),
    'L2 200 tasks': fixtureLevel('stress', { name: 'phase', project: DEEP.project, phase: DEEP.phase }),
    'L3 40 steps': fixtureLevel('budget', { name: 'task', project: DEEP.project, phase: DEEP.phase, task: DEEP.task }),
    'L0 25 projects': fixtureLevel('budget', { name: 'home' }),
  };
  for (const [name, level] of Object.entries(levels)) {
    const layout = layoutOf(level.nodes, level.edges, level.arrangement);
    const targets = layout.nodes.map(node => ({ id: node.id, rect: node, enterable: true }));
    const make = viewport => new MapController({ nodes: targets, bounds: layout.bounds, viewport, canLeave: true, guard: new GestureGuard(),
      handlers: { camera() {}, focus() {}, enter() {}, leave() {} } });
    const check = (controller, viewport, when) => {
      const { k, x, y } = controller.camera;
      assert.ok([k, x, y].every(Number.isFinite) && k > 0, `${name} ${when}: finite camera`);
      assert.equal(inView(controller, layout.nodes, viewport), layout.nodes.length, `${name} ${when}: every card in view`);
      const centre = toScreen(controller.camera, [layout.bounds.x + layout.bounds.width / 2, layout.bounds.y + layout.bounds.height / 2]);
      assert.ok(Math.abs(centre[0] - viewport.width / 2) < 1e-6 && Math.abs(centre[1] - viewport.height / 2) < 1e-6, `${name} ${when}: centred`);
      assert.ok(controller.limits.min <= k / 2 + 1e-12, `${name} ${when}: room to zoom out below the fit`);
    };
    const phoneController = make(phone);
    check(phoneController, phone, 'initial');
    phoneController.zoom(3, [100, 100]);
    phoneController.pan(-500, 200);
    assert.ok(inView(phoneController, layout.nodes, phone) < layout.nodes.length);
    phoneController.fit();
    check(phoneController, phone, 'fit button');
    phoneController.pan(80, 0);
    phoneController.key({ key: '0', shift: false, ctrl: false, meta: false, alt: false });
    check(phoneController, phone, '0 key');
    const resized = make(desktop);
    check(resized, desktop, 'desktop');
    resized.resize(phone);
    check(resized, phone, 'resized to phone');
    resized.reset({ nodes: targets, bounds: layout.bounds, viewport: phone, canLeave: true });
    check(resized, phone, 'reset to the level');
  }
});

test('below a tiny fitted scale, panning keeps content reachable and zooming out still leaves', () => {
  const level = fixtureLevel('budget', { name: 'phases', project: DEEP.project });
  const layout = layoutOf(level.nodes, level.edges, level.arrangement);
  let now = 0, left = 0;
  const controller = new MapController({ nodes: layout.nodes.map(node => ({ id: node.id, rect: node, enterable: true })), bounds: layout.bounds,
    viewport: { width: 375, height: 500 }, canLeave: true, now: () => now, guard: new GestureGuard(),
    handlers: { camera() {}, focus() {}, enter() {}, leave: () => { left++; } } });
  assert.ok(controller.camera.k < 0.05, `fitted scale ${controller.camera.k} is below the former 0.05 floor`);
  controller.pan(1e6, -1e6);
  assert.ok(inView(controller, layout.nodes, { width: 375, height: 500 }) >= 0);
  const [right] = toScreen(controller.camera, [layout.bounds.x, layout.bounds.y]);
  assert.ok(right <= 375, 'the content stays reachable');
  controller.fit();
  for (let i = 0; i < 40 && !left; i++) { controller.zoom(0.8, [187, 250]); now += 16; }
  assert.equal(left, 1, 'zooming out past the minimum still returns to the parent');
});

// Re-review round 1, finding 2: one navigation per gesture also across the level change.
function chain({ canLeave = false, guard = new GestureGuard(), reset = true, clock = { now: 0 } } = {}) {
  const viewport = { width: 1000, height: 600 }, rect = { x: 0, y: 0, width: 200, height: 100 };
  const log = [];
  let level = 0;
  const options = () => ({ nodes: [{ id: `n${level}`, rect, enterable: true }], bounds: rect, viewport, canLeave });
  const controller = new MapController({ ...options(), now: () => clock.now, guard,
    handlers: { camera() {}, focus() {}, enter: id => { log.push(['enter', id]); level++; }, leave: () => { log.push(['leave']); level++; } } });
  let shown = level;
  // The view resets the controller when the next level arrives, before the next event of the burst.
  const commit = () => { if (reset && shown !== level) { shown = level; controller.reset(options()); } };
  return { controller, log, guard, tick: ms => { clock.now += ms; }, commit, options, viewport };
}
const wheel = (dy, x = 500, y = 300) => ({ dx: 0, dy, x, y, ctrl: false, shift: false, mode: 0 });

test('one wheel burst enters one level even though each new level resets the controller', () => {
  for (const spacing of [0, 16]) {
    const { controller, log, tick, commit } = chain();
    for (let i = 0; i < 15; i++) { controller.wheel(wheel(-120)); commit(); tick(spacing); }
    assert.deepEqual(log, [['enter', 'n0']], `events ${spacing} ms apart`);
    // A pause ends the gesture: the next deliberate burst enters the next level, once.
    tick(GESTURE_GAP_MS);
    for (let i = 0; i < 15; i++) { controller.wheel(wheel(-120)); commit(); tick(16); }
    assert.deepEqual(log, [['enter', 'n0'], ['enter', 'n1']]);
  }
});

test('the rest of a burst neither zooms nor navigates; a click or a press right after is not blocked', () => {
  const { controller, log, tick, commit } = chain();
  for (let i = 0; i < 6; i++) { controller.wheel(wheel(-120)); commit(); tick(16); }
  assert.equal(log.length, 1);
  const camera = controller.camera;
  controller.wheel(wheel(-120));
  assert.deepEqual(controller.camera, camera, 'continuation events are ignored on the new level');
  assert.equal(controller.takeClick(false), true);
  controller.enter('n1');
  assert.deepEqual(log.at(-1), ['enter', 'n1'], 'a deliberate click navigates at once');
  commit();
  controller.pointerDown(1, 10, 10, false);
  controller.pointerUp(1);
  for (let i = 0; i < 15; i++) { controller.wheel(wheel(-120)); commit(); tick(16); }
  assert.equal(log.filter(([kind]) => kind === 'enter').length, 3, 'a pointer press starts a new gesture');
});

test('one zoom-out burst leaves one level', () => {
  const { controller, log, tick, commit } = chain({ canLeave: true });
  for (let i = 0; i < 60; i++) { controller.wheel(wheel(150)); commit(); tick(16); }
  assert.deepEqual(log, [['leave']]);
});

test('a remounted view sharing the page guard ignores the rest of the gesture', () => {
  const guard = new GestureGuard(), clock = { now: 0 };
  const first = chain({ guard, clock, reset: false });
  for (let i = 0; i < 15 && !first.log.length; i++) { first.controller.wheel(wheel(-120)); first.tick(16); }
  assert.equal(first.log.length, 1);
  // The parent mounts a new view (and controller) for the next level while the same burst goes on.
  const second = chain({ guard, clock, reset: false });
  for (let i = 0; i < 10; i++) { second.controller.wheel(wheel(-120)); second.tick(16); }
  assert.deepEqual(second.log, []);
  second.tick(GESTURE_GAP_MS);
  for (let i = 0; i < 15; i++) { second.controller.wheel(wheel(-120)); second.tick(16); }
  assert.deepEqual(second.log, [['enter', 'n0']], 'after a pause the new view responds');
});

test('key auto-repeat after Escape, + or Enter never navigates twice; a fresh press does', () => {
  const k = (key, repeat = false) => ({ key, shift: false, ctrl: false, meta: false, alt: false, repeat });
  const { controller, log, tick, commit } = chain({ canLeave: true });
  assert.equal(controller.key(k('Escape')), true);
  commit();
  for (let i = 0; i < 10; i++) { tick(30); assert.equal(controller.key(k('Escape', true)), true, 'repeat swallowed'); commit(); }
  assert.deepEqual(log, [['leave']]);
  tick(30);
  controller.key(k('Escape'));
  commit();
  assert.deepEqual(log, [['leave'], ['leave']], 'a new press leaves again');
  // Keyboard activation (Enter on a link) followed by its auto-repeat on the next level's focused node.
  tick(400);
  controller.key(k('Enter'));
  controller.enter('n2', 'key');
  commit();
  for (let i = 0; i < 5; i++) { tick(30); assert.equal(controller.key(k('Enter', true)), true, 'the repeat is consumed, so the link is not activated'); }
  // Holding + zooms in until it enters once.
  const zoom = chain();
  zoom.controller.focus('n0');
  zoom.controller.key(k('+'));
  for (let i = 0; i < 30; i++) { zoom.tick(30); zoom.controller.key(k('+', true), 'n0'); zoom.commit(); }
  assert.equal(zoom.log.length, 1);
});

test('a Safari trackpad pinch enters once; a new pinch is a new gesture', () => {
  const { controller, log, tick, commit } = chain();
  controller.gestureStart();
  for (let i = 0; i < 30; i++) { controller.gestureZoom(1.15, [500, 300]); commit(); tick(16); }
  assert.equal(log.length, 1);
  controller.gestureStart();
  for (let i = 0; i < 30; i++) { controller.gestureZoom(1.15, [500, 300]); commit(); tick(16); }
  assert.equal(log.length, 2);
});

// Re-review round 2: key continuity does not expire with the wheel's 300 ms gap.
test('a held key that navigated stays ignored even when its first auto-repeat comes after 300 ms', () => {
  const k = (key, repeat = false) => ({ key, shift: false, ctrl: false, meta: false, alt: false, repeat });
  const late = GESTURE_GAP_MS + 200;

  // Escape at t=0 leaves; the level resets; the first repeat at t=500 and later ones never leave again.
  const esc = chain({ canLeave: true });
  assert.equal(esc.controller.key(k('Escape')), true);
  esc.commit();
  esc.tick(late);
  assert.equal(esc.controller.key(k('Escape', true)), true, 'late repeat consumed');
  esc.commit();
  for (let i = 0; i < 5; i++) { esc.tick(late); esc.controller.key(k('Escape', true)); esc.commit(); }
  assert.deepEqual(esc.log, [['leave']]);
  esc.controller.key(k('Escape'));
  esc.commit();
  assert.deepEqual(esc.log, [['leave'], ['leave']], 'a fresh press leaves at once, without waiting');

  // Enter activation on a link, then a late auto-repeat on the next level's focused node.
  const enter = chain();
  assert.equal(enter.controller.key(k('Enter')), false, 'a fresh Enter is left to the link activation');
  enter.controller.enter('n0', 'key');
  enter.commit();
  enter.tick(late);
  assert.equal(enter.controller.key(k('Enter', true)), true, 'the late repeat is consumed, so the next link is not activated');
  enter.tick(late);
  assert.equal(enter.controller.key(k('Enter', true)), true);
  assert.equal(enter.controller.key(k('Enter')), false, 'a fresh Enter activates normally');
  enter.controller.enter('n1', 'key');
  assert.deepEqual(enter.log, [['enter', 'n0'], ['enter', 'n1']]);

  // Holding + zooms until it enters; a late repeat on the next level neither zooms nor enters.
  const zoom = chain();
  zoom.controller.key(k('+'), 'n0');
  for (let i = 0; i < 30 && !zoom.log.length; i++) { zoom.tick(30); zoom.controller.key(k('+', true), 'n0'); }
  assert.equal(zoom.log.length, 1);
  zoom.commit();
  const camera = zoom.controller.camera;
  for (let i = 0; i < 10; i++) { zoom.tick(late); assert.equal(zoom.controller.key(k('+', true), 'n1'), true); zoom.commit(); }
  assert.deepEqual(zoom.controller.camera, camera, 'late repeats do not zoom the new level');
  assert.equal(zoom.log.length, 1);
  zoom.controller.key(k('+'), 'n1');
  assert.notDeepEqual(zoom.controller.camera, camera, 'a fresh + zooms at once');
});

test('the wheel gap still applies and a pointer press still ends a held-key gesture', () => {
  const k = (key, repeat = false) => ({ key, shift: false, ctrl: false, meta: false, alt: false, repeat });
  const esc = chain({ canLeave: true });
  esc.controller.key(k('Escape'));
  esc.commit();
  esc.controller.pointerDown(1, 5, 5, false);
  esc.controller.pointerUp(1);
  esc.tick(GESTURE_GAP_MS + 200);
  esc.controller.key(k('Escape', true));
  esc.commit();
  assert.equal(esc.log.length, 2, 'after a pointer press the guard no longer holds the key');
  // Wheel continuity keeps expiring with its gap (one entry per burst, a new one after a pause).
  const wheelChain = chain();
  for (let i = 0; i < 15; i++) { wheelChain.controller.wheel(wheel(-120)); wheelChain.commit(); wheelChain.tick(16); }
  wheelChain.tick(GESTURE_GAP_MS);
  for (let i = 0; i < 15; i++) { wheelChain.controller.wheel(wheel(-120)); wheelChain.commit(); wheelChain.tick(16); }
  assert.deepEqual(wheelChain.log, [['enter', 'n0'], ['enter', 'n1']]);
});
