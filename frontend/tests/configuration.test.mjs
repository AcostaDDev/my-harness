import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as el } from 'react';
import { hookHost } from './helpers/render-hooks.mjs';
import en from '../src/i18n/en.json' with { type: 'json' };
import es from '../src/i18n/es.json' with { type: 'json' };

globalThis.__tsxHookHarness = {};
const { I18nProvider } = await import('../src/Language.tsx');
const { ServiceModeContext } = await import('../src/ServiceMode.tsx');
const { ConfigurationPage } = await import('../src/pages/Configuration.tsx');
const { Page } = await import('../src/Page.tsx');
const { initialDraft, change, errors } = await import('../src/configuration.ts');
const { parse, href, trail } = await import('../src/router.ts');
delete globalThis.__tsxHookHarness;

const sha = letter => letter.repeat(64);
const base = () => ({ mode: 'UNCONFIGURED', status: 'UNCONFIGURED', version: 0, legacy: false,
  saved: null, active: null, pending: null, text: null, form: null, actual_sha256: null, working_sha256: null,
  blockers: ['unconfigured'], pending_activation_id: null, recovery_operations: [] });
const form = () => ({ format: 'local-config-9', service: { state_dir: '/synthetic/state', supervisor: false },
  git: { executable: '/synthetic/git', author_name: 'Synthetic User', author_email: 'user@example.invalid' },
  agents: { reviewer: { provider: 'codex', model: 'explicit-model', effort: 'medium', timeout_seconds: 300, environment: { USER: 'synthetic', PATH: '/synthetic/bin' } },
    executor: { provider: 'claude', timeout_seconds: 300, environment: { USER: 'synthetic', PATH: '/synthetic/bin', CUSTOM: 'preserve-me' }, tools: ['Read'] } },
  registration: { roots: [], bootstrap_enabled: false } });
const draft = state => ({ ...initialDraft(state), form: form(), reason: 'Synthetic explicit setup' });
const supervisor = mode => ({ configuration_mode: mode, read_only_archive: mode === 'READ_ONLY_ARCHIVE', enabled: false, alive: false,
  last_error: null, ports_configured: false, commit_writer_configured: false });

