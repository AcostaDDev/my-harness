// P002-T021 dependency and asset adoption (D308, T018 §10, TM19): exact rough.js pin sharing mermaid's copy, the
// unmodified Excalifont subsets with their hashes and en/es coverage, the font CSS limited to map labels, the OFL
// notice, and label contrast of the status tokens in both themes (§5.1, §11). Offline: reads repository files only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { cmap, names, tables } from './helpers/woff2.mjs';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const read = path => readFileSync(new URL(path, import.meta.url));
const text = path => read(path).toString('utf8');
const FONTS = {
  'Excalifont-Regular-a88b72a24fb54c9f94e3b5fdaa7481c9.woff2': { size: 24956, sha256: 'e4423b318e11432aff2e6e865e300b7ca270f92321a3f56632268fede01c1b48' },
  'Excalifont-Regular-be310b9bcd4f1a43f571c46df7809174.woff2': { size: 12220, sha256: '4fb8ad69be9aeac5664d99e5aa3a68a27ea40c98943b80387f7cd55c034fcc93' },
};
const LATIN = Object.keys(FONTS)[0];
// T018 §10.2: the 125 code points required for English and Spanish labels.
const REQUIRED = [...Array.from({ length: 95 }, (_, i) => String.fromCharCode(0x20 + i)), ...'áéíóúüñÁÉÍÓÚÜÑ¿¡«»·—–…ºª€‘’“”•'];

const covered = Object.fromEntries(Object.keys(FONTS).map(file => [file, cmap(tables(read(`../src/map/fonts/${file}`)).cmap.bytes)]));

function ranges(points) {
  const out = [];
  for (const point of [...points].sort((a, b) => a - b)) {
    const last = out.at(-1);
    if (last && last[1] === point - 1) last[1] = point; else out.push([point, point]);
  }
  const hex = n => n.toString(16).toUpperCase().padStart(4, '0');
  return out.map(([a, b]) => a === b ? `U+${hex(a)}` : `U+${hex(a)}-${hex(b)}`).join(', ');
}

test('roughjs 4.6.6 is a direct exact dependency sharing the locked copy mermaid uses', () => {
  const pkg = JSON.parse(text('../package.json')), lock = JSON.parse(text('../package-lock.json'));
  assert.equal(pkg.dependencies.roughjs, '4.6.6');
  assert.equal(lock.packages[''].dependencies.roughjs, '4.6.6');
  const rough = lock.packages['node_modules/roughjs'];
  assert.equal(rough.version, '4.6.6');
  assert.equal(rough.integrity, 'sha512-ZUz/69+SYpFN/g/lUlo2FXcIjRkSu3nDarreVdGGndHEBJ6cXPdKguS8JGxwj5HA5xIbVKSmLgr5b3AWxtRfvQ==');
  assert.equal(rough.license, 'MIT');
  assert.deepEqual(Object.fromEntries(['hachure-fill', 'path-data-parser', 'points-on-curve', 'points-on-path']
    .map(name => [name, lock.packages[`node_modules/${name}`].version])),
  { 'hachure-fill': '0.5.2', 'path-data-parser': '0.1.0', 'points-on-curve': '0.2.0', 'points-on-path': '0.2.1' });
  assert.deepEqual(Object.keys(lock.packages).filter(path => path.endsWith('/roughjs')), ['node_modules/roughjs'], 'one copy');
  assert.equal(lock.packages['node_modules/mermaid'].dependencies.roughjs, '^4.6.6');
  assert.equal(JSON.parse(text('../node_modules/roughjs/package.json')).version, '4.6.6');
});

test('the Excalifont subsets are the unmodified v0.18.1 files', () => {
  for (const [file, expected] of Object.entries(FONTS)) {
    const bytes = read(`../src/map/fonts/${file}`);
    assert.equal(bytes.length, expected.size, file);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expected.sha256, file);
    assert.equal(names(tables(bytes).name.bytes)[0], 'Copyright (c) 2024 by Excalidraw. All rights reserved.');
    assert.equal(names(tables(bytes).name.bytes)[1], 'Excalifont');
  }
});

test('the Latin subset alone covers the en/es set, and every map label character is covered or falls back', () => {
  const latin = covered[LATIN];
  assert.equal(latin.size, 212);
  assert.deepEqual(REQUIRED.filter(char => !latin.has(char.codePointAt(0))), []);
  assert.equal(REQUIRED.length, 125);
  const all = new Set([...latin, ...covered[Object.keys(FONTS)[1]]]);
  assert.equal(all.size, 352, 'the two subsets do not overlap');
  for (const catalog of [en, es]) {
    for (const [key, value] of Object.entries(catalog)) {
      if (!key.startsWith('map.')) continue;
      const missing = [...value.replace(/\{[a-z_]+\}/g, '')].filter(char => !all.has(char.codePointAt(0)));
      assert.deepEqual(missing, [], key);
    }
  }
});

test('the @font-face rules use local assets, swap, and unicode-range equal to each subset cmap', () => {
  const css = text('../src/styles.css');
  const faces = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map(match => match[1]);
  assert.equal(faces.length, 2);
  for (const face of faces) {
    const file = face.match(/url\("\.\/map\/fonts\/([^"]+)"\) format\("woff2"\)/)?.[1];
    assert.ok(file in FONTS, file);
    assert.match(face, /font-family: "Excalifont";/);
    assert.match(face, /font-display: swap;/);
    const range = face.match(/unicode-range:\s*([^;]+);/)[1].replace(/\s+/g, ' ').trim();
    assert.equal(range, ranges(covered[file]), file);
  }
  assert.doesNotMatch(css, /https?:\/\/|\/\/fonts\.|@import/, 'no CDN, remote font or imported stylesheet');
});

