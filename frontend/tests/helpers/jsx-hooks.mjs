import * as runtime from 'react/jsx-runtime';
import { HookScope } from './react-hooks.mjs';
export const Fragment = runtime.Fragment;
function record(method, type, props, key) {
  if (Array.isArray(props.children)) {
    const keys = props.children.filter(child => child && typeof child === 'object' && child.key != null).map(child => child.key);
    if (new Set(keys).size !== keys.length) throw new Error('Duplicate sibling keys: ' + keys.join(', '));
  }
  if (typeof type === 'string') globalThis.__tsxHookHarness.elements.push({ type, props });
  const element = runtime[method](type, props, key);
  // Opt in for tests that need a fresh hook scope when a particular subtree's key changes.
  return globalThis.__tsxHookHarness.keyed?.has(type)
    ? runtime.jsx(HookScope.Provider, { value: String(key), children: element })
    : element;
}
export const jsx = (type, props, key) => record('jsx', type, props, key);
export const jsxs = (type, props, key) => record('jsxs', type, props, key);
