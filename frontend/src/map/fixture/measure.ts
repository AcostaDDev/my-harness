// Browser measurements for D309's rendering budgets in the development fixture. They time real frames in the
// browser; computing or server-rendering times are not evidence for these budgets.
import { toScreen } from "../camera.ts";
import type { MapController } from "../controller.ts";
import type { Bounds } from "../layout.ts";

export type BenchmarkResult = { frames: number; meanFps: number; lowFps: number; worstMs: number; visible: number };

/** Frame intervals summarised: mean rate, 5th-percentile rate (95th-percentile interval) and longest interval. */
export function summarise(intervals: readonly number[], visible: number): BenchmarkResult {
  if (!intervals.length) return { frames: 0, meanFps: 0, lowFps: 0, worstMs: 0, visible };
  const sorted = [...intervals].sort((a, b) => a - b);
  const mean = intervals.reduce((sum, value) => sum + value, 0) / intervals.length;
  const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))];
  const r = (n: number) => Math.round(n * 10) / 10;
  return { frames: intervals.length, meanFps: r(1000 / mean), lowFps: r(1000 / p95), worstMs: r(sorted[sorted.length - 1]), visible };
}

/** Nodes whose card is entirely inside the viewport for the current camera. */
export function visibleNodes(controller: MapController, rects: readonly Bounds[], width: number, height: number): number {
  return rects.filter(rect => {
    const [x1, y1] = toScreen(controller.camera, [rect.x, rect.y]);
    const [x2, y2] = toScreen(controller.camera, [rect.x + rect.width, rect.y + rect.height]);
    return x1 >= 0 && y1 >= 0 && x2 <= width && y2 <= height;
  }).length;
}

/**
 * Scripted pan and zoom through the controller (the same path as gestures) on every animation frame for `duration`
 * ms from the fitted camera: the scale varies between 84 % and 100 % of it and the pan stays within the fit padding,
 * so every card that is in view at the start stays in view.
 */
export function panZoomBenchmark(controller: MapController, visible: number, duration = 4000): Promise<BenchmarkResult> {
  return new Promise(resolve => {
    const base = controller.camera;
    const intervals: number[] = [];
    let start = 0, last = 0;
    const step = (now: number) => {
      if (!start) start = now; else intervals.push(now - last);
      last = now;
      const t = (now - start) / 1000;
      controller.set({ k: base.k * (0.92 - 0.08 * Math.sin(t * 2.1)), x: base.x + 20 + 20 * Math.sin(t * 1.3), y: base.y + 20 + 20 * Math.cos(t * 1.7) });
      if (now - start < duration) requestAnimationFrame(step);
      else { controller.set(base); resolve(summarise(intervals, visible)); }
    };
    requestAnimationFrame(step);
  });
}
