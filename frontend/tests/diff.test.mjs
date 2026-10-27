import { test } from 'node:test';
import assert from 'node:assert/strict';
import { appendDiffPage, byteSize, unifiedDiff } from '../src/diff.ts';

const NOTE = 'Cambia el salto de línea final';

/** Applies a unified diff to `before`; proves that the diff describes exactly the change. */
function apply(before, diff) {
  const source = before ? before.split('\n') : [];
  if (source[source.length - 1] === '') source.pop();
  const out = [];
  let cursor = 0;
  for (const line of diff.split('\n').slice(2)) {
    const hunk = /^@@ -(\d+),(\d+) \+\d+,\d+ @@$/.exec(line);
    if (hunk) {
      const start = Number(hunk[2]) ? Number(hunk[1]) - 1 : Number(hunk[1]);
      while (cursor < start) out.push(source[cursor++]);
    } else if (line.startsWith(' ')) { assert.equal(source[cursor], line.slice(1)); out.push(source[cursor++]); }
    else if (line.startsWith('-')) { assert.equal(source[cursor], line.slice(1)); cursor++; }
    else if (line.startsWith('+')) out.push(line.slice(1));
  }
  while (cursor < source.length) out.push(source[cursor++]);
  return out;
}

const lines = text => { const parts = text.split('\n'); if (parts[parts.length - 1] === '') parts.pop(); return parts; };

test('identical texts have no diff; new and deleted files are explicit', () => {
  assert.equal(unifiedDiff('a.md', 'x\n', 'x\n', NOTE), '');
  assert.equal(unifiedDiff('a.md', null, '# A\nb\n', NOTE), '--- /dev/null\n+++ b/a.md\n@@ -0,0 +1,2 @@\n+# A\n+b\n');
  assert.equal(unifiedDiff('a.md', '# A\n', null, NOTE), '--- a/a.md\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-# A\n');
});

test('hunks keep three lines of context and merge when close', () => {
  const before = Array.from({ length: 30 }, (_, i) => `línea ${i + 1}`).join('\n') + '\n';
  const after = before.replace('línea 5\n', 'cinco\n').replace('línea 9\n', 'nueve\n').replace('línea 25\n', '');
  const diff = unifiedDiff('docs/STATE.md', before, after, NOTE);
  const hunks = diff.split('\n').filter(l => l.startsWith('@@'));
  assert.deepEqual(hunks, ['@@ -2,11 +2,11 @@', '@@ -22,7 +22,6 @@']);
  assert.deepEqual(apply(before, diff), lines(after));
});

test('a change of the final newline is shown, never hidden', () => {
  const diff = unifiedDiff('a.md', 'a\nb\n', 'a\nb', NOTE);
  assert.match(diff, /\\ Cambia el salto de línea final/);
  assert.match(unifiedDiff('a.md', 'x\na\nb\n', 'y\na\nb', NOTE), /^-x$[\s\S]*Cambia el salto/m);
});

test('random edits round-trip through the diff', () => {
  let seed = 7;
  const random = n => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  for (let round = 0; round < 200; round++) {
    const base = Array.from({ length: random(25) }, () => `l${random(6)}`);
    const edited = [...base];
    for (let k = random(6); k > 0; k--) {
      const at = random(edited.length + 1);
      if (random(2) && edited.length) edited.splice(Math.min(at, edited.length - 1), 1);
      else edited.splice(at, 0, `n${random(4)}`);
    }
    const before = base.length ? base.join('\n') + '\n' : '', after = edited.length ? edited.join('\n') + '\n' : '';
    const diff = unifiedDiff('x.md', before, after, NOTE);
    if (before === after) { assert.equal(diff, ''); continue; }
    assert.deepEqual(apply(before, diff), lines(after), JSON.stringify({ base, edited }));
  }
});

test('documents too large to compare return null instead of an approximation', () => {
  const before = Array.from({ length: 2500 }, (_, i) => `a${i}`).join('\n');
  const after = Array.from({ length: 2500 }, (_, i) => `b${i}`).join('\n');
  assert.equal(unifiedDiff('big.md', before, after, NOTE), null);
});

// --- paginated cycle diff (D085) ---

const SHA = 'a'.repeat(64);
const bytes = text => new TextEncoder().encode(text).length;
function serve(text, limit) {
  const pages = [];
  let offset = 0;
  const data = new TextEncoder().encode(text);
  while (true) {
    let end = Math.min(offset + limit, data.length);
    const newline = data.subarray(offset, end).lastIndexOf(10);
    if (end < data.length && newline >= 0) end = offset + newline + 1;
    while (end < data.length && (data[end] & 0xc0) === 0x80) end++;
    pages.push({ sha256: SHA, size_bytes: data.length, offset, next_offset: end < data.length ? end : null,
      text: new TextDecoder().decode(data.subarray(offset, end)) });
    if (end >= data.length) return pages;
    offset = end;
  }
}

test('cycle diff pages accumulate in order to the exact text', () => {
  const text = Array.from({ length: 300 }, (_, i) => `+línea ${i} ñ €`).join('\n') + '\n';
  for (const limit of [5, 64, 4096]) {
    let loaded;
    for (const page of serve(text, limit)) loaded = appendDiffPage(loaded, page);
    assert.equal(loaded.text, text);
    assert.equal(loaded.pages.join(''), text);
    assert.equal(loaded.loaded, bytes(text));
    assert.equal(loaded.next, null);
  }
});

test('a page that does not continue the loaded diff is refused, never mixed', () => {
  const [first, second] = serve('+a\n+b\n+c\n', 3);
  const loaded = appendDiffPage(undefined, first);
  assert.equal(appendDiffPage(undefined, second), null); // starts at 0
  assert.equal(appendDiffPage(loaded, first), null); // repeated
  assert.equal(appendDiffPage(loaded, { ...second, sha256: 'b'.repeat(64) }), null);
  assert.equal(appendDiffPage(loaded, { ...second, size_bytes: 99 }), null);
  assert.equal(appendDiffPage(loaded, { ...second, text: '+b' }), null); // bytes that do not reach the cursor
  assert.equal(appendDiffPage(loaded, second).text, '+a\n+b\n');
});

test('an empty diff is a single complete page', () => {
  assert.deepEqual(appendDiffPage(undefined, { sha256: SHA, size_bytes: 0, offset: 0, next_offset: null, text: '' }),
    { sha256: SHA, size: 0, text: '', pages: [''], loaded: 0, next: null });
});

test('byte sizes use binary units', () => {
  assert.equal(byteSize(512, 'es'), '512 B');
  assert.equal(byteSize(64 * 1024, 'es'), '64 KiB');
  assert.equal(byteSize(4 * 1024 * 1024, 'es'), '4 MiB');
  assert.equal(byteSize(1536, 'es'), '1,5 KiB');
  assert.equal(byteSize(1536, 'en'), '1.5 KiB');
});
