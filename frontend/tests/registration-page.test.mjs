import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';

globalThis.__tsxHookHarness = {};
const { RegisterPage } = await import('../src/pages/Registry.tsx');
const { I18nProvider } = await import('../src/Language.tsx');
delete globalThis.__tsxHookHarness;

for (const version of [1, 5]) test(`registration switches entries with one parent picker at revision ${version}`, async () => {
  const host = hookHost();
  const previous = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const requests = [];
  globalThis.setTimeout = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.localStorage = { getItem: () => 'en' };
  globalThis.document = { documentElement: {} };
  globalThis.sessionStorage = { getItem: () => null };
  globalThis.fetch = async path => {
    requests.push(path);
    if (path.endsWith('/preferences')) return Response.json({ version: 1, ui_language: 'en', default_work_language: 'en' });
    if (path.endsWith('/project-creation-root')) return Response.json({ version, status: 'ACTIVE', available: true,
      path: '/synthetic projects', operations: [], history: [] });
    if (path.endsWith('/registry')) return Response.json({ format: 'local-config-9', available: true, creation_available: true,
      roots: ['/synthetic projects'], compositions: [], agent_presets: [], executor_effort_vocabulary: ['medium'],
      reviewer_provider: 'claude', executor_provider: 'claude', bootstrap_enabled: true });
    assert.fail('Unexpected request: ' + path);
  };
  try {
    const tree = el(I18nProvider, null, el(RegisterPage));
    let html = await host.render(tree);
    for (const entry of ['Register an existing folder', 'Create a new folder', 'Register an existing folder', 'Create a new folder']) {
      // JSX hook instrumentation also rejects duplicate explicit keys among siblings before reconciliation.
      assert.equal((html.match(/id="creation-root"/g) ?? []).length, 1);
      const button = host.host.elements.find(e => e.type === 'button' && e.props.children === entry);
      assert.ok(button, entry);
      button.props.onClick();
      html = await host.render(tree);
      assert.equal((html.match(/id="creation-root"/g) ?? []).length, 1);
      assert.match(html, entry === 'Create a new folder' ? /id="new-directory"/ : /Checkout root/);
    }
    assert.ok(requests.every(path => !/preview|confirm|apply/.test(path)));
  } finally {
    host.close(); Object.assign(globalThis, previous);
    delete globalThis.localStorage; delete globalThis.sessionStorage; delete globalThis.document;
  }
});
