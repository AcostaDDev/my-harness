import { test } from 'node:test';
import assert from 'node:assert/strict';
import { axis, coverage, formats, niceStep, scale } from '../src/metrics.ts';
import { plural, translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const catalogs = { en, es };
const of = language => formats(language, (key, params) => translate(catalogs, language, key, params),
  (key, count, params) => plural(catalogs, language, key, count, params));
const { count, compact, usd, duration, percent, coverageText, rootLabel, role } = of('es');
const english = of('en');
// Intl separates the number and the unit with a no-break space; the tests compare plain text.
const plain = text => text.replace(/[\u00a0\u202f]/g, ' ');

test('null renders as «sin dato» / "no data", never zero', () => {
  for (const format of [count, compact, usd, duration]) assert.equal(format(null), 'sin dato');
  for (const format of [english.count, english.compact, english.usd, english.duration]) assert.equal(format(null), 'no data');
  assert.equal(count(0), '0');
  assert.equal(plain(usd(0)), '0,0000 US$');
  assert.equal(english.usd(0), '$0.0000');
  assert.equal(scale(null, 100, 200), null);
  assert.equal(scale(0, 100, 200), 0);
});

test('coverage of a sum by the attempts that contribute to it', () => {
  assert.equal(coverage({ sum: null, attempts: 0 }, 4), 'absent');
  assert.equal(coverage({ sum: 0, attempts: 4 }, 4), 'complete');
  assert.equal(coverage({ sum: 120, attempts: 1 }, 4), 'partial');
  assert.equal(coverageText({ sum: 120, attempts: 1 }, 4), 'de 1 de 4 intentos');
  assert.equal(coverageText({ sum: null, attempts: 0 }, 3), 'ninguno de 3 intentos lo informa');
  assert.equal(coverageText({ sum: null, attempts: 0 }, 0), 'sin intentos');
  assert.equal(coverageText({ sum: 5, attempts: 1 }, 1), 'de 1 intento');
  assert.equal(coverageText({ sum: null, attempts: 0 }, 1), 'el único intento no lo informa');
  assert.equal(english.coverageText({ sum: 120, attempts: 1 }, 4), 'from 1 of 4 attempts');
  assert.equal(english.coverageText({ sum: 5, attempts: 3 }, 3), 'from the 3 attempts');
  assert.equal(english.coverageText({ sum: null, attempts: 0 }, 3), 'none of 3 attempts reports it');
});

test('round axes from zero, with integer ticks for counts', () => {
  assert.equal(niceStep(0), 1);
  assert.equal(niceStep(719), 1000);
  assert.equal(niceStep(1.75), 2);
  assert.equal(niceStep(0.3), 0.5);
  assert.deepEqual(axis(2876), { top: 3000, ticks: [0, 1000, 2000, 3000] });
  assert.deepEqual(axis(9404), { top: 10000, ticks: [0, 5000, 10000] });
  assert.deepEqual(axis(7, 4, true), { top: 8, ticks: [0, 2, 4, 6, 8] });
  assert.deepEqual(axis(2, 4, true), { top: 2, ticks: [0, 1, 2] });
  assert.deepEqual(axis(0), { top: 1, ticks: [0, 1] });
  assert.equal(scale(2500, 5000, 200), 100);
  assert.equal(scale(-3, 5000, 200), 0);
});

test('readable formats', () => {
  assert.equal(compact(2876), count(2876));
  assert.equal(count(12345), '12.345');
  assert.match(compact(1_250_000), /1,3\s?M/);
  assert.equal(duration(950, 'ms'), '950 ms');
  assert.equal(duration(75), '1 min 15 s');
  assert.equal(duration(7260), '2 h 1 min');
  assert.equal(percent(1, 3), '33 %');
  assert.equal(percent(0, 0), 'sin dato');
  assert.equal(plain(usd(0.0125)), '0,0125 US$');
  assert.equal(english.count(12345), '12,345');
  assert.equal(english.percent(1, 3), '33%');
  assert.equal(english.usd(12.5), '$12.50');
  assert.equal(english.duration(1.5), '1.5 s');
  assert.equal(duration(1.5), '1,5 s');
});

test('root label: project id or last segment', () => {
  const projects = [{ id: 'demo', root: '/tmp/a/demo-root' }];
  assert.equal(rootLabel('/tmp/a/demo-root', projects), 'demo');
  assert.equal(rootLabel('/tmp/b/otro', projects), 'otro');
  assert.equal(rootLabel(null, projects), 'sin raíz');
  assert.equal(english.rootLabel(null, projects), 'no root');
  assert.equal(role('executor'), 'Ejecutor');
  assert.equal(english.role('executor'), 'Executor');
  assert.equal(role('future-role'), 'future-role');
});
