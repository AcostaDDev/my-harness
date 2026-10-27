import { renderToStaticMarkup } from 'react-dom/server';

export function hookHost() {
  const host = { state: new Map(), effects: new Map(), pending: [], elements: [], dirty: true };
  globalThis.__tsxHookHarness = host;
  return {
    host,
    async render(tree) {
      let html;
      for (let count = 0; count < 30; count++) {
        host.dirty = false; host.elements = [];
        html = renderToStaticMarkup(tree);
        for (const effect of host.pending.splice(0)) effect();
        await new Promise(resolve => setImmediate(resolve));
        if (!host.dirty) return html;
      }
      throw new Error('Hook host did not settle');
    },
    close() {
      for (const effect of host.effects.values()) effect.cleanup?.();
      delete globalThis.__tsxHookHarness;
    },
  };
}
