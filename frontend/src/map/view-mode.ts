// Map/list toggle (T018 §4, D304, P002-T022): the same path renders either view. `?view=map` or `?view=list` selects
// it; without the parameter the last choice made with the toggle applies, falling back to the map. A parameter only
// applies to its own URL (an evidence link opens the list without changing what the owner chose). The memory is a
// convenience, never authority: storage may be missing or throw (private windows, blocked site data), and the last
// choice made in this page wins over an older stored one when writing it failed.
import { navigate, usePath, useSearch } from "../navigation";
import { href } from "../router.ts";
import type { Route } from "../router.ts";

export type ViewMode = "map" | "list";
export const VIEW_STORAGE = "harness-map-view";
let memory: ViewMode | undefined;

export function isViewMode(value: unknown): value is ViewMode {
  return value === "map" || value === "list";
}

/** The `view` parameter of a query string, if it is a valid choice. */
export function viewParam(search: string): ViewMode | undefined {
  try {
    const value = new URLSearchParams(search).get("view");
    return isViewMode(value) ? value : undefined;
  } catch { return undefined; }
}

/** The last choice made in this page, else the one stored in this browser. */
export function rememberedView(): ViewMode | undefined {
  if (memory) return memory;
  try {
    const value = globalThis.localStorage?.getItem(VIEW_STORAGE);
    if (isViewMode(value)) return value;
  } catch { /* storage unavailable */ }
  return undefined;
}

export function rememberView(mode: ViewMode) {
  memory = mode;
  try { globalThis.localStorage?.setItem(VIEW_STORAGE, mode); } catch { /* kept in memory only */ }
}

/** Test hook: forget the in-page memory. */
export function forgetViewMemory() { memory = undefined; }

/** Effective view: the parameter, else the remembered choice, else the map. */
export function viewOf(search: string): ViewMode {
  return viewParam(search) ?? rememberedView() ?? "map";
}

/** `path` with `view` set and every other parameter kept. */
export function withView(path: string, search: string, mode: ViewMode): string {
  const params = new URLSearchParams(search);
  params.set("view", mode);
  return `${path}?${params}`;
}

/** The list view of `route` (the existing page with its evidence and controls), whatever was chosen before. */
export function listHref(route: Route): string {
  return withView(href(route), "", "list");
}

/** Writes the choice into the URL (a history entry, so Back/Forward replay it) and remembers it. */
export function chooseView(path: string, search: string, mode: ViewMode) {
  rememberView(mode);
  navigate(withView(path, search, mode));
}

export function useViewMode(): { mode: ViewMode; choose: (mode: ViewMode) => void } {
  const path = usePath();
  const search = useSearch();
  const mode = viewOf(search);
  return { mode, choose: next => chooseView(path, search, next) };
}
