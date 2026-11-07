import { createContext, useContext, useSyncExternalStore } from "react";
import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { href } from "./router.ts";
import type { Route } from "./router.ts";

// History API without dependencies (D076). Navigating never repeats actions: it only changes the view.
// The path selects the page; the query only carries view options of the same page (`?view=map|list`, P002-T022), so
// `usePath` subscribers do not re-render when only the query changes and `useSearch` subscribers see both.
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  return () => { listeners.delete(listener); window.removeEventListener("popstate", listener); };
}

// Server renders (the Node tests) read the same location when a window exists.
const pathname = () => globalThis.window?.location?.pathname ?? "/";
const search = () => globalThis.window?.location?.search ?? "";

export function usePath(): string {
  return useSyncExternalStore(subscribe, pathname, pathname);
}

/** Query string of the current location (`""` or `"?…"`); re-renders on navigation, Back/Forward and query changes. */
export function useSearch(): string {
  return useSyncExternalStore(subscribe, search, search);
}

function current(): string {
  return `${window.location.pathname}${window.location.search ?? ""}`;
}

/** `to` may carry a query (`/projects/p/phases?view=list`); a route never does. */
export function navigate(to: Route | string, options: { replace?: boolean } = {}) {
  const path = typeof to === "string" ? to : href(to);
  if (path === current()) return;
  if (options.replace) window.history.replaceState(null, "", path);
  else window.history.pushState(null, "", path);
  listeners.forEach(listener => listener());
}

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { to: Route | string; current?: boolean };

/**
 * Path prefix of route links. Empty in the product; the development map fixture (D312) serves the product map under
 * its own base, so its links stay inside the fixture. String targets are used as given.
 */
export const RouteBase = createContext("");

export function withBase(base: string, path: string): string {
  const prefix = base.replace(/\/+$/, "");
  return prefix ? `${prefix}${path === "/" ? "/" : path}` : path;
}

/** Real link (open in another tab, copy) with internal navigation for a plain click. */
export function Link({ to, current, onClick, children, ...rest }: LinkProps) {
  const base = useContext(RouteBase);
  const path = typeof to === "string" ? to : withBase(base, href(to));
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(path);
  }
  return <a href={path} onClick={follow} aria-current={current ? "page" : undefined} {...rest}>{children}</a>;
}
