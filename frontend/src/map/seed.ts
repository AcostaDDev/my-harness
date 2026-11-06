// Stable rough.js seeds (T018 §10, D297): every shape is drawn with a seed derived from the stable identity of what
// it represents, never from its position in a list, so lines do not jitter between refreshes, reorders or camera moves.

const MAX_SEED = 2 ** 31 - 1;

/** Deterministic seed in [1, 2^31 - 1] for an identity (FNV-1a over UTF-16 code units). rough.js treats 0 as random. */
export function seedOf(identity: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < identity.length; i++) {
    hash ^= identity.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return ((hash >>> 0) % MAX_SEED) + 1;
}
