import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const { I18nProvider } = await import('../src/Language.tsx');
const { JudgeFields } = await import('../src/JudgeFields.tsx');
const { agentIssues, toolsSupported } = await import('../src/profile-form.ts');
const { billingGlobal, billingProject } = await import('../src/billing.ts');
const efforts = { codex: ['medium'], claude: ['high'] };

test('judge validates its own selection and has no writable tools', () => {
  const judge = { provider: 'codex', model: 'synthetic-model', effort: 'medium', environment: { USER: 'synthetic' }, timeout_seconds: 10 };
  assert.deepEqual(agentIssues(judge, 'agents.judge', ['judge'], efforts), {});
  assert.equal(agentIssues({ ...judge, effort: 'high' }, 'agents.judge', ['judge'], efforts)['agents.judge.effort'], 'configuration.effort_invalid');
  assert.equal(agentIssues({ ...judge, model: '-flag' }, 'agents.judge', ['judge'], efforts)['agents.judge.model'], 'configuration.required');
  assert.equal(toolsSupported('claude', ['judge']), false);
  assert.ok(agentIssues({ ...judge, tools: ['Write'] }, 'agents.judge', ['judge'], efforts)['agents.judge.tools']);
  assert.ok(billingGlobal({ format: 'local-config-11' }));
  assert.ok(billingProject({ format: 'project-config-3' }));
});

test('judge controls show independent provider/model/effort and preserve optional manual paths', () => {
  const render = form => renderToStaticMarkup(createElement(I18nProvider, null,
    createElement(JudgeFields, { form, scope: 'project-profile', issues: {}, onChange: () => {} })));
  const disabled = render({ agents: {} });
  assert.match(disabled, /checkbox/);
  assert.doesNotMatch(disabled, /agents-judge-model/);
  const enabled = render({ format: 'project-config-3', agents: { judge: { provider: 'codex', model: 'synthetic-model',
    effort: 'medium', environment: { USER: 'synthetic' }, timeout_seconds: 10 } } });
  assert.match(enabled, /agents-judge-model/);
  assert.match(enabled, /synthetic-model/);
  assert.match(enabled, /agents-judge-provider/);
  assert.match(enabled, /agents-judge-effort/);
});
