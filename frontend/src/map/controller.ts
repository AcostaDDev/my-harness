// Interaction of the work map without a DOM (T018 §4, §11): pointer drag and pinch, wheel, keyboard, the zoom-enter
// and zoom-out-leave thresholds and the navigation lock. The view feeds it events and applies what it reports.
import { clampPan, coverage, fit, limits, panBy, reveal, toScreen, toWorld, zoomAt } from "./camera.ts";
import type { Camera, Limits, Viewport } from "./camera.ts";
import type { Bounds, Point } from "./layout.ts";

export type ControllerNode = { id: string; rect: Bounds; enterable: boolean };
export type Direction = "left" | "right" | "up" | "down";

export type Handlers = {
  /** New camera to draw. */
  camera(camera: Camera): void;
  /** Keyboard focus moved to a node (roving tabindex). */
  focus(id: string): void;
  /** Enter a node through the router; reported at most once until `reset`. */
  enter(id: string): void;
  /** Return to the parent level; reported at most once until `reset`. */
  leave(): void;
};

/** Pointer travel, in screen pixels, after which a press becomes a drag (and its click is cancelled). */
export const DRAG_THRESHOLD = { mouse: 5, touch: 10 } as const;
/** A zoom-in over an enterable node enters it once the node covers this share of the viewport. */
export const ENTER_COVERAGE = 0.5;
/** Accumulated zoom-out (natural log of the factor) beyond the minimum scale that leaves the level. */
export const LEAVE_PRESSURE = 0.7;
/** Zoom-out pressure fades if no zoom-out arrives within this time. */
export const PRESSURE_WINDOW_MS = 600;
/** After reporting enter or leave, further navigation is ignored for this long unless the level is reset. */
export const NAVIGATION_LOCK_MS = 1500;
/** Wheel or trackpad-gesture events closer than this to the previous one belong to the same gesture. */
export const GESTURE_GAP_MS = 300;
export const KEY_PAN = 64;
export const KEY_ZOOM = 1.25;
const WHEEL_SENSITIVITY = 0.0015;
const PINCH_WHEEL_SENSITIVITY = 0.01;
const LINE_HEIGHT = 16;
const PAGE_HEIGHT = 400;

type Pointer = { x: number; y: number; startX: number; startY: number; touch: boolean };

/** Continuous inputs that can cross a navigation threshold and keep arriving after the level has changed. */
export type GestureKind = "wheel" | "gesture" | "key";

/**
 * One navigation per gesture (re-review finding): after a wheel burst, a Safari trackpad pinch or a key auto-repeat
 * has entered or left a level, the rest of that same gesture is ignored on the next level too. The guard outlives
 * `reset` and is shared by every controller of the page, so a remounted view keeps it. Wheel and pinch events carry no
 * end signal, so their gesture ends with a pause of `GESTURE_GAP_MS` or a new pinch (`gesturestart`). A held key does:
 * every auto-repeat belongs to the press that navigated, however late the first repeat arrives, and only a fresh press
 * (not an auto-repeat) ends it, so no timeout applies to keys. Any pointer press also ends a gesture. The next
 * deliberate action is never blocked.
 */
export class GestureGuard {
  private kind?: GestureKind;
  private lastAt = -Infinity;

  /** Records the gesture whose event just caused a navigation. */
  begin(kind: GestureKind, now: number) { this.kind = kind; this.lastAt = now; }

  /**
   * Whether an event of `kind` continues the gesture that navigated; such an event must be ignored. Key events reach
   * here only as auto-repeats, which continue the press without a time limit; wheel and pinch events expire.
   */
  continues(kind: GestureKind, now: number): boolean {
    if (this.kind !== kind) return false;
    if (kind !== "key" && now - this.lastAt >= GESTURE_GAP_MS) { this.kind = undefined; return false; }
    this.lastAt = now;
    return true;
  }

  end() { this.kind = undefined; }

  get active(): GestureKind | undefined { return this.kind; }
}

/** Guard of the page: every map view shares it unless a test injects its own. */
export const pageGestures = new GestureGuard();

