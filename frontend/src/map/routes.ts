// Binding of the map to the existing router and browser history (T018 §4, D304). Every level is an existing URL:
// entering pushes the child's route, leaving pushes the parent's, and Back/Forward replay them. The map never keeps
// a navigation model of its own. `base` prefixes the paths only for the development fixture (D312).
import { navigate, usePath } from "../navigation";
import { href, parse } from "../router.ts";
import type { Route } from "../router.ts";
import type { Camera } from "./camera.ts";

export type MapLevel = 0 | 1 | 2 | 3;

/** Map level of a route: L0 home, L1 phases, L2 phase, L3 task (latest run) or run (selected run). */
export function mapLevel(route: Route): MapLevel | undefined {
  switch (route.name) {
    case "home": return 0;
    case "phases": return 1;
    case "phase": return route.section ? undefined : 2;
    case "task": case "run": return 3;
    default: return undefined;
  }
}

/** Parent level for Escape and zoom-out. A selected run and the latest run are both L3, so both return to L2. */
export function mapParent(route: Route): Route | undefined {
  switch (route.name) {
    case "phases": return { name: "home" };
    case "phase": return route.section ? undefined : { name: "phases", project: route.project };
    case "task": case "run": return { name: "phase", project: route.project, phase: route.phase };
    default: return undefined;
  }
}

function cleanBase(base: string): string { return base.replace(/\/+$/, ""); }

/** URL of a map route, under the fixture base when there is one. */
export function mapPath(route: Route, base = ""): string {
  const path = href(route);
  const prefix = cleanBase(base);
  return prefix ? `${prefix}${path === "/" ? "/" : path}` : path;
}

/** Route of a URL under `base`; a URL outside the base is not a map route. */
export function mapRoute(pathname: string, base = ""): Route {
  const prefix = cleanBase(base);
  if (!prefix) return parse(pathname);
  if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) return { name: "not-found", path: pathname };
  return parse(pathname.slice(prefix.length) || "/");
}

// Per-browser-tab memory of the camera and focused node of each visited level, so Back/Forward and leaving a level
// restore the previous view. Bounded (TM15) and never authority: losing it only means fitting the view again.
const MEMORY_LIMIT = 64;
const views = new Map<string, { camera?: Camera; focus?: string }>();

export function rememberView(path: string, view: { camera?: Camera; focus?: string }) {
  const previous = views.get(path);
  views.delete(path);
  views.set(path, { ...previous, ...view });
  while (views.size > MEMORY_LIMIT) views.delete(views.keys().next().value!);
}

export function recallView(path: string): { camera?: Camera; focus?: string } | undefined { return views.get(path); }

export function forgetViews() { views.clear(); }

/** Map route of a path and its two navigations, through the shared `navigate` (pushState, deduplicated). */
export function mapNavigation(path: string, base = "") {
  const route = mapRoute(path, base);
  const parent = mapParent(route);
  return {
    path,
    route,
    parent,
    level: mapLevel(route),
    /** `from` is the entered node: the parent level focuses it again on return. */
    enter(to: Route, from?: string) {
      if (from) rememberView(path, { focus: from });
      navigate(mapPath(to, base));
    },
    /** The parent restores the focus remembered when this level was entered from it. */
    leave() {
      if (parent) navigate(mapPath(parent, base));
    },
  };
}

/** `mapNavigation` for the current location; re-renders on navigation and on Back/Forward. */
export function useMapNavigation(base = "") {
  return mapNavigation(usePath(), base);
}
