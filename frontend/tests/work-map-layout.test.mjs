// P002-T022 browser corrections: card rows (status and counter never share a line), labels fitted to their card at
// L0–L3 in English and Spanish, the CSS that hides a closed bottom sheet's body on narrow screens, and the focus kept
// when the window narrows. Server markup and fakes only; the overlap, Tab order and focus visibility themselves were
// measured in a browser (see docs/phase/P002-T022-work-map.md §11).
import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createElement as el } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { translate, plural } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const { I18nProvider } = await import('../src/Language.tsx');
const { MapView, CARD_FONT, CARD_SIZES, cardText } = await import('../src/map/MapView.tsx');
const { projectsView, phasesView, tasksView, stepsView } = await import('../src/map/projection.ts');
const { syntheticMap, DEEP } = await import('../src/map/fixture/projections.ts');
const { fitLine, lineFits, wrapTitle, statusText } = await import('../src/map/labels.ts');
const { textWidth, fitsWithin } = await import('../src/map/text-fit.ts');
const { keepSheetFocus, SHEET_MEDIA } = await import('../src/map/sheet-focus.ts');
const { href } = await import('../src/router.ts');

const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const texts = language => ({ t: (key, params) => translate({ en, es }, language, key, params), n: (key, count, params) => plural({ en, es }, language, key, count, params), language });
const decode = text => text.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const SIZE = { 'map-code': CARD_FONT.code, 'map-title': CARD_FONT.title, 'map-status-text': CARD_FONT.status, 'map-counter': CARD_FONT.counter, 'map-badge': CARD_FONT.badge, 'map-slot-label': CARD_FONT.slot, 'map-slot-actors': CARD_FONT.slot };

function render(view, language) {
  return renderToStaticMarkup(el(I18nProvider, { fixed: language }, el(MapView, {
    viewKey: '/k', label: 'map', nodes: view.nodes, edges: view.edges, arrangement: view.arrangement, hrefOf: route => href(route), onEnter() {},
  })));
}

/** Each card: its size, accessible name and the labels drawn inside its link (slots are those under `map-slot`). */
function cards(html) {
  return [...html.matchAll(/<(a|g) ([^>]*data-node="([^"]+)"[^>]*)>([\s\S]*?)<\/\1>(?=<(?:a|g) [^>]*data-node=|<\/g>)/g)].map(match => {
    const [, , attrs, id, body] = match;
    const ring = body.match(/class="map-focus-ring" x="-7" y="-7" width="(\d+)" height="(\d+)"/);
    const labels = [...body.matchAll(/<text class="map-label (map-[a-z-]+)" x="([\d.-]+)" y="([\d.-]+)"( text-anchor="end")?>([^<]*)<\/text>/g)]
      .map(([, cls, x, y, end, text]) => ({ cls, x: +x, y: +y, end: !!end, text: decode(text) }));
    return { id, name: decode(attrs.match(/aria-label="([^"]*)"/)[1]), width: +ring[1] - 14, height: +ring[2] - 14, labels };
  });
}

function levels(scenario, language) {
  const map = syntheticMap(scenario), T = texts(language);
  const run = map.steps('atlas', map.deepRun);
  return {
    L0: projectsView([map.projects()], false, T),
    L1: phasesView([map.phases('atlas')], 'atlas', T),
    L2: tasksView([map.tasks('atlas', DEEP.phase)], 'atlas', DEEP.phase, T),
    L3: stepsView([run], 'atlas', T, run.chats),
  };
}