function environment(language = 'en', initial = base(), savedDraft = draft(initial), storage = new Map()) {
  const driver = hookHost(), requests = [], navigation = [], timers = [], completed = new Map();
  const originals = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const env = { ...driver, state: structuredClone(initial), requests, storage, navigation, timers,
    failSave: false, conflict: false, failRead: false, catalog: language === 'es' ? es : en };
  if (savedDraft) storage.set('harness-configuration-draft-v1', JSON.stringify(savedDraft));
  globalThis.setTimeout = callback => { timers.push(callback); return timers.length; };
  globalThis.clearTimeout = () => {};
  globalThis.document = { documentElement: {}, getElementById: () => ({ focus() {} }) };
  globalThis.localStorage = { getItem: () => language };
  globalThis.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
  globalThis.window = { location: { pathname: '/' }, history: {
    replaceState: (_, __, path) => navigation.push(path), pushState: (_, __, path) => navigation.push(path),
  } };
  globalThis.fetch = async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : undefined;
    requests.push({ path, body, options });
    if (path === '/api/managed/configuration') return env.failRead ? Response.json({ detail: { code: 'unavailable' } }, { status: 503 }) : Response.json(env.state);
    if (path.endsWith('/assistance/preview')) return Response.json({ sha256: sha('f'), selection: { model: 'explicit-model', effort: 'medium' }, configuration_write: false });
    if (path.endsWith('/assistance/confirm')) {
      const key = options.headers['Idempotency-Key'];
      if (completed.has(key)) return Response.json(completed.get(key));
      const result = { id: 'assistance', status: 'APPLIED', result: { authority_changed: false,
        proposal: { text: JSON.stringify({ ...form(), git: { ...form().git, author_name: 'Proposed synthetic name' } }), rationale: 'Synthetic explanation', questions: [] } } };
      completed.set(key, result);
      if (env.failAssistance) { env.failAssistance = false; throw new TypeError('Synthetic lost response'); }
      return Response.json(result);
    }
    if (path.endsWith('/detect')) return Response.json({ candidates: { git: '/detected/git', codex: '/detected/codex', claude: '/detected/claude' },
      user: 'detected-user', state_dir: '/synthetic/state', configuration_dir: '/synthetic/configuration', providers: {} });
    if (path.endsWith('/check-clients')) return Response.json({ reports: { reviewer: { available: true }, executor: { available: true } }, inference_performed: false, internal_effects_verified: false });
    if (path.endsWith('/form')) {
      if (env.rejectConversion) return Response.json({ detail: { code: 'configuration_invalid', diagnostic: 'Synthetic invalid TOML' } }, { status: 422 });
      const parsed = body.form ?? JSON.parse(body.text);
      return Response.json({ text: body.text ?? JSON.stringify(parsed), form: parsed });
    }
    if (path === '/api/managed/configuration/operations/interrupted') return Response.json({ id: 'interrupted', kind: 'SAVE' });
    if (path.endsWith('/recovery/preview')) return Response.json({ operation_id: 'interrupted', sha256: sha('e'), observed: [{ path: 'global.toml', sha256: sha('a') }] });
    if (path.endsWith('/activation/preview')) {
      if (env.refuseActivation) return Response.json({ detail: { code: 'live_configuration_refused', diagnostic: 'Synthetic refusal',
        details: [{ project: null, role: 'executor', setting: 'agents.executor', code: 'discovery_path', diagnostic: 'Configure an explicit PATH' }] } }, { status: 409 });
      return Response.json({ kind: 'ACTIVATE', sha256: sha('d'), references: body.references, impact: ['global'], ...(env.activationPreview ?? { restart_required: true }) });
    }
    if (path.endsWith('/import/preview')) return Response.json({ kind: 'SAVE', sha256: sha('b'), impact: ['global', 'project:own'],
      changes: [{ scope: 'global', text: JSON.stringify(form()), diff: '+converted global', status: 'VALIDATED' },
        { scope: 'project:own', diff: '+draft project', status: 'DRAFT' }], legacy_import: { format: 'local-config-8' } });
    if (path.endsWith('/preview')) {
      if (env.conflict) return Response.json({ detail: { code: 'stale_configuration_preview' } }, { status: 409 });
      return Response.json({ kind: 'SAVE', sha256: sha('b'), impact: ['global'], changes: [{ text: body.text ?? JSON.stringify(body.form), diff: '+synthetic candidate', status: body.validated ? 'VALIDATED' : 'DRAFT' }] });
    }
    const key = options?.headers?.['Idempotency-Key'];
    assert.ok(key, 'Every durable mutation keeps an idempotency key');
    if (completed.has(key)) return Response.json(completed.get(key));
    if (path.endsWith('/import/save')) {
      env.state.version = 1; env.state.saved = { scope: 'global', revision: 1, sha256: sha('c'), status: 'VALIDATED' };
      env.state.form = form(); env.state.text = JSON.stringify(form()); env.state.actual_sha256 = sha('c');
      env.state.imported_projects = ['own'];
      const result = { id: 'imported', status: 'SAVED' }; completed.set(key, result);
      return Response.json(result);
    }
    if (path.endsWith('/save')) {
      if (env.conflict) return Response.json({ detail: { code: 'stale_configuration_preview' } }, { status: 409 });
      env.state.version++;
      env.state.saved = { scope: 'global', revision: env.state.version, sha256: sha('c'), status: body.validated ? 'VALIDATED' : 'DRAFT' };
      env.state.text = body.text ?? JSON.stringify(body.form); env.state.form = body.form ?? JSON.parse(body.text);
      env.state.actual_sha256 = sha('c');
      const result = { id: 'saved-operation', status: 'SAVED' }; completed.set(key, result);
      if (env.failSave) { env.failSave = false; throw new TypeError('Synthetic response lost'); }
      return Response.json(result);
    }
    if (path.endsWith('/activate')) {
      if (env.liveWaiting) {
        env.state.pending = env.state.saved; env.state.pending_activation_id = 'pending-activation'; env.state.mode = 'APPLY_PENDING'; env.state.version++;
        env.state.live_activation = { activation_id: 'pending-activation', state: 'APPLY_PENDING', waiting: env.liveWaiting, restart_fields: [], code: null, details: [] };
        const result = { id: 'activation', status: 'APPLIED', result: { state: 'APPLY_PENDING' } }; completed.set(key, result); return Response.json(result);
      }
      env.state.pending = env.state.saved; env.state.pending_activation_id = 'pending-activation'; env.state.mode = 'RESTART_REQUIRED'; env.state.version++;
      const result = { id: 'activation', status: 'RESTART_REQUIRED' }; completed.set(key, result); return Response.json(result);
    }
    if (path.endsWith('/cancel')) {
      env.state.pending = null; env.state.pending_activation_id = null; env.state.mode = 'UNCONFIGURED'; env.state.version++;
      return Response.json({ id: 'cancelled', status: 'CANCELLED' });
    }
    if (path.endsWith('/recovery/confirm')) {
      env.state.recovery_operations = []; env.state.mode = 'UNCONFIGURED';
      return Response.json({ id: 'interrupted', status: 'SAVED' });
    }
    assert.fail(`Unexpected request ${path}`);
  };
  env.tree = component => el(I18nProvider, null, el(ServiceModeContext.Provider, { value: supervisor(env.state.mode) }, component ?? el(ConfigurationPage)));
  env.button = key => {
    const element = env.host.elements.find(item => item.type === 'button' && item.props.children === env.catalog[key]);
    assert.ok(element, `Button ${key} must be visible`); return element.props;
  };
  env.click = key => { const button = env.button(key); assert.ok(!button.disabled, `${key} enabled`); button.onClick(); };
  env.input = (id, value) => {
    const element = env.host.elements.find(item => ['input', 'textarea', 'select'].includes(item.type) && item.props.id === id);
    assert.ok(element, id); element.props.onChange({ target: { value } });
  };
  env.tick = (key, checked = true) => {
    const label = env.host.elements.find(item => item.type === 'label' && Array.isArray(item.props.children) && item.props.children.at(-1) === env.catalog[key]);
    assert.ok(label, key); label.props.children[0].props.onChange({ target: { checked } });
  };
  env.preview = () => env.host.elements.find(item => item.type === 'form').props.onSubmit({ preventDefault() {} });
  env.close = () => { driver.close(); Object.assign(globalThis, originals); for (const key of ['document', 'window', 'sessionStorage', 'localStorage']) delete globalThis[key]; };
  return env;
}

