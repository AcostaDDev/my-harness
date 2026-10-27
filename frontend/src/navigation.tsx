import { useSyncExternalStore } from "react";
import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { href } from "./router.ts";
import type { Route } from "./router.ts";

// History API without dependencies (D076). Navigating never repeats actions: it only changes the view.
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  return () => { listeners.delete(listener); window.removeEventListener("popstate", listener); };
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}

export function navigate(to: Route | string, options: { replace?: boolean } = {}) {
  const path = typeof to === "string" ? to : href(to);
  if (path === window.location.pathname) return;
  if (options.replace) window.history.replaceState(null, "", path);
  else window.history.pushState(null, "", path);
  listeners.forEach(listener => listener());
}

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { to: Route | string; current?: boolean };

/** Real link (open in another tab, copy) with internal navigation for a plain click. */
export function Link({ to, current, onClick, children, ...rest }: LinkProps) {
  const path = typeof to === "string" ? to : href(to);
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(path);
  }
  return <a href={path} onClick={follow} aria-current={current ? "page" : undefined} {...rest}>{children}</a>;
}
