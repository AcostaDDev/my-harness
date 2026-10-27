import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Dynamic imports ensure the TSX loader is installed before loading the actual form.
const { DraftFields } = await import('../src/pages/Registry.tsx');
const { I18nProvider } = await import('../src/Language.tsx');

const preset = (id, provider, role, model) => ({
  id, provider, roles: [role], models: [model], efforts: ['low'], allow_open_executor: false,
});
const draft = {
  project_id: 'synthetic', root: '/synthetic/project', composition: 'declared',
  planning_mode: 'agent', executor_mode: 'catalog', executor_models: ['executor-model'],
  executor_efforts: ['low'], max_revision_cycles: '0', tag_kind: 'lightweight',
  bootstrap_enabled: false, permission_authority: '', agent_mode: 'project',
  reviewer_preset: 'reader', reviewer_model: 'reviewer-model', reviewer_effort: 'low', executor_preset: 'writer',
};
function render(format, action, language = 'en', presets = true, overrides = {}) {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = () => assert.fail('Rendering must not call the service');
  globalThis.localStorage = { getItem: () => language };
  try {
    return renderToStaticMarkup(createElement(I18nProvider, null, createElement(DraftFields, {
      draft: { ...draft, ...overrides }, action, onChange: () => {}, options: {
        format, roots: ['/synthetic'], compositions: [], bootstrap_enabled: true,
        executor_effort_vocabulary: ['low'], reviewer_provider: 'claude', executor_provider: 'codex',
        agent_presets: presets ? [preset('reader', 'claude', 'reviewer', 'reviewer-model'),
          preset('writer', 'codex', 'executor', 'executor-model')] : [],
      },
    })));
  } finally { delete globalThis.localStorage; globalThis.fetch = previousFetch; }
}

for (const action of ['register', 'create', 'update']) {
  for (const language of ['en', 'es']) {
    test(`v8 ${action} exposes the selected reviewer/executor presets in ${language}`, () => {
      const html = render('local-config-8', action, language);
      assert.match(html, /<option value="reader" selected="">claude · reader<\/option>/);
      assert.match(html, /<option value="writer" selected="">codex · writer<\/option>/);
      assert.match(html, /<option value="reviewer-model" selected="">reviewer-model<\/option>/);
      assert.match(html, /<option value="low" selected="">low<\/option>/);
      assert.doesNotMatch(html, /local-config-5\/6\/7\/8/);
      // Each role's preset is offered only in its own selector.
      assert.equal((html.match(/value="reader"/g) ?? []).length, 1);
      assert.equal((html.match(/value="writer"/g) ?? []).length, 1);
    });
  }
}

test('v5–v9 keep preset selection; older and unknown formats retain the fallback', () => {
  for (const version of [5, 6, 7, 8, 9]) assert.match(render(`local-config-${version}`, 'register'), /value="reader"/);
  for (const format of ['local-config-1', 'local-config-2', 'local-config-3', 'local-config-4', 'local-config-10', undefined]) {
    const html = render(format, 'register');
    assert.doesNotMatch(html, /value="reader"|value="writer"/);
    assert.match(html, /local-config-5\/6\/7\/8/);
  }
});

test('v8 without operator presets keeps the missing-preset warning visible', () => {
  assert.match(render('local-config-8', 'register', 'en', false), /role="alert"/);
  assert.match(render('local-config-8', 'register', 'es', false), /role="alert"/);
});


test('v9 creation and registration offer context-first profiles without a required stack', () => {
  for (const action of ['register', 'create']) {
    const html = render('local-config-9', action);
    assert.match(html, /Define profile from project context/);
    assert.match(html, /value="reader"/);
  }
});

test('inherited agents offer packaged executor models as checkboxes and keep chosen ones', () => {
  const html = render('local-config-9', 'register', 'en', true, { agent_mode: 'inherited', executor_models: ['gpt-6-sol', 'synthetic-extra'] });
  for (const model of ['gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-astra', 'gpt-6-luna', 'synthetic-extra'])
    assert.match(html, new RegExp(`type="checkbox"[^>]*/>${model.replaceAll('.', '\\.')}</label>`));
  assert.match(html, /checked=""\/>gpt-6-sol</); assert.match(html, /checked=""\/>synthetic-extra</);
  assert.doesNotMatch(html, /checked=""\/>gpt-6\.1-sol</); assert.doesNotMatch(html, /claude-opus-5-5/);
  assert.doesNotMatch(html, /<textarea[^>]*>synthetic-extra/);
  assert.match(html, /Another model accepted by the CLI/);
  assert.match(render('local-config-9', 'register', 'es', true, { agent_mode: 'inherited' }), /Otro modelo que acepte la CLI/);
});

test('a project preset in catalog mode bounds the executor checkboxes to its own models', () => {
  const html = render('local-config-8', 'register');
  assert.match(html, /checked=""\/>executor-model</);
  assert.doesNotMatch(html, /gpt-6/); assert.doesNotMatch(html, /Another model accepted by the CLI/);
  const open = render('local-config-8', 'register', 'en', true, { executor_mode: 'open' });
  assert.match(open, /gpt-6-luna/); assert.match(open, /Another model accepted by the CLI/);
});
