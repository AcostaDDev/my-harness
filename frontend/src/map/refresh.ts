// Activity polling of the work map (T018 §8, D306, D029; P002-T022). One aggregated `map/activity` read for every
// scope in view, every 2 s while anything is active and every 10 s when idle (the intervals the response states),
// paused while the tab is hidden and never started in archives (or once a response says polling is disabled).
// Reads never overlap: the next one is scheduled only after the previous one settled. A result read for another set
// of scopes than the current one is ignored, and `stop` clears the timer and the visibility listener.
import type { MapActivity } from "./api.ts";

export type PollerDeps = {
  fetchActivity(scopes: readonly string[]): Promise<MapActivity>;
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  /** Whether the page is hidden now (`document.hidden`). */
  hidden(): boolean;
  /** Subscribes to visibility changes; returns the unsubscribe function. */
  onVisibility(listener: () => void): () => void;
};

/** Until the first response states them (T020 `polling`), the contract's intervals apply. */
export const ACTIVE_MS = 2000;
export const IDLE_MS = 10000;

export type PollResult = { activity: MapActivity; scopes: readonly string[] };

export class ActivityPoller {
  private scopes: string[] = [];
  private key = "";
  private timer: unknown;
  private inflight = false;
  private stopped = true;
  private paused = false;
  private unsubscribe?: () => void;
  private delay = ACTIVE_MS;
  private pauseWhenHidden = true;
  /** Reads issued, for tests and diagnostics. */
  reads = 0;

  constructor(private deps: PollerDeps, private result: (result: PollResult) => void, private failed: (error: unknown) => void = () => {}) {}

  /** The scopes in view; a different set takes effect from the next read. An empty set reads nothing. */
  setScopes(scopes: readonly string[]) {
    const next = [...new Set(scopes.filter(Boolean))].sort();
    const key = next.join("\n");
    if (key === this.key) return;
    this.scopes = next;
    this.key = key;
    if (!this.stopped && !this.inflight && !this.paused) this.schedule(this.delay);
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.unsubscribe = this.deps.onVisibility(() => this.visibility());
    if (this.pauseWhenHidden && this.deps.hidden()) { this.paused = true; return; }
    this.schedule(this.delay);
  }

  stop() {
    this.stopped = true;
    this.clear();
    this.unsubscribe?.();
    this.unsubscribe = undefined;
  }

  get running(): boolean { return !this.stopped; }
  get isPaused(): boolean { return this.paused; }
  get nextDelay(): number { return this.delay; }

  private clear() {
    if (this.timer !== undefined) this.deps.clearTimeout(this.timer);
    this.timer = undefined;
  }

  private schedule(ms: number) {
    this.clear();
    if (this.stopped) return;
    this.timer = this.deps.setTimeout(() => { this.timer = undefined; void this.tick(); }, ms);
  }

  private visibility() {
    if (this.stopped) return;
    if (this.pauseWhenHidden && this.deps.hidden()) { this.paused = true; this.clear(); return; }
    if (this.paused) { this.paused = false; if (!this.inflight) void this.tick(); }
  }

  private async tick() {
    if (this.stopped || this.inflight) return;
    if (this.pauseWhenHidden && this.deps.hidden()) { this.paused = true; return; }
    if (!this.scopes.length) { this.schedule(this.delay); return; }
    const key = this.key, scopes = this.scopes;
    this.inflight = true;
    this.reads++;
    try {
      const activity = await this.deps.fetchActivity(scopes);
      if (this.stopped) return;
      const polling = activity.polling;
      this.pauseWhenHidden = polling?.pause_when_hidden !== false;
      this.delay = activity.active ? polling?.active_interval_ms ?? ACTIVE_MS : polling?.idle_interval_ms ?? IDLE_MS;
      if (polling && !polling.enabled) { this.stop(); return; }
      if (key === this.key) this.result({ activity, scopes });
    } catch (error) {
      if (this.stopped) return;
      this.delay = IDLE_MS;
      this.failed(error);
    } finally {
      this.inflight = false;
    }
    if (this.stopped) return;
    if (this.pauseWhenHidden && this.deps.hidden()) { this.paused = true; return; }
    this.schedule(this.delay);
  }
}

/** Scopes whose current version differs from the one shown, or that no longer exist (`not_found`). */
export function changedScopes(activity: MapActivity, shown: Readonly<Record<string, string | undefined>>): string[] {
  return activity.scopes.filter(item => Object.hasOwn(shown, item.scope) && (item.error === "not_found" || item.version !== shown[item.scope]))
    .map(item => item.scope);
}
