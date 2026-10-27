import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createOnce, managed, managedApi, ManagedError, jobRequest, savePending, readPending } from '../src/managed-api.ts';
import { LocalizedError } from '../src/i18n.ts';
const values = new Map();
globalThis.sessionStorage = { getItem: k => values.get(k) ?? null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k) };
beforeEach(() => values.clear());

test('double send after an immediate acknowledgement reuses key; changed version gets another', () => {
  const first = jobRequest('/runs/r/actions', {action:'commit',expected_version:17});
  savePending(first);
  savePending(); // response acknowledged
  const second = jobRequest('/runs/r/actions', {action:'commit',expected_version:17});
  assert.deepEqual(first, second);
  assert.notEqual(jobRequest('/runs/r/actions', {action:'commit',expected_version:18}).key, first.key);
});

test('network failure preserves exact pending envelope across reload and explicit retry', async () => {
  const pending = jobRequest('/projects/demo/runs', {task_id:'T',phase_id:'P',text:'synthetic'});
  savePending(pending);
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({path,options});
    if (calls.length === 1) throw new TypeError('Failed to fetch');
    return Response.json({id:1});
  };
  await assert.rejects(managed(pending.path,pending.body,pending.key));
  const restored = readPending();
  assert.deepEqual(restored,pending);
  assert.deepEqual(await managed(restored.path,restored.body,restored.key),{id:1});
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(calls[0].options.headers['X-My-Harness'],'1');
  assert.equal(calls[0].options.headers['Idempotency-Key'],pending.key);
});

test('conflicts preserve code and diagnostic; all managed mutations carry CSRF header', async () => {
  globalThis.fetch = async (path, options) => {
    assert.equal(options.headers['X-My-Harness'],'1');
    assert.equal(JSON.parse(options.body).expected_version,8);
    return Response.json({detail:{code:'conflict',diagnostic:'Version changed'}},{status:409});
  };
  await assert.rejects(managedApi.confirm(1,{expected_version:8,owner_token:'token',reason:'stopped'}),
    e => e instanceof ManagedError && e.status === 409 && e.message.includes('conflict: Version changed') && e.diagnostic === 'Version changed');
});

test('a problem without a diagnostic keeps status and code only; the interface adds its own sentence', async () => {
  globalThis.fetch = async () => new Response('gateway', { status: 502 });
  await assert.rejects(managed('/supervisor'), e => e instanceof ManagedError && e.status === 502
    && e.message === '502 · request_failed' && e.code === undefined && e.diagnostic === undefined);
});

test('H0/H1 mutations carry the local CSRF header; reads do not need it', async () => {
  const { api } = await import('../src/api.ts');
  const calls = [];
  globalThis.fetch = async (path, options) => { calls.push({path, options}); return Response.json({}); };
  await api.list();
  await api.create({title: 'synthetic'});
  assert.equal(calls[0].options, undefined);
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(calls[1].options.headers['X-My-Harness'], '1');
  assert.equal(calls[1].options.headers['Content-Type'], 'application/json');
});

test('401 notifies the session gate once and never retries a mutation or changes its envelope', async () => {
  const events = [];
  globalThis.window = {dispatchEvent: event => events.push(event.type)};
  const pending = jobRequest('/projects/demo/runs', {task_id:'T',phase_id:'P',text:'synthetic'});
  savePending(pending);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({detail:{code:'session_required',diagnostic:'Expired'}}, {status:401}); };
  try {
    await assert.rejects(managed(pending.path, pending.body, pending.key), e => e instanceof ManagedError && e.status === 401);
    assert.equal(calls, 1);
    assert.deepEqual(readPending(), pending);
    assert.deepEqual(events, ['harness-session-required']);
    const {api} = await import('../src/api.ts');
    await assert.rejects(api.create({title:'synthetic'}));
    assert.equal(calls, 2);
    assert.equal(events.length, 2);
  } finally { delete globalThis.window; }
});

