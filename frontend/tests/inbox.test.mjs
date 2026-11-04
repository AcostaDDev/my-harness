import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import { inboxResponse } from '../src/inbox-actions.ts';
import { parse, href } from '../src/router.ts';

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ServiceModeContext } = await import('../src/ServiceMode.tsx');
const { Page } = await import('../src/Page.tsx');
delete globalThis.__tsxHookHarness;

const item = { id: 'auto-question:q-1', kind: 'question', topic: 'autonomous_question', mode: 'autonomous',
  project_id: 'knowledge-project', registered_project_id: 'synthetic', knowledge_project_id: 'knowledge-project',
  at: '2026-11-04T10:00:00Z', origin: 'autonomous', event_id: '10', phase_id: 'P001', task_id: null,
  run_id: 'a-1', autonomous_run_id: 'a-1', operation_id: null, request_id: 'q-1', evidence_id: 'q-1',
  thread_id: 'thread-1', read_at: null, resolved: false, current_state: 'WAITING_FOR_OWNER',
  context: ['Which synthetic output?'], response: { target_id: 'a-1', version: 11, request_version: 2, prompts: ['Synthetic question'] } };

test('inbox and lifecycle shortcuts round-trip independently of reviewer chat', () => {
  for (const route of [{ name: 'inbox' }, { name: 'project-inbox', project: 'synthetic' },
    { name: 'project-inbox', project: 'synthetic', item: item.id },
    { name: 'phase', project: 'synthetic', phase: 'P001', section: 'check' },
    { name: 'project-autonomous', project: 'synthetic', run: 'a-1' }, { name: 'chat', project: 'synthetic' }]) {
    assert.deepEqual(parse(href(route)), route);
  }
});

test('inbox response binds the exact origin and keeps autonomous answer separate from resume', () => {
  const inputs = { answers: ['Synthetic answer.'], reason: 'Synthetic reason', scope: 'once', confirmed: true, ttl: 3600 };
  assert.deepEqual(inboxResponse(item, inputs), {
    path: '/projects/synthetic/autonomous/runs/a-1/questions/q-1/answer', once: true,
    body: { expected_version: 2, text: 'Synthetic answer.' },
  });
  assert.equal(inboxResponse({ ...item, resolved: true }, inputs), undefined);
  assert.equal(inboxResponse({ ...item, response: null }, inputs), undefined);
  assert.equal(inboxResponse({ ...item, topic: 'judge_escalation' }, inputs), undefined);
  assert.equal(inboxResponse(item, { ...inputs, confirmed: false }), undefined);
  const phase = { ...item, topic: 'phase_question', response: { ...item.response, target_id: 'phase-1' } };
  assert.equal(inboxResponse(phase, inputs).path, '/phases/phase-1/questions/q-1/answer');
  assert.deepEqual(inboxResponse(phase, inputs).body, {
    expected_version: 11, expected_question_version: 2, answer: 'Synthetic answer.', confirmed: true,
  });
  const permission = { ...item, topic: 'run_permission', response: { ...item.response, proof: 'a'.repeat(64) } };
  assert.equal(inboxResponse(permission, inputs), undefined);
  assert.equal(inboxResponse(permission, inputs, 'grant').body.fingerprint, 'a'.repeat(64));
});

test('archive mounts the inbox item and exposes evidence without a write control or a polling timer', async () => {
  const env = hookHost();
  const requests = [], timers = [];
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.localStorage = { getItem: () => 'en', setItem() {} };
  globalThis.document = { documentElement: { lang: '' } };
  globalThis.setTimeout = () => { timers.push(true); return timers.length; };
  globalThis.clearTimeout = () => {};
  globalThis.fetch = async (url, options) => {
    assert.equal(options, undefined);
    requests.push(url);
    if (url === '/api/managed/preferences') return Response.json({ status: 'missing' });
    assert.equal(url, '/api/managed/inbox/auto-question%3Aq-1?project=knowledge-project');
    // Even if a stale detail carries a response envelope, the archive gate suppresses the control.
    return Response.json(item);
  };
  try {
    const mode = { read_only_archive: true };
    const route = parse('/projects/knowledge-project/inbox/auto-question%3Aq-1');
    const html = await env.render(el(I18nProvider, null, el(ServiceModeContext.Provider, { value: mode }, el(Page, { route }))));
    assert.match(html, /Which synthetic output/);
    assert.match(html, /WAITING_FOR_OWNER/);
    assert.match(html, /q-1/);
    assert.doesNotMatch(html, /<input|<button|<textarea|Mark as read|Open run/);
    assert.equal(requests.filter(url => url.includes('/inbox/')).length, 1);
    assert.deepEqual(timers, []);
  } finally {
    env.close(); Object.assign(globalThis, original);
    delete globalThis.localStorage; delete globalThis.document;
  }
});