for (const language of ['en', 'es']) {
  test(`global setup previews, saves and activates separate exact versions (${language})`, async () => {
    const env = environment(language), tree = env.tree();
    try {
      let html = await env.render(tree);
      assert.match(html, /explicit-model/); assert.ok(html.includes(env.catalog['configuration.mode.unconfigured']));
      assert.ok(env.requests.every(request => request.body === undefined), 'Mount is passive');
      env.preview(); html = await env.render(tree); assert.match(html, /synthetic candidate/);
      assert.equal(env.button('configuration.save').disabled, true);
      env.tick('configuration.confirm_save'); await env.render(tree); env.click('configuration.save'); await env.render(tree);
      const saved = env.requests.find(request => request.path.endsWith('/save'));
      assert.equal(saved.body.preview_sha256, sha('b')); assert.equal(saved.body.expected_version, 0);
      assert.equal(saved.body.form.agents.executor.environment.CUSTOM, 'preserve-me');
      assert.equal(env.state.active, null); assert.equal(env.state.pending, null);
      assert.equal(env.requests.filter(request => request.path.endsWith('/activate')).length, 0);
      env.click('configuration.activation_preview'); await env.render(tree);
      assert.equal(env.button('configuration.activate').disabled, true);
      env.tick('configuration.confirm_activation'); await env.render(tree); env.click('configuration.activate'); html = await env.render(tree);
      const activation = env.requests.find(request => request.path.endsWith('/activate'));
      assert.equal(activation.body.preview_sha256, sha('d')); assert.equal(activation.body.references[0].sha256, sha('c'));
      assert.ok(html.includes(env.catalog['configuration.mode.restart'])); assert.equal(env.state.active, null);
      assert.ok(env.requests.every(request => !request.path.endsWith('/restart')));
      env.tick('configuration.confirm_cancel'); await env.render(tree); env.click('configuration.cancel'); await env.render(tree);
      assert.equal(env.requests.find(request => request.path.endsWith('/cancel')).body.activation_id, 'pending-activation');
    } finally { env.close(); }
  });

  test(`initial fields show localized inline errors without sending a candidate (${language})`, async () => {
    const env = environment(language, base(), null), tree = env.tree();
    try {
      await env.render(tree); env.preview(); const html = await env.render(tree);
      assert.match(html, /aria-invalid="true"/); assert.ok(html.includes(env.catalog['configuration.required']));
      assert.ok(env.requests.every(request => request.body === undefined));
    } finally { env.close(); }
  });
}

