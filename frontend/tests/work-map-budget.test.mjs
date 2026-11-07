// P002-T022: D309's first-render budget for an 80-node L2 built from T020-shaped projections (T018 §12). This is a
// server render in Node with plain React (no test hook host): adapters, layered layout, rough.js shapes and markup.
// It is not a browser measurement (no style, layout or paint) and does not replace one.
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { translate, plural } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const { I18nProvider } = await import('../src/Language.tsx');
const { MapView } = await import('../src/map/MapView.tsx');
const { clearShapes } = await import('../src/map/shapes.ts');
const { tasksView } = await import('../src/map/projection.ts');
const { syntheticMap, DEEP } = await import('../src/map/fixture/projections.ts');
const { href } = await import('../src/router.ts');

const T = { t: (key, params) => translate({ en, es }, 'en', key, params), n: (key, count, params) => plural({ en, es }, 'en', key, count, params), language: 'en' };

test('first render of an 80-node L2 from T020 projections stays within 500 ms (server render, cold shape cache)', () => {
  const read = syntheticMap('budget').tasks('atlas', DEEP.phase);
  assert.equal(read.items.length, 80);
  const samples = [];
  let html = '';
  for (let i = 0; i < 15; i++) {
    clearShapes();
    const start = performance.now();
    const view = tasksView([read], 'atlas', DEEP.phase, T);
    html = renderToStaticMarkup(el(I18nProvider, { fixed: 'en' }, el(MapView, { viewKey: `/budget/${i}`, label: 'map', nodes: view.nodes,
      edges: view.edges, arrangement: view.arrangement, hrefOf: href, onEnter() {}, onSelect() {}, onActor() {}, onRequests() {} })));
    samples.push(performance.now() - start);
  }
  assert.equal([...html.matchAll(/data-node="/g)].length, 80);
  const sorted = [...samples].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  console.log(`[P002-T022 SSR] L2 80 nodes, cold shape cache, ${samples.length} samples: first ${samples[0].toFixed(1)} ms, `
    + `median ${median.toFixed(1)} ms, p90 ${sorted[Math.floor(sorted.length * 0.9)].toFixed(1)} ms, max ${sorted.at(-1).toFixed(1)} ms`);
  assert.ok(median <= 500 && samples[0] <= 500, `median ${median} ms, first ${samples[0]} ms`);
});
