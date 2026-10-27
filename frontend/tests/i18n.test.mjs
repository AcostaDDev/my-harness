import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FIELD, LANGUAGES, LocalizedError, isLanguage, plural, segments, translate } from '../src/i18n.ts';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

const fields = text => [...text.matchAll(FIELD)].map(match => match[1]).sort();

test('both catalogs cover the same keys, parameters and plural variants', () => {
  assert.deepEqual(Object.keys(es).sort(), Object.keys(en).sort());
  for (const [key, text] of Object.entries(en)) {
    assert.ok(text.trim() && es[key].trim(), key);
    assert.deepEqual(fields(es[key]), fields(text), key);
    // Plain text with named fields only: no markup and no expressions to evaluate.
    assert.doesNotMatch(text + es[key], /[<>]|\{(?![a-z_][a-z0-9_]*\})/, key);
    if (key.endsWith('.one')) assert.ok(`${key.slice(0, -4)}.other` in en, key);
  }
});

test('interpolation replaces named fields as text and keeps absent ones visible', () => {
  const catalogs = { en: { greet: 'Hi {name}, {count} runs' }, es: { greet: 'Hola {name}, {count} runs' } };
  assert.equal(translate(catalogs, 'es', 'greet', { name: '<b>{count}</b>', count: 1234 }), 'Hola <b>{count}</b>, 1234 runs');
  assert.equal(translate(catalogs, 'en', 'greet', { count: 1234 }), 'Hi {name}, 1,234 runs');
  assert.equal(translate(catalogs, 'en', 'greet', { constructor: 'x', count: 1 }), 'Hi {name}, 1 runs');
});

test('missing translations fall back to English and missing keys stay visible', () => {
  const catalogs = { en: { only: 'Only English', both: 'Both' }, es: { both: 'Ambos' } };
  assert.equal(translate(catalogs, 'es', 'only'), 'Only English');
  assert.equal(translate(catalogs, 'es', 'both'), 'Ambos');
  assert.equal(translate(catalogs, 'es', 'nowhere.key'), 'nowhere.key');
});

test('plural variants follow Intl.PluralRules for each language', () => {
  const catalogs = { en: { 'runs.one': '{count} run', 'runs.other': '{count} runs' },
    es: { 'runs.one': '{count} ejecución', 'runs.other': '{count} ejecuciones' } };
  assert.deepEqual([0, 1, 2].map(n => plural(catalogs, 'en', 'runs', n)), ['0 runs', '1 run', '2 runs']);
  assert.deepEqual([0, 1, 1000].map(n => plural(catalogs, 'es', 'runs', n)), ['0 ejecuciones', '1 ejecución', '1000 ejecuciones']);
});

test('only en and es are languages; anything else is rejected rather than normalized', () => {
  assert.deepEqual(LANGUAGES, ['en', 'es']);
  for (const value of ['en', 'es']) assert.ok(isLanguage(value));
  for (const value of ['EN', 'es-ES', 'fr', '', null, undefined, 1]) assert.ok(!isLanguage(value), String(value));
});

test('segments split a message at its fields so elements are placed as values, never parsed as markup', () => {
  assert.deepEqual(segments('Task {task} of phase {phase}.'),
    [{ text: 'Task ' }, { field: 'task' }, { text: ' of phase ' }, { field: 'phase' }, { text: '.' }]);
  assert.deepEqual(segments('{a}{b}'), [{ field: 'a' }, { field: 'b' }]);
  assert.deepEqual(segments('No fields <b>here</b>'), [{ text: 'No fields <b>here</b>' }]);
});

test('own errors outside React carry a catalog key, translated when shown', () => {
  const error = new LocalizedError('error.request_status', { status: 503 });
  assert.ok(error instanceof Error);
  assert.equal(error.key, 'error.request_status');
  assert.equal(translate({ en, es }, 'es', error.key, error.params), 'La solicitud falló (503). Comprueba que el servicio esté disponible.');
  assert.equal(translate({ en, es }, 'en', error.key, error.params), 'The request failed (503). Check that the service is available.');
});

test('a command duration is a localized number, not the raw float', () => {
  const seconds = 0.03816141700008302;
  assert.equal(translate({ en, es }, 'en', 'tests.seconds', { seconds }), '0.038 s');
  assert.equal(translate({ en, es }, 'es', 'tests.seconds', { seconds }), '0,038 s');
});

test('every attempt outcome stored by the adapters has its own label in both languages', () => {
  // Stream statuses upper-cased by the queue when the attempt is stored (TIMED_OUT shares the TIMEOUT label).
  for (const status of ['COMPLETE', 'PARTIAL', 'INVALID', 'CANCELLED', 'TIMEOUT', 'FAILED', 'INTERRUPTED', 'COMPLETED']) {
    const key = `status.run.${status}`;
    assert.ok(en[key] && es[key] && en[key] !== es[key], key);
  }
});

test('the Spanish catalog keeps protocol literals untranslated', () => {
  // Chat command names and technical markers are protocol, identical in both catalogs.
  assert.match(en['chat_command.no_phase.body'], /\/abrir-fase/);
  assert.match(es['chat_command.no_phase.body'], /\/abrir-fase/);
  for (const key of ['status.run.QUEUED', 'nav.docs', 'stats.api_equivalent']) assert.notEqual(en[key], es[key], key);
});