test('suggestions are explicit, preserve unrelated environment and preflight is a separate action', async () => {
  const env = environment(), tree = env.tree();
  const before = JSON.parse(env.storage.get('harness-configuration-draft-v1'));
  before.form.agents.executor.executable = ['/synthetic/claude', '--synthetic-argument'];
  env.storage.set('harness-configuration-draft-v1', JSON.stringify(before));
  try {
    await env.render(tree); env.click('configuration.detect'); await env.render(tree);
    assert.equal(JSON.parse(env.storage.get('harness-configuration-draft-v1')).form.git.executable, '/synthetic/git');
    env.click('configuration.use_suggestions'); await env.render(tree);
    const saved = JSON.parse(env.storage.get('harness-configuration-draft-v1'));
    assert.equal(saved.form.git.executable, '/detected/git'); assert.equal(saved.form.agents.executor.environment.CUSTOM, 'preserve-me');
    assert.deepEqual(saved.form.agents.executor.executable, ['/detected/claude', '--synthetic-argument']);
    env.click('configuration.check_clients'); const html = await env.render(tree);
    assert.match(html, /No inference was performed/);
    assert.equal(env.requests.filter(request => request.path.endsWith('/check-clients')).length, 1);
    assert.ok(!env.requests.some(request => request.path.endsWith('/save')));
  } finally { env.close(); }
});

test('TOML switching keeps advanced fields and invalidates an earlier confirmation', async () => {
  const env = environment(), tree = env.tree();
  try {
    await env.render(tree); env.preview(); await env.render(tree); env.tick('configuration.confirm_save'); await env.render(tree);
    env.click('configuration.toml'); let html = await env.render(tree);
    assert.match(html, /preserve-me/); assert.ok(!env.host.elements.some(item => item.type === 'button' && item.props.children === en['configuration.save']));
    const text = JSON.stringify({ ...form(), service: { state_dir: '/synthetic/state', supervisor: true } });
    env.input('configuration-text', text); await env.render(tree); env.click('configuration.form'); html = await env.render(tree);
    const local = JSON.parse(env.storage.get('harness-configuration-draft-v1'));
    assert.equal(local.form.service.supervisor, true); assert.equal(local.form.agents.executor.environment.CUSTOM, 'preserve-me');
    assert.ok(env.requests.every(request => !request.path.endsWith('/save')));
    env.preview(); await env.render(tree); assert.equal(env.button('configuration.save').disabled, true);
  } finally { env.close(); }
});