export type WheelInput = { dx: number; dy: number; x: number; y: number; ctrl: boolean; shift: boolean; mode: 0 | 1 | 2 };
export type KeyInput = { key: string; shift: boolean; ctrl: boolean; meta: boolean; alt: boolean; repeat?: boolean };

export type ControllerOptions = {
  nodes: ControllerNode[];
  bounds: Bounds;
  viewport: Viewport;
  camera?: Camera;
  canLeave: boolean;
  handlers: Handlers;
  now?: () => number;
  guard?: GestureGuard;
};

export class MapController {
  camera: Camera;
  private nodes: ControllerNode[];
  private byId: Map<string, ControllerNode>;
  private bounds: Bounds;
  private viewport: Viewport;
  private range: Limits;
  private canLeave: boolean;
  private readonly handlers: Handlers;
  private readonly now: () => number;
  private readonly guard: GestureGuard;
  private readonly pointers = new Map<number, Pointer>();
  private moved = false;
  private suppressClick = false;
  private pinch?: { distance: number; mid: Point };
  private pressure = 0;
  private pressureAt = -Infinity;
  private lockedUntil = -Infinity;
  /** The camera is the fitted view and nobody has moved it since: a resize fits again instead of clamping. */
  private fitted = false;

  constructor(options: ControllerOptions) {
    this.handlers = options.handlers;
    this.now = options.now ?? (() => Date.now());
    this.guard = options.guard ?? pageGestures;
    this.nodes = options.nodes;
    this.byId = new Map(options.nodes.map(node => [node.id, node]));
    this.bounds = options.bounds;
    this.viewport = options.viewport;
    this.range = limits(this.bounds, this.viewport);
    this.canLeave = options.canLeave;
    this.camera = this.clamp(options.camera ?? fit(this.bounds, this.viewport));
    this.fitted = !options.camera;
  }

  /**
   * New level content (after navigation): releases the navigation lock, so a deliberate action on the new level is not
   * delayed, and drops pointers. The gesture guard is kept: the rest of a navigating gesture stays ignored.
   */
  reset(options: Omit<ControllerOptions, "handlers" | "now">) {
    this.nodes = options.nodes;
    this.byId = new Map(options.nodes.map(node => [node.id, node]));
    this.bounds = options.bounds;
    this.viewport = options.viewport;
    this.range = limits(this.bounds, this.viewport);
    this.canLeave = options.canLeave;
    this.pointers.clear();
    this.pinch = undefined;
    this.moved = this.suppressClick = false;
    this.pressure = 0;
    this.lockedUntil = -Infinity;
    if (options.camera) this.set(options.camera); else this.fit();
  }

  resize(viewport: Viewport) {
    if (viewport.width === this.viewport.width && viewport.height === this.viewport.height) return;
    this.viewport = viewport;
    this.range = limits(this.bounds, viewport);
    if (this.fitted) this.fit(); else this.set(this.camera);
  }

  get locked(): boolean { return this.now() < this.lockedUntil; }
  get limits(): Limits { return this.range; }

  fit() {
    this.set(fit(this.bounds, this.viewport));
    this.fitted = true;
  }

  set(camera: Camera) {
    this.camera = this.clamp(camera);
    this.fitted = false;
    this.handlers.camera(this.camera);
  }

  pan(dx: number, dy: number) {
    this.pressure = 0;
    this.set(panBy(this.camera, dx, dy));
  }

  /** Pan that is part of a pinch: it keeps the accumulated zoom-out pressure. */
  private follow(dx: number, dy: number) { this.set(panBy(this.camera, dx, dy)); }

  /**
   * Continuous zoom around a screen point; crossing a threshold enters a node or leaves the level. `source` names the
   * continuous input that drives it, so the rest of that gesture is ignored once it has navigated.
   */
  zoom(factor: number, at: Point, source?: GestureKind) {
    if (!(factor > 0) || factor === 1) return;
    const before = this.camera.k;
    this.set(zoomAt(this.camera, factor, at, this.range));
    if (factor > 1) {
      this.pressure = 0;
      const node = this.nodeAt(at);
      if (node?.enterable && coverage(this.camera, node.rect, this.viewport) >= ENTER_COVERAGE) this.enter(node.id, source);
      return;
    }
    if (before > this.range.min * 1.0001) return;
    const time = this.now();
    if (time - this.pressureAt > PRESSURE_WINDOW_MS) this.pressure = 0;
    this.pressureAt = time;
    this.pressure += -Math.log(factor);
    if (this.pressure >= LEAVE_PRESSURE) { this.pressure = 0; this.leave(source); }
  }

