import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ProjectWorkspace } = await import('../src/workspace.tsx');
const { ProjectProfile, ProfileProposal } = await import('../src/pages/ProjectProfile.tsx');
const { TaskForm } = await import('../src/pages/shared.tsx');
const { configurationChange, preparationChange } = await import('../src/project-profile.ts');
delete globalThis.__tsxHookHarness;
const hash = c => c.repeat(64);
const form = () => ({ format: 'project-config-1', profile_name: 'own-go', project: { id: 'own', root: '/synthetic/own' },
  profile: { executor_instructions: 'Use Go', validations: [{ argv: ['go', 'test', './...'] }] },
  commands: { executables: { go: '/synthetic/go' }, environment: { HOME: '/synthetic/own/.prepare/home', TMPDIR: '/synthetic/own/.prepare/tmp' } } });
const profile = () => ({ candidate: { name: 'own-go', profile: form().profile, tools: [{ name: 'go', requirement: 'Go synthetic' }] } });
function environment(language = 'en') {
  const driver = hookHost(), storage = new Map(), requests = [], timers = [], results = new Map();
  const originals = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const env = { ...driver, storage, requests, timers, catalog: language === 'en' ? en : es, conflict: false, lose: false,
    state: { scope: 'project:own', version: 0, status: 'UNCONFIGURED', saved: null, active: null, pending: null,
      working_sha256: null, actual_sha256: null, configuration_state: 'DOCUMENTS_COMMITTED', text: null,
      form: form(), profile: profile(), proposal_id: 'profile', proposal_sha256: hash('a') } };
  globalThis.setTimeout = callback => { timers.push(callback); return timers.length; };
  globalThis.clearTimeout = () => {};
  globalThis.document = { documentElement: {}, getElementById: () => ({ focus() {} }) };
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
  globalThis.window = { location: { pathname: '/projects/own', search: '' }, dispatchEvent() {}, history: { pushState() {} } };
  globalThis.fetch = async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : undefined;
    requests.push({ path, body, options });
    if (path === '/api/managed/projects/own') return Response.json({ versions: { local_config: 'local-config-9', ...(env.state.configuration_state === 'ACTIVE' ? { project_configuration: 'project-config-1' } : {}) }, configuration_state: env.state.configuration_state });
    if (path.endsWith('/task-sources')) return Response.json({ items: [], diagnostics: [] });
    if (path === '/api/managed/projects/own/configuration') return Response.json(env.state);
    if (path === '/api/managed/registry') return Response.json({ compositions: [] });
    if (path.endsWith('/preparation')) return Response.json({ available: false });
    if (path.endsWith('/form')) return Response.json({ form: body.form ?? JSON.parse(body.text), text: body.text ?? JSON.stringify(body.form) });
    if (path.endsWith('/preview')) {
      if (env.conflict) return Response.json({ detail: { code: 'stale_configuration_preview' } }, { status: 409 });
      return Response.json({ sha256: hash('b'), changes: [{ diff: '+ synthetic profile' }], ready: true, preview_sha256: hash('b'), blockers: [], expected_version: 1 });
    }
    const key = options?.headers['Idempotency-Key'];
    assert.ok(key);
    if (results.has(key)) return Response.json(results.get(key));
    const result = { id: 'operation' };
    results.set(key, result);
    if (path.endsWith('/save')) env.state = { ...env.state, version: 1, saved: { revision: 1, sha256: hash('c') }, working_sha256: hash('c'), form: JSON.parse(body.text) };
    if (path.endsWith('/activate')) env.state = { ...env.state, version: 2, active: env.state.saved, configuration_state: 'ACTIVE' };
    if (env.lose) { env.lose = false; throw new TypeError('Synthetic lost reply'); }
    return Response.json(result);
  };
  env.tree = component => el(I18nProvider, null, el(ProjectWorkspace, { project: 'own' }, component ?? el(ProjectProfile)));
  env.button = key => { const button = env.host.elements.find(e => e.type === 'button' && e.props.children === env.catalog[key]); assert.ok(button, key); return button.props; };
  env.click = key => { const button = env.button(key); assert.ok(!button.disabled, key); button.onClick(); };
  env.reason = value => {
    const label = env.host.elements.find(e => e.type === 'label' && Array.isArray(e.props.children) && e.props.children[0] === env.catalog['docs.review.reason']);
    assert.ok(label); label.props.children[1].props.onChange({ target: { value } });
  };
  env.tick = () => {
    const label = env.host.elements.find(e => e.type === 'label' && Array.isArray(e.props.children) && e.props.children.at(-1) === env.catalog['profile.confirm_exact']);
    assert.ok(label); label.props.children[0].props.onChange({ target: { checked: true } });
  };
  env.close = () => { driver.close(); Object.assign(globalThis, originals); for (const key of ['document', 'window', 'sessionStorage', 'localStorage']) delete globalThis[key]; };
  return env;
}