test('invalid manual TOML remains editable after server rejection', async () => {
  const env = environment(), tree = env.tree();
  try {
    await env.render(tree); env.click('configuration.toml'); await env.render(tree);
    env.input('configuration-text', 'invalid = ['); await env.render(tree); env.rejectConversion = true;
    env.click('configuration.form'); const html = await env.render(tree);
    assert.match(html, /Synthetic invalid TOML/); assert.match(html, /invalid = \[/);
    assert.equal(JSON.parse(env.storage.get('harness-configuration-draft-v1')).text, 'invalid = [');
    assert.ok(!env.requests.some(request => request.path.endsWith('/save')));
  } finally { env.close(); }
});

test('invalid startup source can be replaced by a reviewed validated version before restart', async () => {
  const state = { ...base(), mode: 'INVALID' }, env = environment('en', state), tree = env.tree();
  try {
    await env.render(tree); env.preview(); await env.render(tree); env.tick('configuration.confirm_save'); await env.render(tree);
    env.click('configuration.save'); await env.render(tree);
    assert.equal(env.state.mode, 'INVALID', 'Startup diagnostic stays visible until restart');
    assert.equal(env.button('configuration.activation_preview').disabled, false);
    env.click('configuration.activation_preview'); await env.render(tree);
    assert.ok(env.requests.some(request => request.path.endsWith('/activation/preview')));
  } finally { env.close(); }
});

test('incomplete drafts save without activation and external changes require an explicit import choice', async () => {
  const state = { ...base(), status: 'EXTERNAL_CHANGE', mode: 'INVALID', actual_sha256: sha('f') };
  const local = { ...draft(state), validated: false, form: { format: 'local-config-9' } };
  const env = environment('en', state, local), tree = env.tree();
  try {
    await env.render(tree); env.tick('configuration.import_external'); await env.render(tree);
    env.preview(); await env.render(tree); env.tick('configuration.confirm_save'); await env.render(tree);
    env.click('configuration.save'); await env.render(tree);
    const saved = env.requests.find(request => request.path.endsWith('/save'));
    assert.equal(saved.body.validated, false); assert.equal(saved.body.import_external, true);
    assert.equal(saved.body.base_sha256, sha('f')); assert.equal(env.button('configuration.activation_preview').disabled, true);
  } finally { env.close(); }
});

test('both global URLs mount the editor while archive URLs remain blocked', async () => {
  for (const path of ['/setup', '/settings/configuration']) {
    const env = environment(), tree = env.tree(el(Page, { route: parse(path) }));
    try {
      const html = await env.render(tree); assert.match(html, /explicit-model/);
      assert.equal(env.requests.length, 1); assert.equal(env.requests[0].path, '/api/managed/configuration');
    } finally { env.close(); }
    const archive = environment('en', { ...base(), mode: 'READ_ONLY_ARCHIVE' });
    try {
      const html = await archive.render(archive.tree(el(Page, { route: parse(path) })));
      assert.match(html, /unavailable in a read-only copy/); assert.deepEqual(archive.requests, []);
    } finally { archive.close(); }
  }
});

test('stale save keeps candidate and CAS base until an explicit rebase and new preview', async () => {
  const env = environment(), tree = env.tree();
  try {
    await env.render(tree); env.preview(); await env.render(tree); env.tick('configuration.confirm_save'); await env.render(tree);
    env.state.version = 3; env.state.actual_sha256 = sha('f'); env.conflict = true;
    env.click('configuration.save'); let html = await env.render(tree);
    assert.match(html, /candidate is preserved/); assert.match(html, /explicit-model/);
    assert.equal(JSON.parse(env.storage.get('harness-configuration-draft-v1')).base.version, 0);
    assert.equal(env.storage.has('harness-configuration-action-v1'), false);
    env.click('configuration.rebase'); await env.render(tree); env.conflict = false; env.preview(); await env.render(tree);
    const preview = env.requests.filter(request => request.path.endsWith('/preview')).at(-1);
    assert.equal(preview.body.expected_version, 3); assert.equal(preview.body.base_sha256, sha('f'));
    assert.equal(env.button('configuration.save').disabled, true);
  } finally { env.close(); }
});

test('lost save acknowledgment survives reload without automatic replay and retries identical bytes/key', async () => {
  const env = environment(), tree = env.tree(); let pending, saved;
  try {
    await env.render(tree); env.preview(); await env.render(tree); env.tick('configuration.confirm_save'); await env.render(tree);
    env.failSave = true; env.click('configuration.save'); await env.render(tree);
    saved = env.requests.find(request => request.path.endsWith('/save'));
    pending = new Map(env.storage);
    assert.ok(pending.has('harness-configuration-action-v1'));
  } finally { env.close(); }
  const reloaded = environment('en', base(), null, pending), next = reloaded.tree();
  try {
    await reloaded.render(next);
    assert.ok(reloaded.requests.every(request => request.body === undefined));
    reloaded.click('configuration.retry'); await reloaded.render(next);
    const retry = reloaded.requests.find(request => request.path.endsWith('/save'));
    assert.deepEqual(retry.body, saved.body); assert.deepEqual(retry.options.headers, saved.options.headers);
    assert.equal(reloaded.storage.has('harness-configuration-action-v1'), false);
  } finally { reloaded.close(); }
});

test('recovery requires inspection and a separate stopped-writers declaration', async () => {
  const state = { ...base(), mode: 'RECOVERY_REQUIRED', recovery_operations: ['interrupted'] };
  const env = environment('es', state), tree = env.tree();
  try {
    await env.render(tree);
    env.host.elements.find(item => item.type === 'button' && Array.isArray(item.props.children) && item.props.children[0] === es['configuration.recovery_preview']).props.onClick();
    await env.render(tree); assert.equal(env.button('configuration.recover').disabled, true);
    env.tick('configuration.writers_stopped'); await env.render(tree); env.click('configuration.recover'); await env.render(tree);
    const request = env.requests.find(request => request.path.endsWith('/recovery/confirm'));
    assert.deepEqual(request.body, { preview_sha256: sha('e'), writers_stopped: true });
  } finally { env.close(); }
});

test('legacy is explained without detection or editable controls; read failures are visible', async () => {
  const state = { ...base(), mode: 'READY', legacy: true };
  const env = environment('en', state), tree = env.tree();
  try {
    const html = await env.render(tree); assert.ok(html.includes(env.catalog["configuration.legacy"])); assert.doesNotMatch(html, /<form|<input|<textarea/);
    assert.ok(env.requests.every(request => request.body === undefined));
  } finally { env.close(); }
  const failed = environment(); failed.failRead = true;
  try { assert.match(await failed.render(failed.tree()), /role="alert"/); } finally { failed.close(); }
});

test('setup routing resolves archive first and blocks operational workspace before redirect', async () => {
  for (const mode of ['UNCONFIGURED', 'INVALID', 'RECOVERY_REQUIRED', 'RESTART_REQUIRED', 'READ_ONLY_ARCHIVE']) {
    const env = environment('en', { ...base(), mode });
    try {
      await env.render(env.tree(el(Page, { route: parse('/projects/synthetic/settings') })));
      assert.deepEqual(env.navigation, mode === 'READ_ONLY_ARCHIVE' ? [] : ['/setup']);
      assert.equal(env.requests.length, 0);
    } finally { env.close(); }
  }
  for (const path of ['/setup', '/settings/configuration']) {
    const route = parse(path); assert.equal(href(route), path);
    const breadcrumb = trail(route, key => en[key]); assert.equal(breadcrumb.at(-1).label, en['configuration.title']);
  }
});

test('reviewer model offers the packaged catalog per provider and keeps a hand-written model', async () => {
  const env = environment(), tree = env.tree();
  const model = () => JSON.parse(env.storage.get('harness-configuration-draft-v1')).form.agents.reviewer.model;
  const select = () => env.host.elements.find(item => item.type === 'select' && item.props.id === 'configuration-agents-reviewer-model');
  try {
    let html = await env.render(tree);
    // A saved model outside the catalog stays visible and editable under "Other".
    assert.equal(select().props.value, '_other'); assert.match(html, /value="gpt-6\.1-sol"/); assert.doesNotMatch(html, /claude-opus-5-5/);
    assert.match(html, /id="configuration-agents-reviewer-model-other"[^>]*value="explicit-model"/);
    env.input('configuration-agents-reviewer-provider', 'claude'); html = await env.render(tree);
    assert.equal(model(), 'explicit-model'); assert.match(html, /value="claude-opus-5-5"/); assert.doesNotMatch(html, /gpt-6\.1-sol/);
    env.input('configuration-agents-reviewer-model', 'claude-opus-5-5'); html = await env.render(tree);
    assert.equal(model(), 'claude-opus-5-5'); assert.equal(select().props.value, 'claude-opus-5-5');
    assert.doesNotMatch(html, /reviewer-model-other/);
    // A packaged model does not carry over to another provider.
    env.input('configuration-agents-reviewer-provider', 'codex'); await env.render(tree);
    assert.equal(model(), ''); assert.equal(select().props.value, '');
    env.input('configuration-agents-reviewer-model', '_other'); html = await env.render(tree);
    assert.equal(model(), ''); assert.match(html, /reviewer-model-other/);
    env.input('configuration-agents-reviewer-model-other', 'synthetic-new-model'); await env.render(tree);
    assert.equal(model(), 'synthetic-new-model');
  } finally { env.close(); }
});

test('draft validation, permission preservation and positive/path field errors', () => {
  const value = draft(base()); value.form.agents.reviewer.timeout_seconds = 0;
  value.form.git.executable = 'relative'; value.form.registration.roots = ['relative'];
  assert.equal(errors(value)['agents.reviewer.timeout_seconds'], 'configuration.positive');
  assert.equal(errors(value)['git.executable'], 'configuration.absolute');
  assert.equal(errors(value)['registration.roots'], 'configuration.absolute');
  value.validated = false; assert.deepEqual(errors(value), {});
  const request = change(value); assert.equal(request.form.agents.executor.tools[0], 'Read');
  assert.equal(request.validated, false); assert.equal(request.active_sha256, null);
});


for (const language of ['en', 'es']) test(`configuration assistance requires an exact turn and only applies a draft (${language})`, async () => {
  const state = { ...base(), mode: 'READY', status: 'READY', version: 2, form: form(),
    active: { scope: 'global', revision: 1, sha256: sha('a'), status: 'VALIDATED' }, working_sha256: sha('a'), actual_sha256: sha('a') };
  const env = environment(language, state), tree = env.tree();
  try {
    await env.render(tree);
    assert.ok(env.requests.every(r => r.body === undefined));
    env.input('configuration-assistance-message', 'Explain a useful later configuration'); await env.render(tree);
    env.click('assistance.preview'); await env.render(tree);
    assert.equal(env.button('assistance.confirm').disabled, true);
    env.tick('assistance.authorize'); await env.render(tree); env.click('assistance.confirm'); await env.render(tree);
    assert.equal(env.requests.filter(r => r.path.endsWith('/assistance/confirm')).length, 1);
    assert.deepEqual(env.state.active, state.active);
    env.click('assistance.apply'); const html = await env.render(tree);
    assert.match(html, /Proposed synthetic name/);
    assert.equal(env.requests.filter(r => r.path.endsWith('/save') || r.path.endsWith('/activate')).length, 0);
    assert.equal(JSON.parse(env.storage.get('harness-configuration-draft-v1')).source, 'text');
  } finally { env.close(); }
});

test('an unacknowledged assistance turn is repeated only by explicit action with the same key', async () => {
  const state = { ...base(), mode: 'READY', status: 'READY', version: 2, form: form(),
    active: { scope: 'global', revision: 1, sha256: sha('a'), status: 'VALIDATED' }, working_sha256: sha('a'), actual_sha256: sha('a') };
  const env = environment('en', state), tree = env.tree();
  try {
    await env.render(tree); env.input('configuration-assistance-message', 'Review a synthetic change'); await env.render(tree);
    env.click('assistance.preview'); await env.render(tree); env.tick('assistance.authorize'); await env.render(tree);
    env.failAssistance = true; env.click('assistance.confirm'); await env.render(tree);
    const before = env.requests.filter(r => r.path.endsWith('/assistance/confirm'));
    assert.equal(before.length, 1);
    await env.render(tree); assert.equal(env.requests.filter(r => r.path.endsWith('/assistance/confirm')).length, 1);
    env.click('workspace.pending.repeat'); await env.render(tree);
    const calls = env.requests.filter(r => r.path.endsWith('/assistance/confirm'));
    assert.equal(calls.length, 2);
    assert.equal(calls[0].options.headers['Idempotency-Key'], calls[1].options.headers['Idempotency-Key']);
    assert.deepEqual(calls[0].body, calls[1].body);
    assert.equal(env.storage.get('harness-configuration-assistance:global'), undefined);
  } finally { env.close(); }
});

for (const language of ['en', 'es']) {
  test(`legacy conversion is explicit, reviewed and leaves preparation visible (${language})`, async () => {
    const state = { ...base(), mode: 'READY', legacy: true, legacy_source: '/synthetic/original.toml' };
    const env = environment(language, state), tree = env.tree();
    try {
      await env.render(tree);
      assert.ok(env.requests.every(request => request.body === undefined));
      env.click('configuration.import_review'); let html = await env.render(tree);
      assert.match(html, /draft project/);
      assert.equal(env.button('configuration.import').disabled, true);
      env.tick('profile.confirm_exact'); await env.render(tree);
      env.click('configuration.import'); html = await env.render(tree);
      const request = env.requests.find(request => request.path.endsWith('/import/save'));
      assert.equal(request.body.source, '/synthetic/original.toml');
      assert.equal(request.body.preview_sha256, sha('b'));
      assert.ok(request.options.headers['Idempotency-Key']);
      assert.equal(env.state.active, null); assert.equal(env.state.legacy, true);
      assert.ok(html.includes(env.catalog['configuration.import_prepare']));
      assert.match(html, /projects\/own/);
      assert.equal(env.requests.filter(request => /detect|check-clients|activate/.test(request.path)).length, 0);
    } finally { env.close(); }
  });
}

for (const language of ['en', 'es']) {
  test(`a live set shows its policy, waits for named current work and stays cancellable (${language})`, async () => {
    const saved = { ...base(), mode: 'READY', status: 'READY', version: 2, blockers: [],
      saved: { scope: 'global', revision: 2, sha256: sha('c'), status: 'VALIDATED' }, active: { scope: 'global', revision: 1, sha256: sha('a'), status: 'VALIDATED' },
      actual_sha256: sha('c'), form: form(), text: JSON.stringify(form()) };
    const env = environment(language, saved), tree = env.tree();
    env.activationPreview = { restart_required: false, apply: 'live', waiting: ['job:7', 'job:preparation:p1', 'acceptance:run-1'] };
    env.liveWaiting = ['job:7'];
    try {
      await env.render(tree);
      env.click('configuration.activation_preview'); let html = await env.render(tree);
      assert.ok(html.includes(env.catalog['configuration.live.will_wait']));
      assert.ok(html.includes(env.catalog['configuration.waiting.preparation'].replace('{id}', 'p1')));
      assert.ok(html.includes(env.catalog['configuration.waiting.acceptance'].replace('{id}', 'run-1')));
      assert.ok(!html.includes(env.catalog['configuration.restart_hint']));
      env.tick('configuration.confirm_activation'); await env.render(tree); env.click('configuration.activate'); html = await env.render(tree);
      assert.ok(html.includes(env.catalog['configuration.mode.apply_pending']));
      assert.ok(html.includes(env.catalog['configuration.live.when_idle']));
      assert.ok(html.includes(env.catalog['configuration.waiting.job'].replace('{id}', '7')));
      assert.ok(env.requests.every(request => !request.path.endsWith('/restart')));
      env.tick('configuration.confirm_cancel'); await env.render(tree); env.click('configuration.cancel'); await env.render(tree);
      assert.equal(env.requests.find(request => request.path.endsWith('/cancel')).body.activation_id, 'pending-activation');
    } finally { env.close(); }
  });

  test(`a refused or failed live candidate names the setting to correct (${language})`, async () => {
    const failed = { ...base(), mode: 'READY', status: 'READY', version: 3, blockers: [],
      saved: { scope: 'global', revision: 2, sha256: sha('c'), status: 'VALIDATED' }, active: { scope: 'global', revision: 1, sha256: sha('a'), status: 'VALIDATED' },
      actual_sha256: sha('c'), form: form(), text: JSON.stringify(form()),
      live_activation: { activation_id: 'withdrawn', state: 'FAILED', waiting: [], restart_fields: [], code: 'live_configuration_refused',
        details: [{ project: 'own', role: null, setting: 'project:own', code: 'project_preparation_changed', diagnostic: null, already_failing: false }] } };
    const env = environment(language, failed), tree = env.tree();
    env.refuseActivation = true;
    try {
      let html = await env.render(tree);
      assert.ok(html.includes(env.catalog['configuration.live.failed'].replace('{id}', 'withdrawn')));
      assert.match(html, /own · project_preparation_changed/);
      env.click('configuration.activation_preview'); html = await env.render(tree);
      assert.ok(html.includes(env.catalog['configuration.live.refused']));
      assert.match(html, /agents\.executor · discovery_path · Configure an explicit PATH/);
      assert.equal(env.requests.filter(request => request.path.endsWith('/activate')).length, 0);
    } finally { env.close(); }
  });
}
