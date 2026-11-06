// `prefers-reduced-motion` (T018 §11): transitions become immediate and activity marks stay static.
import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function media(): MediaQueryList | undefined {
  try { return typeof window !== "undefined" && window.matchMedia ? window.matchMedia(QUERY) : undefined; }
  catch { return undefined; }
}

function subscribe(listener: () => void) {
  const query = media();
  query?.addEventListener("change", listener);
  return () => query?.removeEventListener("change", listener);
}

/** Whether the system asks for reduced motion; false where it cannot be read (server rendering, old engines). */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, () => media()?.matches ?? false, () => false);
}

/** Duration of the camera transition that finishes a zoom-enter; zero means navigate at once. */
export const ENTER_TRANSITION_MS = 220;
export function transitionMs(reduced: boolean): number { return reduced ? 0 : ENTER_TRANSITION_MS; }

/** Ease-out cubic for camera transitions. */
export function ease(t: number): number { return 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3); }
