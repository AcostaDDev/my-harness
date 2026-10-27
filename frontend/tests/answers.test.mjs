import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MESSAGE_LIMIT, characters, compose, draftsKey, entries, mark, marked, markSent, orphans, prune, readDrafts,
  resolved, sourceTurn, standings, writeDrafts } from '../src/answers.ts';

// Synthetic question ids: 64 hex characters, distinct in their first 12 (the marker).
const id = n => String(n).repeat(12).slice(0, 12) + 'f'.repeat(52);
const q1 = { id: id(1), text: 'Which database?', blocking: true, deferred: null };
const q2 = { id: id(2), text: 'Which deploy target?', blocking: false, deferred: null };
const q3 = { id: id(3), text: 'License?', blocking: true, deferred: null };
const answered = (number, questions, message = 'brief') => ({ number, status: 'ANSWERED', message, result: { result: { questions } } });
const labels = { intro: 'Answers from turn 2:', blocking: 'Blocking question', informative: 'Informative question',
  earlier: 'Earlier question', answer: 'Answer', context: 'Additional context' };
const draft = (text, extra = {}) => ({ text, question: 'q', blocking: true, turn: 2, selected: false, ...extra });

function memory() {
  const data = new Map();
  return { data, getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
}

test('drafts are isolated by project and conversation and survive a reload; invalid entries are dropped', () => {
  const store = memory();
  const key = draftsKey('demo', 'conv-a');
  assert.notEqual(key, draftsKey('demo', 'conv-b'));
  assert.notEqual(key, draftsKey('other', 'conv-a'));
  writeDrafts(store, key, { [q1.id]: draft('PostgreSQL') });
  assert.deepEqual(readDrafts(store, key), { [q1.id]: draft('PostgreSQL') });
  store.setItem(key, JSON.stringify({ [q1.id]: draft('ok'), short: draft('bad id'), [q2.id]: { text: 1 } }));
  assert.deepEqual(Object.keys(readDrafts(store, key)), [q1.id]);
  store.setItem(key, '{broken');
  assert.deepEqual(readDrafts(store, key), {});
  writeDrafts(store, key, {});
  assert.equal(store.getItem(key), null);
  // Without storage (private mode) nothing throws.
  assert.deepEqual(readDrafts(undefined, key), {});
  writeDrafts({ setItem() { throw new Error('quota'); }, removeItem() {}, getItem() { return null; } }, key, { [q1.id]: draft('x') });
});

test('a composed message keeps each question, its kind, its marker and its answer, then the optional context', () => {
  const items = entries([q2.id, q1.id], { [q1.id]: draft(' PostgreSQL 16 '), [q2.id]: draft('Fly.io', { blocking: false }) }, [q1, q2], new Set());
  assert.deepEqual(items.map(item => item.id), [q1.id, q2.id], 'shown order, not click order');
  const text = compose(items, '  Budget is small. ', labels);
  assert.equal(text, [
    'Answers from turn 2:',
    `1. [q:${id(1).slice(0, 12)}] Blocking question: Which database?\nAnswer:\nPostgreSQL 16`,
    `2. [q:${id(2).slice(0, 12)}] Informative question: Which deploy target?\nAnswer:\nFly.io`,
    'Additional context:\nBudget is small.',
  ].join('\n\n'));
  assert.deepEqual([...marked(text)], [id(1).slice(0, 12), id(2).slice(0, 12)]);
  assert.ok(!compose(items, '   ', labels).includes('Additional context'));
});

test('only chosen answers with text that are not already waiting go into a submission', () => {
  const drafts = { [q1.id]: draft('A'), [q2.id]: draft('   '), [q3.id]: draft('C') };
  assert.deepEqual(entries([q1.id, q2.id, q3.id], drafts, [q1, q2, q3], new Set([q3.id])).map(e => e.id), [q1.id]);
  assert.deepEqual(entries([q2.id], drafts, [q1, q2, q3], new Set()), [], 'empty answers are never sent nor taken as deferrals');
  // An answer to a question no longer asked is labelled as earlier and keeps its own question text.
  const old = { ...drafts, [id(4)]: draft('Old answer', { question: 'Old question?' }) };
  const [earlier] = entries([id(4)], old, [q1], new Set());
  assert.deepEqual(earlier, { id: id(4), question: 'Old question?', blocking: true, earlier: true, answer: 'Old answer' });
  assert.match(compose([earlier], '', labels), /Earlier question: Old question\?/);
});

test('the aggregate limit counts characters as the service does', () => {
  assert.equal(MESSAGE_LIMIT, 20000);
  assert.equal(characters('ñ😀'), 2);
  assert.equal('😀'.length, 2, 'UTF-16 length would overcount');
  const big = { [q1.id]: draft('x'.repeat(12000)), [q2.id]: draft('y'.repeat(9000)) };
  const one = compose(entries([q1.id], big, [q1, q2], new Set()), '', labels);
  const both = compose(entries([q1.id, q2.id], big, [q1, q2], new Set()), '', labels);
  assert.ok(characters(one) <= MESSAGE_LIMIT);
  assert.ok(characters(both) > MESSAGE_LIMIT, 'the batch is refused as a whole, never cut or split');
});

test('the source turn is the latest answered one; standings follow the turns that carried each marker', () => {
  const turns = [answered(1, [q1, q2, q3]), { number: 2, status: 'FAILED', message: `${mark(q3.id)} answer` },
    answered(3, [q1, q2, q3], `${mark(q2.id)} answer`), { number: 4, status: 'QUEUED', message: `${mark(q1.id)} answer` }];
  assert.equal(sourceTurn(turns), 3);
  assert.equal(sourceTurn([{ number: 1, status: 'QUEUED', message: 'x' }]), null);
  assert.deepEqual(standings([q1, q2, q3], turns), {
    [q1.id]: { kind: 'awaiting', turn: 4 },
    [q2.id]: { kind: 'asked_again', turn: 3 },
    [q3.id]: { kind: 'unreviewed', turn: 2, status: 'FAILED' },
  });
  assert.deepEqual(standings([q1], [answered(1, [q1])]), { [q1.id]: { kind: 'open' } });
});

test('questions the reviewer stopped asking after an answered turn that carried them are resolved', () => {
  const turns = [answered(1, [q1, q2]), answered(2, [q2], `${mark(q1.id)} PostgreSQL`), { number: 3, status: 'FAILED', message: mark(q2.id) }];
  assert.deepEqual(resolved([q2], turns), [{ id: id(1).slice(0, 12), text: 'Which database?', turn: 2 }]);
  // A failed turn resolves nothing; a question still asked is not resolved.
  assert.deepEqual(resolved([q1, q2], turns), []);
});

test('pruning keeps typed text when the question set moves and drops what the reviewer resolved unchanged', () => {
  const turns = [answered(1, [q1, q2]), answered(2, [q2], `${mark(q1.id)} A`)];
  const drafts = { [q1.id]: draft('A', { sent: 'A' }), [q2.id]: draft(''), [q3.id]: draft('kept') };
  const pruned = prune(drafts, [q2], turns);
  assert.deepEqual(Object.keys(pruned), [q3.id], 'resolved and empty drafts leave; an orphan with text stays');
  // Edited after sending: the new text is kept for an explicit decision.
  assert.ok(prune({ [q1.id]: draft('A, plus more', { sent: 'A' }) }, [q2], turns)[q1.id]);
  // Nothing changes: the same object is returned (no needless writes).
  const same = { [q2.id]: draft('B') };
  assert.equal(prune(same, [q2], turns), same);
  assert.deepEqual(orphans({ [q3.id]: draft('kept'), [q1.id]: draft('  ') }, [q2]), [[q3.id, draft('kept')]]);
});

test('an accepted submission records what was sent and leaves the batch; others are untouched', () => {
  const drafts = { [q1.id]: draft('A', { selected: true }), [q2.id]: draft('B', { selected: true }) };
  const after = markSent(drafts, [q1.id]);
  assert.deepEqual(after[q1.id], draft('A', { selected: false, sent: 'A' }));
  assert.deepEqual(after[q2.id], drafts[q2.id]);
});