/** Status and counter rows apart, every label inside its row; returns the cards seen. */
function assertRows(html, where) {
  const seen = cards(html);
  assert.ok(seen.length > 0, where);
  for (const card of seen) {
    const at = `${where} ${card.id}`;
    const one = cls => card.labels.filter(label => label.cls === cls);
    const [status] = one('map-status-text'), [counter] = one('map-counter'), titles = one('map-title'), [code] = one('map-code'), [badge] = one('map-badge');
    assert.ok(status, `${at}: status drawn`);
    assert.equal(status.x, 14, at);
    assert.ok(titles.every(line => status.y - line.y >= 20), `${at}: the status row is below the title`);
    if (counter) {
      assert.equal(counter.x, 14, `${at}: the counter starts its own row`);
      assert.equal(counter.end, false, `${at}: no longer right-aligned against the status`);
      assert.ok(counter.y - status.y >= 16, `${at}: counter row below the status row (${status.y} → ${counter.y})`);
      assert.ok(counter.y <= card.height - 8, `${at}: counter inside the card`);
    }
    for (const label of [status, counter, ...titles].filter(Boolean))
      assert.ok(label.x + textWidth(label.text, SIZE[label.cls]) <= card.width - 14, `${at}: "${label.text}" fits its row`);
    assert.ok(code.x + textWidth(code.text, CARD_FONT.code) <= (badge ? badge.x - textWidth(badge.text, CARD_FONT.badge) - 8 : card.width - 26), `${at}: code fits`);
    // A cut label keeps its full text in the accessible name.
    for (const label of [status, counter].filter(Boolean)) if (label.text.endsWith('…')) assert.ok(card.name.includes(label.text.slice(0, -1)), at);
    const slots = card.labels.filter(label => label.cls.startsWith('map-slot-'));
    for (const label of slots) assert.ok(label.x + textWidth(label.text, CARD_FONT.slot) <= Math.round(card.width / 3) - 6, `${at}: slot "${label.text}" fits its third`);
  }
  return seen;
}

test('status and counter have rows of their own and every label fits its card at L0–L3, review and budget, en/es', () => {
  for (const scenario of ['review', 'budget']) for (const language of ['en', 'es']) {
    const all = levels(scenario, language);
    for (const [level, view] of Object.entries(all)) assertRows(render(view, language), `${scenario} ${language} ${level}`);
  }
});

test('the reported overlaps are drawn on separate rows: P002-T007 and P002-T009 in Spanish and English', () => {
  for (const [language, unknown, waiting, attempt, absent] of [
    ['es', 'Desconocido: MYSTERY', 'Te espera', 'Intento 1/3', 'Intentos: no observado'],
    ['en', 'Unknown: MYSTERY', 'Waiting for you', 'Attempt 1/3', 'Attempts: not observed']]) {
    const seen = assertRows(render(levels('review', language).L2, language), `review ${language} L2`);
    const label = (id, cls) => seen.find(card => card.id === id).labels.find(item => item.cls === cls);
    assert.equal(label('P002-T007', 'map-status-text').text, unknown, 'the raw code stays visible');
    assert.equal(label('P002-T007', 'map-counter').text, attempt);
    assert.equal(label('P002-T009', 'map-status-text').text, waiting);
    assert.equal(label('P002-T009', 'map-counter').text, absent, '"not observed" stays visible, never zero');
    for (const id of ['P002-T007', 'P002-T009']) assert.ok(label(id, 'map-counter').y > label(id, 'map-status-text').y, id);
  }
});