for (const language of ['en', 'es']) test(`own profile save and activation need separate exact confirmations (${language})`, async () => {
  const env = environment(language), tree = env.tree();
  try {
    let html = await env.render(tree);
    assert.ok(html.includes(env.catalog['profile.configuration']));
    assert.ok(env.requests.every(r => r.body === undefined));
    env.reason('Explicit review'); await env.render(tree); env.click('profile.review_save'); html = await env.render(tree);
    assert.match(html, /synthetic profile/); assert.equal(env.button('registry.save').disabled, true);
    env.tick(); await env.render(tree); env.click('registry.save'); await env.render(tree);
    const saved = env.requests.find(r => r.path.endsWith('/save'));
    assert.equal(saved.body.preview_sha256, hash('b')); assert.equal(saved.body.expected_version, 0);
    assert.equal(env.state.active, null);
    env.click('profile.review_activation'); await env.render(tree); assert.equal(env.button('profile.activate').disabled, true);
    env.tick(); await env.render(tree); env.click('profile.activate'); await env.render(tree);
    assert.equal(env.requests.find(r => r.path.endsWith('/activate')).body.sha256, hash('c'));
    assert.ok(env.requests.every(r => !r.path.endsWith('/preparation/confirm') && !r.path.endsWith('/runs')));
  } finally { env.close(); }
});

test('lost save response retains one exact key and explicit replay after reload', async () => {
  const env = environment(), tree = env.tree();
  try {
    await env.render(tree); env.reason('Save exact candidate'); await env.render(tree); env.click('profile.review_save'); await env.render(tree);
    env.tick(); await env.render(tree); env.lose = true; env.click('registry.save'); let html = await env.render(tree);
    assert.ok(html.includes(en['profile.pending']));
    const envelope = JSON.parse(env.storage.get('harness-confirmation-v1'));
    assert.ok(envelope.key && envelope.body.text);
    assert.equal(env.requests.filter(r => r.path.endsWith('/save')).length, 1);
    env.click('workspace.pending.repeat'); await env.render(tree);
    const saved = env.requests.filter(r => r.path.endsWith('/save'));
    assert.equal(saved.length, 2); assert.deepEqual(saved[0], saved[1]);
    assert.equal(env.storage.has('harness-confirmation-v1'), false);
  } finally { env.close(); }
});

test('conflict preserves editable candidate and never sends save or activation', async () => {
  const env = environment(), tree = env.tree();
  try {
    await env.render(tree); env.reason('Stale candidate'); await env.render(tree); env.conflict = true; env.click('profile.review_save'); await env.render(tree);
    assert.equal(JSON.parse(env.storage.get('harness-project-configuration:own')).commands.executables.go, '/synthetic/go');
    assert.ok(!env.requests.some(r => /\/(save|activate)$/.test(r.path)));
  } finally { env.close(); }
});