test('Excalifont is limited to map labels and other characters fall back to the interface font', () => {
  const css = text('../src/styles.css');
  const outsideFaces = css.replace(/@font-face\s*\{[^}]*\}/g, '');
  const rules = [...outsideFaces.matchAll(/([^{}]+)\{([^}]*)\}/g)].map(([, selector, body]) => ({ selector: selector.trim().split('\n').at(-1).trim(), body }));
  const family = rules.filter(rule => rule.body.includes('Excalifont'));
  assert.deepEqual(family.map(rule => rule.selector), ['.map'], 'only the map scope names the font');
  assert.match(family[0].body, /--font-map: "Excalifont", var\(--font-ui\);/, 'fallback to the interface font');
  assert.deepEqual(rules.filter(rule => rule.body.includes('var(--font-map)')).map(rule => rule.selector), ['.map-label']);
  const view = text('../src/map/MapView.tsx');
  assert.ok([...view.matchAll(/<text className="([^"]+)"/g)].every(match => match[1].startsWith('map-label')), 'every SVG text is a map label');
  assert.doesNotMatch(view, /className="map-label"[^>]*>\s*<\/?(button|span|p)/);
});

test('the OFL 1.1 licence, copyright and attribution ship beside the fonts and in the third-party notice', () => {
  const licence = text('../src/map/fonts/OFL-1.1.txt');
  for (const fragment of ['Copyright (c) 2024 by Excalidraw. All rights reserved.', 'tag v0.18.1', 'shipped unmodified',
    'Attribution: Excalifont by Excalidraw', 'SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007', 'PERMISSION & CONDITIONS',
    // Credits preserved upstream in the font's index.ts at the same tag (the subsets' name tables keep only the copyright).
    'Designers: Your Own Font Foundry (Virgil); Ján Filípek / DizajnDesign (Excalifont, modifications).',
    'Trademark: Excalifont is a trademark of Excalidraw.', '"Origin File Name Table" in packages/excalidraw/fonts/Excalifont/index.ts',
    ...Object.keys(FONTS)]) assert.ok(licence.includes(fragment), fragment);
  assert.doesNotMatch(licence, /[ \t]$/m);
  const notice = text('../../NOTICE-THIRD-PARTY.md');
  const fonts = notice.slice(notice.indexOf('\n## Fonts\n'), notice.indexOf('\n## Notice ', notice.indexOf('\n## Fonts\n')));
  assert.ok(fonts.includes(licence.trimEnd()), 'the notice carries the same licence text');
  for (const [file, { sha256 }] of Object.entries(FONTS)) assert.ok(fonts.includes(file) && fonts.includes(sha256), file);
  assert.ok(fonts.includes('assets/Excalifont-OFL-1.1.txt'));
  const vite = text('../vite.config.ts');
  assert.match(vite, /fileName: "assets\/Excalifont-OFL-1\.1\.txt"/);
  assert.match(vite, /src\/map\/fonts\/OFL-1\.1\.txt/);
  assert.match(vite, /name: "harness-map-fixture",\s*apply: "serve"/, 'the synthetic fixture is never built');
});

// WCAG relative luminance contrast.
function contrast(a, b) {
  const lum = hex => {
    const [r, g, bl] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

test('status label colours, including the new orange and violet pairs, reach 4.5:1 in light and dark themes', () => {
  const css = text('../src/styles.css');
  const tokens = block => Object.fromEntries([...block.matchAll(/--([a-z-]+):\s*(#[0-9a-f]{6})/g)].map(([, name, value]) => [name, value]));
  const light = tokens(css.slice(css.indexOf(':root {'), css.indexOf('@media (prefers-color-scheme: dark)')));
  const darkMedia = tokens(css.slice(css.indexOf(':root:not([data-theme="light"])'), css.indexOf(':root[data-theme="dark"]')));
  const darkChoice = tokens(css.slice(css.indexOf(':root[data-theme="dark"]'), css.indexOf('* { box-sizing')));
  for (const name of ['progress', 'progress-soft', 'waiting', 'waiting-soft']) {
    assert.ok(light[name] && darkMedia[name], name);
    assert.equal(darkChoice[name], darkMedia[name], `${name}: both dark declarations agree`);
  }
  // Text drawn on the card surface: status text and code per class, titles in ink; the bubble count on its fill.
  const classes = { done: 'ok', progress: 'progress', waiting: 'waiting', failed: 'danger', pending: 'neutral', inactive: 'muted', unknown: 'neutral' };
  const mapCss = css.slice(css.indexOf('/* Work map (P002-T021)'));
  for (const [cls, token] of Object.entries(classes)) assert.match(mapCss, new RegExp(`\\.map-status-${cls} \\{ color: var\\(--${token}\\); \\}`), cls);
  for (const [theme, values] of [['light', light], ['dark', { ...light, ...darkMedia }]]) {
    for (const token of [...new Set(Object.values(classes)), 'ink']) {
      assert.ok(contrast(values[token], values.surface) >= 4.5, `${theme} ${token} ${contrast(values[token], values.surface).toFixed(2)}`);
    }
    assert.ok(contrast(values.waiting, values['waiting-soft']) >= 4.5, `${theme} bubble count`);
  }
});
