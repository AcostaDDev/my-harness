import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';

// OT002: the live rail reads the existing event cursor backwards from the run's version, then forwards.
// Synthetic events only; no browser or service.
globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { LiveActivity } = await import('../src/Activity.tsx');
delete globalThis.__tsxHookHarness;

const at = '2026-10-27T10:00:00Z';
const agent = (sequence, original) => ({ id: sequence, sequence, kind: 'agent_event', recorded_at: at, payload: { attempt_id: 'a1', original } });
const bytes = sequence => ({ id: sequence, sequence, kind: 'stream_bytes', recorded_at: at, payload: { size: 1 } });

for (const language of ['en', 'es']) test(`the feed backfills the latest windows, then follows the cursor (${language})`, async () => {
  const host = hookHost(), requests = [], timers = [];
  const originals = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = callback => { timers.push(callback); return timers.length; };
  globalThis.clearTimeout = () => {};
  globalThis.document = { documentElement: {} };
  globalThis.localStorage = { getItem: () => language, setItem() {} };
  // 250 events: only stream bytes except two tool calls far back and a message at the end.
  const all = Array.from({ length: 250 }, (_, i) => bytes(i + 1));
  all[59] = agent(60, { type: 'assistant', message: { id: 'm1', content: [{ type: 'tool_use', id: 't1', name: 'Read', input: { file_path: 'docs/STATE.md' } }] } });
  all[119] = agent(120, { type: 'assistant', message: { id: 'm2', content: [{ type: 'tool_use', id: 't2', name: 'Bash', input: { command: 'git status' } }] } });
  all[249] = agent(250, { type: 'assistant', message: { id: 'm3', content: [{ type: 'text', text: 'Reviewing the drafts' }] } });
  globalThis.fetch = async path => {
    requests.push(path);
    if (path === '/api/managed/preferences') return Response.json({ version: 1, ui_language: language, default_work_language: 'en' });
    const url = new URL(path, 'http://local');
    const after = Number(url.searchParams.get('after')), limit = Number(url.searchParams.get('limit'));
    const items = all.filter(e => e.sequence > after).slice(0, limit);
    return Response.json({ items, cursor: items.at(-1)?.sequence ?? after, has_more: all.some(e => e.sequence > after + limit) });
  };
  try {
    const tree = el(I18nProvider, null, el(LiveActivity, { runId: 'run-1', version: 250, status: 'REVIEWING' }));
    let html = await host.render(tree);
    const events = requests.filter(path => path.includes('/events'));
    assert.deepEqual(events, ['/api/managed/runs/run-1/events?after=150&limit=100', '/api/managed/runs/run-1/events?after=50&limit=100',
      '/api/managed/runs/run-1/events?after=0&limit=100', '/api/managed/runs/run-1/events?after=250&limit=100'], 'backwards until there is context, then from the present');
    const catalog = (await import(`../src/i18n/${language}.json`, { with: { type: 'json' } })).default;
    for (const text of ['Reviewing the drafts', 'git status', 'docs/STATE.md', catalog['activity.read'], catalog['activity.command']]) assert.ok(html.includes(text), text);
    assert.ok(html.indexOf('Reviewing the drafts') < html.indexOf('git status'), 'newest step first');
    // The next forward page appends without reading again what was shown.
    all.push(agent(251, { type: 'result', subtype: 'success', is_error: false, num_turns: 2, duration_ms: 10 }));
    timers.shift()();
    await new Promise(resolve => setImmediate(resolve));
    html = await host.render(tree);
    assert.equal(requests.filter(path => path.includes('/events')).at(-1), '/api/managed/runs/run-1/events?after=250&limit=100');
    assert.ok(html.includes(catalog['activity.agent_done']));
    assert.ok(requests.every(path => !/messages|actions|confirm/.test(path)), 'the rail only reads');
  } finally {
    host.close(); Object.assign(globalThis, originals);
    delete globalThis.document; delete globalThis.localStorage;
  }
});
