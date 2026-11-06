// Camera of the work map: pure geometry, no DOM. A screen point s and a world point w relate by s = w·k + (x, y).
import type { Bounds, Point } from "./layout.ts";

export type Camera = { x: number; y: number; k: number };
export type Viewport = { width: number; height: number };
export type Limits = { min: number; max: number };

/** Margin around the content when fitting, in screen pixels. */
export const FIT_PADDING = 48;
/** A fitted view never magnifies beyond this scale, so one or two cards do not fill the screen. */
export const FIT_MAX = 1.25;
/** Largest zoom; the smallest is relative to the content (`limits`), so any accepted level can fit. */
export const SCALE_MAX = 4;
/** Screen pixels of content that always stay inside the viewport while panning. */
export const PAN_MARGIN = 96;

export const IDENTITY: Camera = { x: 0, y: 0, k: 1 };

export function toScreen(camera: Camera, [x, y]: Point): Point { return [x * camera.k + camera.x, y * camera.k + camera.y]; }
export function toWorld(camera: Camera, [x, y]: Point): Point { return [(x - camera.x) / camera.k, (y - camera.y) / camera.k]; }

/** Camera that shows the whole content centred, with padding, never above `FIT_MAX`. */
export function fit(bounds: Bounds, viewport: Viewport, padding = FIT_PADDING): Camera {
  const width = Math.max(1, viewport.width - 2 * padding), height = Math.max(1, viewport.height - 2 * padding);
  const k = bounds.width && bounds.height ? Math.min(FIT_MAX, width / bounds.width, height / bounds.height) : 1;
  return { k, x: viewport.width / 2 - (bounds.x + bounds.width / 2) * k, y: viewport.height / 2 - (bounds.y + bounds.height / 2) * k };
}

/**
 * Zoom range for some content: down to half of the fitted scale (or of 1 when the content fits at full size) and up
 * to `SCALE_MAX`. The minimum is never an absolute floor: a fixed floor above a large level's fitted scale would clip
 * "fit" and leave cards outside the view (re-review finding). `fit` is finite and positive for any finite bounds.
 */
export function limits(bounds: Bounds, viewport: Viewport): Limits {
  const fitted = fit(bounds, viewport).k;
  return { min: Math.min(fitted, 1) * 0.5, max: SCALE_MAX };
}

/** Keeps at least `PAN_MARGIN` pixels of the content (or all of it when smaller) inside the viewport. */
export function clampPan(camera: Camera, bounds: Bounds, viewport: Viewport): Camera {
  const axis = (offset: number, start: number, size: number, screen: number) => {
    const low = start * camera.k + offset, extent = size * camera.k;
    const keep = Math.min(PAN_MARGIN, extent, screen);
    if (low + extent < keep) return offset + keep - (low + extent);
    if (low > screen - keep) return offset - (low - (screen - keep));
    return offset;
  };
  return { k: camera.k, x: axis(camera.x, bounds.x, bounds.width, viewport.width), y: axis(camera.y, bounds.y, bounds.height, viewport.height) };
}

/** Zoom by `factor` keeping the world point under the screen point `at` fixed; the scale stays within `range`. */
export function zoomAt(camera: Camera, factor: number, at: Point, range: Limits): Camera {
  const k = Math.min(range.max, Math.max(range.min, camera.k * factor));
  const [wx, wy] = toWorld(camera, at);
  return { k, x: at[0] - wx * k, y: at[1] - wy * k };
}

export function panBy(camera: Camera, dx: number, dy: number): Camera { return { k: camera.k, x: camera.x + dx, y: camera.y + dy }; }

/** Smallest pan that brings a world rectangle fully into view with a margin (keyboard focus follows the camera). */
export function reveal(camera: Camera, rect: Bounds, viewport: Viewport, margin = 24): Camera {
  const axis = (offset: number, start: number, size: number, screen: number) => {
    const low = start * camera.k + offset, high = low + size * camera.k;
    if (high - low > screen - 2 * margin) return offset + (screen / 2 - (low + high) / 2);
    if (low < margin) return offset + margin - low;
    if (high > screen - margin) return offset - (high - (screen - margin));
    return offset;
  };
  return { k: camera.k, x: axis(camera.x, rect.x, rect.width, viewport.width), y: axis(camera.y, rect.y, rect.height, viewport.height) };
}

/** Share of the viewport that a world rectangle covers on its tighter axis (1 = fills the width or the height). */
export function coverage(camera: Camera, rect: Bounds, viewport: Viewport): number {
  return Math.max(rect.width * camera.k / viewport.width, rect.height * camera.k / viewport.height);
}

/** Linear interpolation of position and logarithmic interpolation of scale, for camera transitions. */
export function between(from: Camera, to: Camera, t: number): Camera {
  if (t >= 1) return to;
  return { k: from.k * Math.pow(to.k / from.k, t), x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t };
}

/** Transform attribute of the world group, rounded to keep the DOM writes small and stable. */
export function transformOf(camera: Camera): string {
  const r = (n: number) => Math.round(n * 1000) / 1000;
  return `translate(${r(camera.x)} ${r(camera.y)}) scale(${r(camera.k)})`;
}
