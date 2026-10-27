import * as runtime from 'react/jsx-runtime';
export const Fragment = runtime.Fragment;
function record(method, type, props, key) {
  if (Array.isArray(props.children)) {
    const keys = props.children.filter(child => child && typeof child === 'object' && child.key != null).map(child => child.key);
    if (new Set(keys).size !== keys.length) throw new Error('Duplicate sibling keys: ' + keys.join(', '));
  }
  if (typeof type === 'string') globalThis.__tsxHookHarness.elements.push({ type, props });
  return runtime[method](type, props, key);
}
export const jsx = (type, props, key) => record('jsx', type, props, key);
export const jsxs = (type, props, key) => record('jsxs', type, props, key);
