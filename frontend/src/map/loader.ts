// Snapshot loader of one map level (P002-T022, T018 §§7–8, D306): the first page of one scope, further pages only
// on demand, reloaded when the activity poll reports a new version. Memory is bounded by a window: at most
// `maxPages` pages are held; loading past it drops the oldest ones (counted in `skipped`, the first page kept apart
// as `head`), so later data stays reachable without ever holding the whole history, and a reload returns to the
// start. At most one request of the level is in flight; a reload asked meanwhile runs once after it. A `409
// cursor_stale` while paging discards every later page and recovers from the first one. A loader belongs to one
// path: after `dispose` (the level changed) no late response is applied.
import { isMissing, isStaleCursor, pageOf } from "./api.ts";
import type { Fetcher, Paged } from "./api.ts";

export type LevelState<T> = {
  /** Pages in the window, in order; every page carries the scope and version shown. */
  pages: T[];
  /** First page of the snapshot (its head fields, such as the latest run), held even when the window moved on. */
  head?: T;
  /** Pages before the window that are no longer held (0 while the window starts at the first page). */
  skipped: number;
  loading: boolean;
  /** The last read failed; `pages` keep the previous snapshot. */
  error?: unknown;
  /** 404: the element does not exist in this project (or not any more). */
  missing: boolean;
  /** Pages were discarded after `409 cursor_stale` and the first page is being read again. */
  recovered: boolean;
};

/** Pages a level holds at once (each one is a T020 page of at most its level cap); not a limit on the history. */
export const MAX_PAGES = 5;

export class LevelLoader<T extends Paged> {
  state: LevelState<T> = { pages: [], skipped: 0, loading: true, missing: false, recovered: false };
  private generation = 0;
  private inflight = false;
  private queued = false;
  private disposed = false;

  constructor(readonly path: string, private fetcher: Fetcher, private changed: (state: LevelState<T>) => void, private maxPages = MAX_PAGES) {}

  get version(): string | undefined { return this.state.pages[0]?.version; }
  get scope(): string | undefined { return this.state.pages[0]?.scope; }
  get canLoadMore(): boolean {
    const last = this.state.pages[this.state.pages.length - 1];
    return !!last?.next_cursor;
  }

  private set(patch: Partial<LevelState<T>>) {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    this.changed(this.state);
  }

  private settle() {
    this.inflight = false;
    if (this.queued && !this.disposed) { this.queued = false; this.reload(); }
  }

  /** Reads the first page again and replaces every page with it. */
  reload() {
    if (this.disposed) return;
    if (this.inflight) { this.queued = true; return; }
    const generation = ++this.generation;
    this.inflight = true;
    this.set({ loading: true });
    this.fetcher<T>(this.path).then(page => {
      if (generation === this.generation) this.set({ pages: [page], head: page, skipped: 0, loading: false, error: undefined, missing: false, recovered: false });
    }, error => {
      if (generation !== this.generation) return;
      const missing = isMissing(error);
      this.set({ loading: false, error, missing, pages: missing ? [] : this.state.pages, ...(missing ? { head: undefined, skipped: 0 } : {}) });
    }).finally(() => this.settle());
  }

  /** Appends the next page (dropping the oldest held page past the window); a stale cursor discards the later
   * pages and recovers from the first page. */
  loadMore() {
    if (this.disposed || this.inflight || !this.canLoadMore) return;
    const cursor = this.state.pages[this.state.pages.length - 1].next_cursor;
    const generation = this.generation;
    this.inflight = true;
    this.set({ loading: true });
    this.fetcher<T>(pageOf(this.path, cursor)).then(page => {
      if (generation !== this.generation) return;
      const pages = [...this.state.pages, page];
      const dropped = Math.max(0, pages.length - this.maxPages);
      this.set({ pages: pages.slice(dropped), skipped: this.state.skipped + dropped, loading: false, error: undefined });
    }, error => {
      if (generation !== this.generation) return;
      if (isStaleCursor(error)) {
        const first = this.state.head ?? this.state.pages[0];
        this.set({ pages: first ? [first] : [], skipped: 0, recovered: true });
        this.queued = true;
        return;
      }
      this.set({ loading: false, error });
    }).finally(() => this.settle());
  }

  /** The level is no longer shown: nothing that arrives later is applied. */
  dispose() {
    this.disposed = true;
    this.generation++;
  }
}
