// Drive effects/state across real React server renders, without a DOM or application service.
// This is a deterministic hook host for request/navigation tests, not browser lifecycle QA.
export * from 'react';
import * as React from 'react';
export function useState(initial) {
  const host = globalThis.__tsxHookHarness;
  const id = React.useId();
  if (!host.state.has(id)) host.state.set(id, typeof initial === 'function' ? initial() : initial);
  return [host.state.get(id), value => {
    host.state.set(id, typeof value === 'function' ? value(host.state.get(id)) : value);
    host.dirty = true;
  }];
}
export function useRef(initial) { return useState(() => ({ current: initial }))[0]; }
export function useEffect(effect, dependencies) {
  const host = globalThis.__tsxHookHarness;
  const id = React.useId();
  const previous = host.effects.get(id);
  if (!previous || !dependencies || dependencies.some((value, i) => !Object.is(value, previous.dependencies?.[i]))) {
    host.pending.push(() => {
      previous?.cleanup?.();
      host.effects.set(id, { dependencies, cleanup: effect() });
    });
  }
}

// Opt-in lifecycle (host.lifecycle = true): layout effects run like effects and memoized values survive re-renders,
// so a view that measures and resets in a layout effect can be driven across commits. Off by default.
export function useLayoutEffect(effect, dependencies) {
  return globalThis.__tsxHookHarness?.lifecycle ? useEffect(effect, dependencies) : React.useLayoutEffect(effect, dependencies);
}
export function useMemo(factory, dependencies) {
  const host = globalThis.__tsxHookHarness;
  if (!host?.lifecycle) return React.useMemo(factory, dependencies);
  const id = React.useId();
  host.memos ??= new Map();
  const previous = host.memos.get(id);
  if (previous && dependencies && dependencies.length === previous.dependencies.length
    && dependencies.every((value, i) => Object.is(value, previous.dependencies[i]))) return previous.value;
  const value = factory();
  host.memos.set(id, { value, dependencies });
  return value;
}
export function useCallback(callback, dependencies) { return useMemo(() => callback, dependencies); }
