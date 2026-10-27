// Line-based unified diff, without dependencies (H6.2 E4). Display only: the authority is still the hash
// the server confirms, never this diff. Above the limit it returns null instead of approximating.

const CONTEXT = 3;
const MAX_CELLS = 4_000_000;

type Op = { kind: " " | "-" | "+"; line: string };

function lines(text: string): string[] {
  if (!text) return [];
  const parts = text.split("\n");
  if (parts[parts.length - 1] === "") parts.pop();
  return parts;
}

/** Minimal edit operations (LCS) between two lists of lines; null if the table exceeds the limit. */
function operations(a: string[], b: string[]): Op[] | null {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let end = 0;
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
  const x = a.slice(start, a.length - end), y = b.slice(start, b.length - end);
  if ((x.length + 1) * (y.length + 1) > MAX_CELLS) return null;
  const width = y.length + 1;
  const table = new Uint32Array((x.length + 1) * width);
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      table[i * width + j] = x[i] === y[j] ? table[(i + 1) * width + j + 1] + 1
        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const middle: Op[] = [];
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { middle.push({ kind: " ", line: x[i] }); i++; j++; }
    else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) middle.push({ kind: "-", line: x[i++] });
    else middle.push({ kind: "+", line: y[j++] });
  }
  while (i < x.length) middle.push({ kind: "-", line: x[i++] });
  while (j < y.length) middle.push({ kind: "+", line: y[j++] });
  return [...a.slice(0, start).map(line => ({ kind: " " as const, line })), ...middle,
    ...a.slice(a.length - end).map(line => ({ kind: " " as const, line }))];
}

/**
 * Unified diff from `before` to `after` with three lines of context. A null `before` is a new file and a null
 * `after` a deleted one. Returns "" if nothing changed and null if the document is too large to compare here.
 * `eolNote` is the text of the line that marks a changed final newline, in the visual language.
 */
export function unifiedDiff(path: string, before: string | null, after: string | null, eolNote: string): string | null {
  if (before === after) return "";
  const ops = operations(lines(before ?? ""), lines(after ?? ""));
  if (!ops) return null;
  const out = [`--- ${before === null ? "/dev/null" : `a/${path}`}`, `+++ ${after === null ? "/dev/null" : `b/${path}`}`];
  // Different end of file (with or without a final newline): marked as Git does.
  const eol = !!before && !!after && before.endsWith("\n") !== after.endsWith("\n");
  const changed = ops.map((op, index) => op.kind !== " " ? index : -1).filter(index => index >= 0);
  if (eol && changed[changed.length - 1] !== ops.length - 1) changed.push(ops.length - 1);
  let index = 0;
  while (index < changed.length) {
    const first = Math.max(0, changed[index] - CONTEXT);
    let last = Math.min(ops.length - 1, changed[index] + CONTEXT);
    while (index + 1 < changed.length && changed[index + 1] - CONTEXT <= last + 1) {
      index++;
      last = Math.min(ops.length - 1, changed[index] + CONTEXT);
    }
    index++;
    let oldStart = 1, newStart = 1;
    for (const op of ops.slice(0, first)) { if (op.kind !== "+") oldStart++; if (op.kind !== "-") newStart++; }
    const hunk = ops.slice(first, last + 1);
    const oldCount = hunk.filter(op => op.kind !== "+").length, newCount = hunk.filter(op => op.kind !== "-").length;
    out.push(`@@ -${oldCount ? oldStart : oldStart - 1},${oldCount} +${newCount ? newStart : newStart - 1},${newCount} @@`);
    for (const op of hunk) out.push(op.kind + op.line);
    if (eol && last === ops.length - 1) out.push(`\\ ${eolNote}`);
  }
  return out.join("\n") + "\n";
}

// --- reviewed diff of a cycle, read in pages (D085) ---------------------------------------------

export type DiffPage = { sha256: string; size_bytes: number; offset: number; next_offset: number | null; text: string };
// `pages` keeps each page as it arrived, to paint them separately without repainting the previous ones.
export type LoadedDiff = { sha256: string; size: number; text: string; pages: string[]; loaded: number; next: number | null };

/**
 * Appends the next page to what is already loaded. Returns null if it does not fit (another hash or size, a cursor
 * other than expected or bytes that fall short of `next_offset`): what is loaded is not mixed with another diff
 * and is reread from 0.
 */
export function appendDiffPage(loaded: LoadedDiff | undefined, page: DiffPage): LoadedDiff | null {
  if (page.offset !== (loaded ? loaded.next : 0)) return null;
  if (loaded && (loaded.sha256 !== page.sha256 || loaded.size !== page.size_bytes)) return null;
  const end = page.offset + new TextEncoder().encode(page.text).length;
  if (end !== (page.next_offset ?? page.size_bytes)) return null;
  return { sha256: page.sha256, size: page.size_bytes, text: (loaded?.text ?? "") + page.text,
    pages: [...(loaded?.pages ?? []), page.text], loaded: end, next: page.next_offset };
}

/** Human-readable size in binary units, like the server limits (64 KiB, 4 MiB). */
export function byteSize(value: number, language: string): string {
  if (value < 1024) return `${value.toLocaleString(language)} B`;
  const [amount, unit] = value < 1024 * 1024 ? [value / 1024, "KiB"] : [value / (1024 * 1024), "MiB"];
  return `${amount.toLocaleString(language, { maximumFractionDigits: 1 })} ${unit}`;
}