test('long codes, counters, titles, badges and slots are cut to their row and stay whole in the accessible name', () => {
  const T = texts('es');
  const nodes = [
    { id: 'p', kind: 'project', code: 'proyecto-con-un-nombre-muy-largo', badge: 'Autónomo', title: 'P002 · WWWWWWWWWWWWWWWWWWWWWWWWWWWWWW', statusClass: 'x', status: 'X_FUTURE_STATE_WITH_A_VERY_LONG_NAME', counter: 'Fases: no observado' },
    { id: 'f', kind: 'phase', code: 'P002', title: 'Un título largo con palabras', statusClass: 'waiting', status: 'READY', counter: 'Tareas 126/180',
      slots: [{ key: 'plan', label: 'Planificación extensa', statusClass: 'done', actors: ['R', 'E', 'J', 'H'] }, { key: 'check', label: 'Revisión', actors: [] }, { key: 'close', label: 'Cierre', statusClass: 'failed', actors: ['H'] }] },
    { id: 's', kind: 'step', code: 'Ejecutor #12', title: 'claude · claude-synthetic-model-with-a-long-name', statusClass: 'progress', status: 'RUNNING', counter: 'Duración: no observada' },
  ];
  for (const node of nodes) {
    const html = render({ nodes: [node], edges: [], arrangement: 'grid' }, 'es');
    const [card] = assertRows(html, node.id);
    const status = card.labels.find(label => label.cls === 'map-status-text');
    assert.ok(card.name.includes(statusText(node, T.t)), 'the full status text is in the accessible name');
    assert.ok(card.name.includes(node.counter), 'the full counter is in the accessible name');
    assert.ok(decode(html).includes(T.t('map.node.raw_status', { code: node.status })), 'the raw code is in the accessible description');
    if (node.id === 'p') {
      assert.ok(status.text.startsWith('X_FUTURE_STATE') && status.text.endsWith('…'), `the raw code first, cut only when it does not fit: ${status.text}`);
      assert.ok(card.labels.find(label => label.cls === 'map-code').text.endsWith('…'), 'a long project name is cut beside its badge');
      assert.equal(card.labels.find(label => label.cls === 'map-badge').text, 'Autónomo');
    }
  }
  // The card text helper cuts at a character, never drops the raw code entirely.
  const text = cardText({ code: 'P1', title: '', counter: 'Intentos: no observado' }, 'Desconocido: SOME_EXTREMELY_LONG_STATUS_CODE_VALUE', CARD_SIZES.step.width);
  assert.match(text.status, /^Desconocido: SOME.*…$/);
  assert.equal(text.counter, 'Intentos: no observado');
  // An unknown status that does not fit keeps its raw code visible, whole when the code alone fits.
  const unknown = (status, code) => cardText({ code: 'P1', title: '' }, status, CARD_SIZES.task.width, code).status;
  assert.equal(unknown('Desconocido: MYSTERY', 'MYSTERY'), 'Desconocido: MYSTERY', 'the full text when it fits');
  assert.equal(unknown('Desconocido: X_FUTURE_STATE', 'X_FUTURE_STATE'), 'X_FUTURE_STATE');
  assert.match(unknown('Desconocido: X_FUTURE_STATE_WITH_A_VERY_LONG_NAME', 'X_FUTURE_STATE_WITH_A_VERY_LONG_NAME'), /^X_FUTURE_STATE_.*…$/);
});

test('line fitting: character budgets keep the old wrapping, width budgets cut at a character with "…"', () => {
  assert.deepEqual(wrapTitle('Revisar contratos de la API pública', 21, 2), ['Revisar contratos de', 'la API pública']);
  assert.deepEqual(wrapTitle('Supercalifragilisticexpialidocious', 21, 2), ['Supercalifragilistic…']);
  const fits = fitsWithin(14, 100);
  assert.equal(fitLine('Fallido', fits), 'Fallido');
  const long = 'Desconocido: MYSTERY_CODE', cut = fitLine(long, fits);
  assert.ok(cut.endsWith('…') && lineFits(cut, fits), cut);
  assert.equal(lineFits(`${long.slice(0, cut.length)}…`, fits), false, 'the longest prefix that fits');
  for (const line of wrapTitle('WWWW '.repeat(30), fitsWithin(16, 176), 2)) assert.ok(textWidth(line, 16) <= 176, line);
  assert.ok(textWidth('WW', 14) > textWidth('ii', 14), 'per-character widths');
  assert.ok(textWidth('Ñandú', 14) >= textWidth('Nandu', 14), 'accented letters measure as their base letter or more');
  assert.equal(textWidth('', 14), 0);
});

test('a maximum-length title fits the task card with bounded glyph work', () => {
  const title = 'W'.repeat(65_536);
  const iterate = String.prototype[Symbol.iterator];
  let measured = 0;
  let lines;
  String.prototype[Symbol.iterator] = function* () {
    for (const character of iterate.call(this)) {
      if (character === 'W') measured++;
      assert.ok(measured <= title.length * 2, 'truncation must not repeatedly measure long prefixes');
      yield character;
    }
  };
  try {
    lines = cardText({ code: 'P002-T022', title }, 'Running', CARD_SIZES.task.width).title;
  } finally {
    String.prototype[Symbol.iterator] = iterate;
  }
  assert.match(lines.join(''), /^W+…$/);
  assert.equal(lines.length, 1);
  assert.ok(textWidth(lines[0], CARD_FONT.title) < CARD_SIZES.task.width);

  const budget = { limit: 6, advance(character) {
    assert.notEqual(character, 'X', 'words past the final visible row are not measured');
    return character.length;
  } };
  assert.deepEqual(wrapTitle('aaaaaa bbbbbb cccccc X'.repeat(2_000), budget, 2), ['aaaaaa', 'bbbbb…']);
});