test('profile proposal adoption never writes configuration or runs preparation', async () => {
  const env = environment(), proposal = { id: 'proposal', content: JSON.stringify(profile()), proposal_sha256: hash('a') };
  const tree = env.tree(el(ProfileProposal, { proposal, conversation: { version: 1 }, base: '/projects/own/planning/conversation' }));
  try {
    await env.render(tree); env.reason('Reviewed proposal'); await env.render(tree); env.click('profile.review_adoption'); await env.render(tree);
    env.tick(); await env.render(tree); env.click('profile.adopt'); await env.render(tree);
    const adopted = env.requests.find(r => r.path.endsWith('/profile/confirm'));
    assert.equal(adopted.body.proposal_id, 'proposal'); assert.equal(adopted.body.preview_sha256, hash('b'));
    assert.ok(!env.requests.some(r => /\/(save|activate|preparation\/confirm)$/.test(r.path)));
  } finally { env.close(); }
});

test('configuration and preparation envelopes bind the exact saved version and proposal', () => {
  const state = { version: 7, working_sha256: hash('d'), active: { sha256: hash('e') }, saved: { revision: 4, sha256: hash('f') }, proposal_id: 'p', proposal_sha256: hash('a') };
  assert.equal(configurationChange(state, 'candidate', 'review').base_sha256, hash('d'));
  assert.deepEqual(preparationChange(state, 2, 'offline', { id: 'failed', step: 3 }), {
    contract: 'project-profile-preparation-1', expected_version: 2, mode: 'offline', configuration_revision: 4,
    configuration_sha256: hash('f'), proposal_id: 'p', proposal_sha256: hash('a'), previous_id: 'failed', retry_step: 3,
  });
});

test('manual TOML and its original CAS survive rejection without replacing the form base', async () => {
  const env = environment(), tree = env.tree();
  try {
    await env.render(tree); env.click('profile.toml'); await env.render(tree);
    const edited = JSON.stringify({ ...env.state.form, commands: { ...env.state.form.commands, executables: { go: '/different/synthetic-go' } } });
    const area = env.host.elements.find(e => e.type === 'textarea' && e.props.id === 'project-profile-toml');
    assert.ok(area); area.props.onChange({ target: { value: edited } });
    await env.render(tree); env.reason('Review manual candidate'); await env.render(tree); env.conflict = true;
    env.click('profile.review_save'); await env.render(tree);
    assert.equal(JSON.parse(env.storage.get('harness-project-configuration:own:text')), edited);
    assert.equal(JSON.parse(env.storage.get('harness-project-configuration:own:base')).version, 0);
    assert.equal(JSON.parse(env.storage.get('harness-project-configuration:own')).commands.executables.go, '/synthetic/go');
    assert.ok(!env.requests.some(r => r.path.endsWith('/save')));
  } finally { env.close(); }
});


for (const stage of ['READY_TO_ACTIVATE', 'ACTIVE']) test(`task page admission follows active configuration (${stage})`, async () => {
  const env = environment();
  env.state.configuration_state = stage;
  const tree = env.tree(el(TaskForm, { task: 'P001-T001', phase: 'P001' }));
  try {
    await env.render(tree);
    const label = env.host.elements.find(e => e.type === 'label' && Array.isArray(e.props.children) && e.props.children[0] === en['task_form.contract']);
    label.props.children[1].props.onChange({ target: { value: 'Synthetic task body' } });
    await env.render(tree);
    assert.equal(env.button('task_form.submit').disabled, stage !== 'ACTIVE');
    assert.ok(env.requests.every(r => r.body === undefined));
  } finally { env.close(); }
});


for (const language of ['en', 'es']) test(`an active own profile retains its manual editor and optional assistance (${language})`, async () => {
  const env = environment(language);
  env.state = { ...env.state, version: 2, configuration_state: 'ACTIVE', active: { revision: 1, sha256: hash('a') }, saved: { revision: 1, sha256: hash('a') } };
  try {
    const html = await env.render(env.tree());
    assert.ok(html.includes(env.catalog['profile.toml']));
    assert.ok(html.includes(env.catalog['assistance.edit_base']));
    assert.ok(html.includes(env.catalog['assistance.title']));
    assert.ok(env.requests.every(r => r.body === undefined));
  } finally { env.close(); }
});