test('lost acknowledgement then expired session keeps one identity until explicit authenticated resend', async () => {
  const pending = jobRequest('/runs/r/actions', {action:'commit', expected_version:17});
  savePending(pending);
  const calls = [];
  const jobs = new Map();
  let authenticated = true;
  globalThis.fetch = async (path, options) => {
    calls.push({path, options});
    if (!authenticated) return Response.json({detail:{code:'session_required'}}, {status:401});
    const key = options.headers['Idempotency-Key'];
    if (!jobs.has(key)) {
      jobs.set(key, {id:42}); // server admitted the action; its response was lost
      throw new TypeError('Lost acknowledgement');
    }
    return Response.json(jobs.get(key));
  };
  await assert.rejects(managed(pending.path, pending.body, pending.key));
  authenticated = false;
  const restored = readPending();
  await assert.rejects(managed(restored.path, restored.body, restored.key), e => e.status === 401);
  authenticated = true; // logging in does not call managed or discard pending state
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 2);
  assert.deepEqual(readPending(), pending);
  assert.deepEqual(await managed(restored.path, restored.body, restored.key), {id:42});
  savePending(); // explicit resend acknowledged
  assert.equal(readPending(), undefined);
  assert.equal(jobs.size, 1);
  assert.deepEqual(calls[0], calls[1]);
  assert.deepEqual(calls[1], calls[2]);
});

test('conversation creation reuses its key until acknowledged, then starts another', async () => {
  const keys = [];
  let fail = true;
  globalThis.fetch = async (path, options) => {
    keys.push(options.headers['Idempotency-Key']);
    if (fail) { fail = false; throw new TypeError('Failed to fetch'); }
    return Response.json({ id: 'c1' }, { status: 201 });
  };
  const body = { title: 'Chat', phase_id: null, task_run_id: null };
  await assert.rejects(createOnce('/projects/demo/conversations', body));
  assert.deepEqual(await createOnce('/projects/demo/conversations', body), { id: 'c1' });
  assert.equal(keys[0], keys[1]); // retry after losing the response: same key
  await createOnce('/projects/demo/conversations', body);
  assert.notEqual(keys[2], keys[1]); // confirmed response: another conversation
  fail = true;
  await assert.rejects(createOnce('/projects/demo/conversations', body));
  await createOnce('/projects/demo/conversations', { ...body, title: 'Otra' });
  assert.notEqual(keys[4], keys[3]); // another body, another key
});

test('a definitive rejection forgets the creation key', async () => {
  const keys = [];
  globalThis.fetch = async (path, options) => {
    keys.push(options.headers['Idempotency-Key']);
    return keys.length === 1 ? Response.json({ detail: { code: 'conflict', diagnostic: 'x' } }, { status: 409 })
      : Response.json({ id: 'p1' }, { status: 201 });
  };
  const body = { kind: 'phase_planning', title: 'Plan', brief: null, phase_id: 'p' };
  await assert.rejects(createOnce('/projects/demo/planning', body), /409/);
  await createOnce('/projects/demo/planning', body);
  assert.notEqual(keys[0], keys[1]);
});

test('folder/project confirmation survives reload and a lost acknowledgement with its exact envelope', async () => {
  const { confirmOnce, readConfirmation } = await import('../src/managed-api.ts');
  const path = '/project-creations/confirm';
  const body = { change: { project_id: 'synthetic', directory_name: 'synthetic', root_version: 4 },
    preview_sha256: 'a'.repeat(64), trust_root: '/synthetic/parent/synthetic' };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) throw new TypeError('Lost reply');
    return Response.json({ id: 'operation', status: 'REGISTERED' });
  };
  await assert.rejects(confirmOnce(path, body));
  const pending = readConfirmation();
  assert.deepEqual(pending.body, body);
  await assert.rejects(confirmOnce(path, { ...body, trust_root: '/another' }),
    e => e instanceof LocalizedError && e.key === 'error.confirmation_pending');
  assert.equal(calls.length, 1);
  assert.deepEqual(await confirmOnce(pending.path, pending.body), { id: 'operation', status: 'REGISTERED' });
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(readConfirmation(), undefined);
});

test('confirmation preserves expired-session envelope and forgets a definitive conflict', async () => {
  const { confirmOnce, readConfirmation } = await import('../src/managed-api.ts');
  globalThis.fetch = async () => Response.json({ detail: { code: 'session_required' } }, { status: 401 });
  await assert.rejects(confirmOnce('/project-creation-root/apply', { preview_sha256: 'x' }));
  const pending = readConfirmation();
  globalThis.fetch = async () => Response.json({ detail: { code: 'stale_version' } }, { status: 409 });
  await assert.rejects(confirmOnce(pending.path, pending.body));
  assert.equal(readConfirmation(), undefined);
});
