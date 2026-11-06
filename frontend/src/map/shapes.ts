// Hand-drawn outlines with rough.js 4.6.6 (D308). Only the generator is used: it computes path data without a DOM or
// canvas, and the view renders that data as ordinary SVG paths whose colours come from the theme tokens in CSS.
// The import is the same module mermaid uses, so the built bundle shares one rough.js chunk.
import rough from "roughjs";
import type { Point } from "./layout.ts";
import { seedOf } from "./seed.ts";

export type ShapePath = { d: string; fill: boolean };

type Drawable = ReturnType<ReturnType<typeof rough.generator>["path"]>;

const generator = rough.generator();
const BASE = { roughness: 1.1, bowing: 1, stroke: "stroke", strokeWidth: 1, fill: "fill", fillStyle: "solid" } as const;
/** Bounded cache (TM15): shapes are pure functions of their identity, size and geometry. */
const CACHE_LIMIT = 4000;
const cache = new Map<string, ShapePath[]>();

function memo(key: string, draw: () => Drawable): ShapePath[] {
  const hit = cache.get(key);
  if (hit) return hit;
  const drawable = draw();
  const paths: ShapePath[] = [];
  for (const set of drawable.sets) {
    if (set.type === "fillSketch") continue;
    // One decimal keeps the path data compact; the multi-stroke stays in a single path element.
    paths.push({ d: generator.opsToPath(set, 1), fill: set.type === "fillPath" });
  }
  if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value!);
  cache.set(key, paths);
  return paths;
}

const round = (n: number) => Math.round(n * 10) / 10;

/** Rounded card of a node, drawn from the node identity. */
export function cardShape(identity: string, width: number, height: number): ShapePath[] {
  const r = Math.min(16, width / 6, height / 4);
  const d = `M ${r} 0 L ${width - r} 0 Q ${width} 0, ${width} ${r} L ${width} ${height - r} Q ${width} ${height}, ${width - r} ${height}`
    + ` L ${r} ${height} Q 0 ${height}, 0 ${height - r} L 0 ${r} Q 0 0, ${r} 0 Z`;
  return memo(`card:${identity}:${width}x${height}`, () => generator.path(d, { ...BASE, seed: seedOf(`card:${identity}`) }));
}

/** Edge line through its layout points with an arrowhead at the target. */
export function edgeShape(identity: string, points: readonly Point[]): { line: ShapePath[]; head: ShapePath[] } {
  const key = points.map(([x, y]) => `${round(x)},${round(y)}`).join(" ");
  const seed = seedOf(`edge:${identity}`);
  const options = { ...BASE, fill: undefined, seed, roughness: 0.9 };
  const line = memo(`edge:${identity}:${key}`, () => points.length > 2
    ? generator.curve(points as Point[], options)
    : generator.line(points[0][0], points[0][1], points[1][0], points[1][1], options));
  const [x1, y1] = points[points.length - 2], [x2, y2] = points[points.length - 1];
  const angle = Math.atan2(y2 - y1, x2 - x1), size = 11, spread = Math.PI / 7;
  const wing = (sign: number): Point => [x2 - size * Math.cos(angle + sign * spread), y2 - size * Math.sin(angle + sign * spread)];
  const head = memo(`head:${identity}:${key}`, () => generator.linearPath([wing(1), [x2, y2], wing(-1)], { ...options, seed: seed + 1 }));
  return { line, head };
}

/** Actor circle (R/E/J/H) on a node. */
export function circleShape(identity: string, cx: number, cy: number, diameter: number): ShapePath[] {
  return memo(`circle:${identity}:${cx},${cy},${diameter}`, () => generator.circle(cx, cy, diameter, { ...BASE, seed: seedOf(`circle:${identity}`) }));
}

/** Short static rays around an active actor circle; motion, when allowed, is a CSS effect on top. */
export function raysShape(identity: string, cx: number, cy: number, radius: number): ShapePath[] {
  const segments = [-150, -90, -30].map(degrees => {
    const a = degrees * Math.PI / 180;
    return `M ${round(cx + Math.cos(a) * (radius + 3))} ${round(cy + Math.sin(a) * (radius + 3))} L ${round(cx + Math.cos(a) * (radius + 9))} ${round(cy + Math.sin(a) * (radius + 9))}`;
  }).join(" ");
  return memo(`rays:${identity}:${cx},${cy},${radius}`, () => generator.path(segments, { ...BASE, fill: undefined, seed: seedOf(`rays:${identity}`), roughness: 0.6 }));
}

/** Comic bubble with a tail pointing down-left, for the request count primitive. */
export function bubbleShape(identity: string, width: number, height: number): ShapePath[] {
  const d = `M 6 0 L ${width - 6} 0 Q ${width} 0, ${width} 6 L ${width} ${height - 6} Q ${width} ${height}, ${width - 6} ${height}`
    + ` L 12 ${height} L 4 ${height + 7} L 6 ${height} Q 0 ${height}, 0 ${height - 6} L 0 6 Q 0 0, 6 0 Z`;
  return memo(`bubble:${identity}:${width}x${height}`, () => generator.path(d, { ...BASE, seed: seedOf(`bubble:${identity}`), roughness: 0.8 }));
}

/** Status icon in a 20×20 box, one look per class. */
export function iconShape(statusClass: string, icon: { kind: "path" | "circle"; d?: string }): ShapePath[] {
  const options = { ...BASE, fill: undefined, seed: seedOf(`icon:${statusClass}`), roughness: 0.7 };
  return memo(`icon:${statusClass}`, () => icon.kind === "circle" ? generator.circle(10, 10, 14, options) : generator.path(icon.d!, options));
}

/** Number of cached shapes; exposed for tests of the bound. */
export function cachedShapes(): number { return cache.size; }

/** Empties the cache, so the development fixture can measure a cold first render. */
export function clearShapes() { cache.clear(); }