  /** Enter a node; `source` is the continuous input that triggered it, if any (a click is discrete). */
  enter(id: string, source?: GestureKind) {
    const node = this.byId.get(id);
    if (!node?.enterable || this.locked) return;
    this.navigated(source);
    this.handlers.enter(id);
  }

  leave(source?: GestureKind) {
    if (!this.canLeave || this.locked) return;
    this.navigated(source);
    this.handlers.leave();
  }

  private navigated(source?: GestureKind) {
    const now = this.now();
    this.lockedUntil = now + NAVIGATION_LOCK_MS;
    if (source) this.guard.begin(source, now); else this.guard.end();
  }

  /** Topmost node under a screen point. */
  nodeAt(point: Point): ControllerNode | undefined {
    const [x, y] = toWorld(this.camera, point);
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const { rect } = this.nodes[i];
      if (x >= rect.x && x <= rect.x + rect.width && y >= rect.y && y <= rect.y + rect.height) return this.nodes[i];
    }
    return undefined;
  }

  pointerDown(id: number, x: number, y: number, touch: boolean) {
    this.guard.end();
    if (!this.pointers.size) { this.moved = false; this.suppressClick = false; }
    this.pointers.set(id, { x, y, startX: x, startY: y, touch });
    if (this.pointers.size === 2) this.pinch = this.pinchState();
  }

  pointerMove(id: number, x: number, y: number) {
    const pointer = this.pointers.get(id);
    if (!pointer) return;
    const dx = x - pointer.x, dy = y - pointer.y;
    pointer.x = x; pointer.y = y;
    if (this.pointers.size >= 2) {
      const next = this.pinchState();
      if (this.pinch && next) {
        this.moved = true;
        this.follow(next.mid[0] - this.pinch.mid[0], next.mid[1] - this.pinch.mid[1]);
        this.zoom(next.distance / this.pinch.distance, next.mid);
      }
      this.pinch = next;
      return;
    }
    const threshold = pointer.touch ? DRAG_THRESHOLD.touch : DRAG_THRESHOLD.mouse;
    if (!this.moved && Math.hypot(x - pointer.startX, y - pointer.startY) < threshold) return;
    // The first movement past the threshold also applies the travel accumulated below it.
    const first = !this.moved;
    this.moved = true;
    this.pan(first ? x - pointer.startX : dx, first ? y - pointer.startY : dy);
  }

  pointerUp(id: number) {
    this.pointers.delete(id);
    this.pinch = this.pointers.size >= 2 ? this.pinchState() : undefined;
    if (!this.pointers.size) this.suppressClick = this.moved;
  }

  get dragging(): boolean { return this.moved && this.pointers.size > 0; }

  /**
   * Whether a click on a node may navigate: not after a drag or pinch, and not while a navigation is pending.
   * A keyboard activation (Enter on a link) is never treated as the end of a drag.
   */
  takeClick(keyboard: boolean): boolean {
    const suppressed = this.suppressClick && !keyboard;
    this.suppressClick = false;
    return !suppressed && !this.locked;
  }

  wheel(input: WheelInput) {
    if (this.guard.continues("wheel", this.now())) return;
    const scale = input.mode === 1 ? LINE_HEIGHT : input.mode === 2 ? PAGE_HEIGHT : 1;
    const dx = input.dx * scale, dy = input.dy * scale;
    if (input.shift && !input.ctrl) { this.pan(-(dx || dy), 0); return; }
    const factor = Math.exp(-dy * (input.ctrl ? PINCH_WHEEL_SENSITIVITY : WHEEL_SENSITIVITY));
    this.zoom(Math.min(2, Math.max(0.5, factor)), [input.x, input.y], "wheel");
  }

  /** Safari trackpad pinch: `gesturestart` always begins a new gesture. */
  gestureStart() { if (this.guard.active === "gesture") this.guard.end(); }

  gestureZoom(factor: number, at: Point) {
    if (this.guard.continues("gesture", this.now())) return;
    this.zoom(factor, at, "gesture");
  }

  /**
   * Keyboard (T018 §11, D312): arrows move the focus to the nearest node in that direction and the camera follows;
   * Shift+arrows pan without moving the focus; + and − zoom around the focused node; 0 fits; Home/End go to the first
   * or last node; Escape leaves. Enter is the native activation of the focused link. Returns whether it was handled.
   */
  key(input: KeyInput, focused?: string): boolean {
    // Auto-repeat of the key that navigated (Enter, Escape, + or −) is swallowed; a fresh press is deliberate.
    if (input.repeat && this.guard.continues("key", this.now())) return true;
    if (!input.repeat) this.guard.end();
    if (input.ctrl || input.meta || input.alt) return false;
    const direction = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as const)[input.key as "ArrowLeft"];
    if (direction && input.shift) {
      const [dx, dy] = { left: [KEY_PAN, 0], right: [-KEY_PAN, 0], up: [0, KEY_PAN], down: [0, -KEY_PAN] }[direction];
      this.pan(dx, dy);
      return true;
    }
    if (direction) {
      const next = focused && this.byId.has(focused) ? neighbour(this.nodes, focused, direction) : this.reading()[0]?.id;
      if (next) this.focus(next);
      return true;
    }
    const centre = (): Point => {
      const node = focused ? this.byId.get(focused) : undefined;
      return node ? toScreen(this.camera, [node.rect.x + node.rect.width / 2, node.rect.y + node.rect.height / 2])
        : [this.viewport.width / 2, this.viewport.height / 2];
    };
    switch (input.key) {
      case "+": case "=": this.zoom(KEY_ZOOM, centre(), "key"); return true;
      case "-": case "_": this.zoom(1 / KEY_ZOOM, centre(), "key"); return true;
      case "0": this.fit(); return true;
      case "Home": case "End": {
        const order = this.reading();
        const target = input.key === "Home" ? order[0] : order[order.length - 1];
        if (target) this.focus(target.id);
        return true;
      }
      case "Escape": this.leave("key"); return this.canLeave;
      default: return false;
    }
  }

  /** Focus a node and pan the minimum needed to show it. */
  focus(id: string) {
    const node = this.byId.get(id);
    if (!node) return;
    this.set(reveal(this.camera, node.rect, this.viewport));
    this.handlers.focus(id);
  }

  /** Nodes in reading order: top to bottom, then left to right. */
  private reading(): ControllerNode[] {
    return [...this.nodes].sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
  }

  private pinchState(): { distance: number; mid: Point } | undefined {
    const [a, b] = [...this.pointers.values()];
    if (!a || !b) return undefined;
    return { distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), mid: [(a.x + b.x) / 2, (a.y + b.y) / 2] };
  }

  private clamp(camera: Camera): Camera {
    const k = Math.min(this.range.max, Math.max(this.range.min, camera.k));
    return clampPan({ ...camera, k }, this.bounds, this.viewport);
  }
}

/** Nearest node in a direction from a node's centre, favouring alignment; `undefined` at the edge of the map. */
export function neighbour(nodes: readonly ControllerNode[], from: string, direction: Direction): string | undefined {
  const origin = nodes.find(node => node.id === from);
  if (!origin) return undefined;
  const centre = (node: ControllerNode): Point => [node.rect.x + node.rect.width / 2, node.rect.y + node.rect.height / 2];
  const [ox, oy] = centre(origin);
  let best: { id: string; score: number } | undefined;
  for (const node of nodes) {
    if (node.id === from) continue;
    const [x, y] = centre(node);
    const along = direction === "right" ? x - ox : direction === "left" ? ox - x : direction === "down" ? y - oy : oy - y;
    const across = direction === "left" || direction === "right" ? Math.abs(y - oy) : Math.abs(x - ox);
    if (along <= 1) continue;
    const score = along + 2 * across;
    if (!best || score < best.score) best = { id: node.id, score };
  }
  return best?.id;
}
