// Polite live-region announcements of status changes in view (T018 §11, D309; P002-T022): one summarised message at
// most every 10 s. Changes that arrive sooner are accumulated (the latest status of each element wins) and spoken
// together when the interval has passed. Nothing is announced for the first snapshot of a level, and `dispose`
// clears the pending timer.
export const ANNOUNCE_GAP_MS = 10000;

/** Per element: its code, its status key (class and raw code, so a language switch is not a change) and its text. */
export type StatusSnapshot = ReadonlyMap<string, { code: string; status: string; label: string }>;
export type StatusChange = { id: string; code: string; status: string; label: string };

/** Elements of `next` whose status differs from `previous`, in `next`'s order; new or removed elements are not. */
export function statusChanges(previous: StatusSnapshot | undefined, next: StatusSnapshot): StatusChange[] {
  if (!previous) return [];
  const changes: StatusChange[] = [];
  for (const [id, item] of next) {
    const before = previous.get(id);
    if (before && before.status !== item.status) changes.push({ id, ...item });
  }
  return changes;
}

export type AnnouncerDeps = { now(): number; setTimeout(callback: () => void, ms: number): unknown; clearTimeout(handle: unknown): void };

export class Announcer {
  private pending = new Map<string, StatusChange>();
  private last = -Infinity;
  private timer: unknown;
  private disposed = false;

  constructor(private deps: AnnouncerDeps, private say: (changes: StatusChange[]) => void, private gap = ANNOUNCE_GAP_MS) {}

  push(changes: readonly StatusChange[]) {
    if (this.disposed || !changes.length) return;
    for (const change of changes) { this.pending.delete(change.id); this.pending.set(change.id, change); }
    const wait = this.last + this.gap - this.deps.now();
    if (wait <= 0) { this.flush(); return; }
    if (this.timer === undefined) this.timer = this.deps.setTimeout(() => { this.timer = undefined; this.flush(); }, wait);
  }

  private flush() {
    if (this.disposed || !this.pending.size) return;
    const changes = [...this.pending.values()];
    this.pending.clear();
    this.last = this.deps.now();
    this.say(changes);
  }

  dispose() {
    this.disposed = true;
    if (this.timer !== undefined) this.deps.clearTimeout(this.timer);
    this.timer = undefined;
    this.pending.clear();
  }
}
