// Width of map card labels without a DOM (P002-T022): server renders, tests and the first browser frame lay out the
// same lines. Advance widths are per 100 px of font size: for each printable ASCII character (and its accented
// variants), the largest of Excalifont v0.18.1 and the interface fallback font at the label sizes 12–16 px, measured in
// the built-in Chromium on macOS. A line that fits before the map font loads (font-display: swap) therefore also fits
// after. Other characters use their unaccented base letter, else a full em.
const ASCII = [
  40, 32, 48, 79, 73, 93, 72, 30, 45, 41, 53, 63, 30, 48, 30, 57, 67, 47, 70, 63, 65, 62, 64, 57, 64, 64, 30, 30, 63, 63,
  63, 52, 92, 68, 77, 72, 78, 71, 67, 78, 75, 55, 57, 66, 57, 88, 75, 78, 70, 78, 74, 64, 86, 74, 68, 97, 68, 66, 84, 48,
  59, 50, 63, 67, 60, 58, 62, 56, 62, 58, 50, 61, 59, 25, 33, 55, 26, 88, 59, 60, 62, 61, 42, 55, 56, 59, 55, 78, 60, 55,
  58, 51, 30, 55, 67,
];
const ELLIPSIS = 81;
const EM = 100;
// Pairs with positive kerning draw slightly wider than the sum of their advances (at most 0.6 px over 2 % in 100,000
// random strings at 12–16 px in both fonts); 2 % plus 1 px covers them.
const KERNING = 1.02, SLACK = 1;

function advance(ch: string): number {
  const code = ch.codePointAt(0)!;
  if (code >= 32 && code < 127) return ASCII[code - 32];
  if (ch === "…") return ELLIPSIS;
  const base = ch.normalize("NFD").codePointAt(0)!;
  return base >= 32 && base < 127 ? ASCII[base - 32] : EM;
}

/** Estimated drawn width, in px, of `text` at `size` px (an upper bound for both fonts the map may use). */
export function textWidth(text: string, size: number): number {
  let units = 0;
  for (const ch of text) units += advance(ch);
  return text ? (units * size * KERNING) / 100 + SLACK : 0;
}

export type LineBudget = { limit: number; advance: (character: string) => number };

/** Additive width budget in the same units as the glyph advances. */
export function fitsWithin(size: number, width: number): LineBudget {
  return { limit: (width - SLACK) * 100 / (size * KERNING), advance };
}