test('ellipsis preserves surrogate pairs and whole graphemes', () => {
  assert.equal(fitLine('😀😀😀', 4), '😀…');
  assert.equal(fitLine('Ae\u0301BBB', 3), 'A…');
  assert.equal(fitLine('A👩‍💻BBBB', 5), 'A…');
});

test('card font sizes and the sheet breakpoint equal styles.css; a closed sheet hides its body only on narrow screens', () => {
  const size = selector => Number(css.match(new RegExp(`\\${selector} \\{[^}]*font-size: (\\d+)px`))?.[1]);
  assert.equal(size('.map-code'), CARD_FONT.code);
  assert.equal(size('.map-title'), CARD_FONT.title);
  assert.equal(size('.map-status-text'), CARD_FONT.status);
  assert.equal(size('.map-counter'), CARD_FONT.counter);
  assert.equal(size('.map-badge'), CARD_FONT.badge);
  assert.equal(size('.map-slot-label'), CARD_FONT.slot);
  assert.equal(size('.map-slot-actors'), CARD_FONT.slot);
  const blocks = css.split(`@media ${SHEET_MEDIA} {`).slice(1).map(rest => rest.slice(0, rest.indexOf('\n}\n')));
  const narrow = blocks.find(block => block.includes('.map-inspector'));
  assert.ok(narrow, `the sheet's media rule is ${SHEET_MEDIA}`);
  assert.match(narrow, /\.map-page:not\(\.map-sheet-open\) \.map-inspector-body \{ display: none; \}/, 'closed: the body is not rendered (no Tab stop, no accessible content)');
  assert.match(narrow, /\.map-inspector-body \{[^}]*overflow-y: auto/, 'open: only the body scrolls');
  assert.doesNotMatch(narrow, /\.map-sheet-open \.map-inspector \{[^}]*overflow-y/, 'the sheet itself never scrolls its heading away');
  assert.match(narrow, /\.map-sheet-toggle \{ display: inline-flex; flex: none; \}/, 'the toggle keeps its size beside a long title');
  assert.match(narrow, /\.map-inspector-head h2 \{[^}]*text-overflow: ellipsis/, 'a closed sheet shows one line of the title');
  const wide = css.replace(narrow, '');
  assert.doesNotMatch(wide, /map-inspector-body[^{]*\{[^}]*display: none/, 'wide screens always show the body');
});

/** Fakes for `keepSheetFocus`: a media query, a document with focus events and focusable elements. */
function sheetHost() {
  const listeners = { focusin: new Set(), focusout: new Set(), change: new Set() };
  const frames = [];
  const element = name => ({ name, isConnected: true, visible: true, focused: 0, revealed: 0,
    focus() { this.focused++; document.activeElement = this; }, scrollIntoView() { this.revealed++; }, checkVisibility() { return this.visible; } });
  const inside = element('run link'), other = element('toolbar button'), page = { name: 'page body' };
  const sheet = { transitions: [], addEventListener(type, listener, options) { this.transitions.push({ type, listener, options }); } };
  let body = { contains: node => node === inside, parentElement: sheet };
  const document = { activeElement: page, body: page,
    addEventListener: (type, listener) => listeners[type].add(listener), removeEventListener: (type, listener) => listeners[type].delete(listener) };
  const query = { matches: false, addEventListener: (type, listener) => listeners[type].add(listener), removeEventListener: (type, listener) => listeners[type].delete(listener) };
  let opened = 0;
  const stop = keepSheetFocus({ query, document, body: () => body, open: () => { opened++; inside.visible = true; }, frame: callback => frames.push(callback) });
  return {
    inside, other, page, sheet, listeners, document, stop,
    get opened() { return opened; },
    focus(target, related = null) {
      const previous = document.activeElement;
      if (previous && previous !== page) listeners.focusout.forEach(listener => listener({ target: previous, relatedTarget: target }));
      document.activeElement = target;
      listeners.focusin.forEach(listener => listener({ target, relatedTarget: related }));
    },
    blurTo(target, related = null) { listeners.focusout.forEach(listener => listener({ target: document.activeElement, relatedTarget: related })); document.activeElement = target; },
    resize(matches) { query.matches = matches; listeners.change.forEach(listener => listener()); },
    flushFrame() { frames.splice(0).forEach(callback => callback()); },
    narrow(matches = true) { this.resize(matches); this.flushFrame(); },
    replacePanel() { body = { ...body }; },
  };
}

test('narrowing the window keeps the focus in the inspector: the sheet opens and the control is focused and revealed', () => {
  // Focus still in the body when the change is reported.
  let host = sheetHost();
  host.focus(host.inside);
  host.narrow();
  assert.equal(host.opened, 1, 'the sheet opens');
  assert.equal(host.document.activeElement, host.inside);
  assert.equal(host.inside.focused, 0, 'a kept focus is not moved');
  assert.equal(host.inside.revealed, 1, 'revealed at once');
  assert.deepEqual(host.sheet.transitions.map(item => [item.type, item.options.once]), [['transitionend', true]], 'and again when the sheet has grown');
  host.sheet.transitions[0].listener();
  assert.equal(host.inside.revealed, 2);
  host.stop();
  assert.equal(host.listeners.focusin.size + host.listeners.focusout.size + host.listeners.change.size, 0, 'removed on unmount');

  // The browser dropped the focus (hidden body) before reporting the change: it is restored.
  host = sheetHost();
  host.focus(host.inside);
  host.inside.visible = false;
  host.blurTo(host.page);
  host.narrow();
  assert.equal(host.opened, 1);
  assert.equal(host.document.activeElement, host.inside, 'the dropped focus comes back');
  assert.equal(host.inside.focused, 1);

  // Widening never opens anything.
  host = sheetHost();
  host.focus(host.inside);
  host.narrow(false);
  assert.equal(host.opened, 0);
});

test('narrowing never takes the focus from elsewhere, nor after the focus left the inspector', () => {
  let host = sheetHost();
  host.focus(host.inside);
  host.focus(host.other);
  host.narrow();
  assert.equal(host.opened, 0, 'focus elsewhere: the sheet stays as it was');
  assert.equal(host.document.activeElement, host.other);

  // Focus moved without a focusin event (a window without system focus): the remembered control does not win.
  host = sheetHost();
  host.focus(host.inside);
  host.document.activeElement = host.other;
  host.narrow();
  assert.equal(host.opened, 0);
  assert.equal(host.document.activeElement, host.other, 'never taken from a control outside the inspector');

  // A click on the page leaves a visible control for nothing: it is forgotten.
  host = sheetHost();
  host.focus(host.inside);
  host.blurTo(host.page);
  host.narrow();
  assert.equal(host.opened, 0);
  assert.equal(host.inside.focused, 0);

  // A control that was removed is not focused again.
  host = sheetHost();
  host.focus(host.inside);
  host.inside.visible = false;
  host.blurTo(host.page);
  host.inside.isConnected = false;
  host.narrow();
  assert.equal(host.opened, 0);
});

test('deferred restoration and transition reveal leave newer focus alone', () => {
  const host = sheetHost();
  host.focus(host.inside);
  host.resize(true);
  host.focus(host.other);
  host.flushFrame();
  assert.equal(host.document.activeElement, host.other);
  assert.equal(host.inside.focused, 0);
  assert.equal(host.inside.revealed, 0);
  assert.equal(host.sheet.transitions.length, 0);

  host.focus(host.inside);
  host.narrow();
  assert.equal(host.inside.revealed, 1);
  host.focus(host.other);
  host.sheet.transitions[0].listener();
  assert.equal(host.inside.revealed, 1);
});

test('pending restoration is discarded after widening, panel replacement or cleanup', () => {
  for (const invalidate of [host => host.resize(false), host => host.replacePanel(), host => host.stop()]) {
    const host = sheetHost();
    host.focus(host.inside);
    host.inside.visible = false;
    host.blurTo(host.page);
    host.resize(true);
    invalidate(host);
    host.flushFrame();
    assert.equal(host.document.activeElement, host.page);
    assert.equal(host.inside.revealed, 0);
  }
});