test('standing permission conversation displays only the selected request without fetching the ledger', async () => {
  const env = hookHost();
  const requests = [];
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.localStorage = { getItem: () => 'en', setItem() {} };
  globalThis.document = { documentElement: { lang: '' } };
  globalThis.setTimeout = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.fetch = async (url, options) => {
    assert.equal(options, undefined);
    requests.push(url);
    if (url === '/api/managed/preferences') return Response.json({ status: 'missing' });
    assert.equal(url, '/api/managed/inbox/standing-permission%3Ap-1?project=synthetic');
    return Response.json({ ...item, id: 'standing-permission:p-1', kind: 'permission', topic: 'standing_permission',
      request_id: 'p-1', run_id: null, autonomous_run_id: null, response: null,
      standing_permission: { revision: 6, duration: { kind: 'operation', seconds: null }, targets: ['synthetic exact target'] } });
  };
  try {
    const route = parse('/projects/synthetic/inbox/standing-permission%3Ap-1');
    const html = await env.render(el(I18nProvider, null,
      el(ServiceModeContext.Provider, { value: { read_only_archive: false } }, el(Page, { route }))));
    assert.match(html, /synthetic exact target/);
    assert.match(html, /Mark as read/);
    assert.doesNotMatch(requests.join(' '), /\/projects\/synthetic\/permissions/);
  } finally {
    env.close(); Object.assign(globalThis, original);
    delete globalThis.localStorage; delete globalThis.document;
  }
});

test('recorded task clarification requires a separate retry confirmation bound to the resolution', async () => {
  const env = hookHost();
  const requests = [];
  const storage = new Map();
  let confirmed = false;
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.localStorage = { getItem: () => 'en', setItem() {} };
  globalThis.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) };
  globalThis.document = { documentElement: { lang: '' } };
  globalThis.window = { confirm: () => confirmed };
  globalThis.setTimeout = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.fetch = async (url, options) => {
    if (options) {
      requests.push({ url, body: JSON.parse(options.body), key: options.headers['Idempotency-Key'] });
      return Response.json({ run_id: 'task-run' });
    }
    if (url === '/api/managed/preferences') return Response.json({ status: 'missing' });
    assert.equal(url, '/api/managed/inbox/gap%3A10?project=synthetic');
    return Response.json({ ...item, id: 'gap:10', kind: 'question', topic: 'task_gap', resolved: true,
      response: null, standing_permission: null, continuation: { target_id: 'task-run', version: 12, resolution_id: 11 } });
  };
  try {
    const { default: en } = await import('../src/i18n/en.json', { with: { type: 'json' } });
    const route = parse('/projects/synthetic/inbox/gap%3A10');
    const tree = el(I18nProvider, null, el(ServiceModeContext.Provider, { value: { read_only_archive: false } }, el(Page, { route })));
    await env.render(tree);
    const retry = env.host.elements.find(e => e.type === 'button' && e.props.children === en['run.retry']);
    assert.ok(retry && !retry.props.disabled);
    retry.props.onClick();
    assert.equal(requests.length, 0);
    confirmed = true;
    retry.props.onClick();
    await env.render(tree);
    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0].body, { action: 'retry_executor', expected_version: 12, gap_resolution_id: 11 });
    assert.equal(requests[0].url, '/api/managed/runs/task-run/actions');
    assert.ok(requests[0].key);
  } finally {
    env.close(); Object.assign(globalThis, original);
    for (const key of ['localStorage', 'sessionStorage', 'document', 'window']) delete globalThis[key];
  }
});
