import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { converted, defaultUsers, fromScheme, globalIssues, missingConditions, profileIssues, resolution, schemeOf,
  selectionIssues } = await import('../src/billing.ts');
const { errors, initialDraft } = await import('../src/configuration.ts');
const { projectIssues } = await import('../src/project-profile.ts');

// Synthetic values only: digests and schemes are made up, never a real account, invoice or price observation.
const BUNDLE = 'a'.repeat(64);
const scheme = { provider: 'codex', platform: 'synthetic_platform', product: 'synthetic_product', scheme: 'synthetic_credit',
  unit: 'synthetic_credit', bases: ['subscription_equivalent', 'token_credit'], models: ['synthetic-model'],
  conditions: { geography: ['global'], speed: ['standard', 'fast'] } };
const bundles = [{ id: BUNDLE, source: 'packaged', recorded_at: null, available: true, references: 2, providers: ['codex'],
  models: ['synthetic-model'], observed_from: null, observed_to: null, effective_period: 'unknown', schemes: [scheme] }];
const profile = () => ({ provider: 'codex', platform: 'synthetic_platform', product: 'synthetic_product',
  scheme: 'synthetic_credit', unit: 'synthetic_credit', basis: 'token_credit', references: BUNDLE,
  conditions: { speed: { value: 'standard', source: 'synthetic assertion' } } });
const global = (billing, format = 'local-config-10') => ({ format, agents: { reviewer: { provider: 'codex' }, executor: { provider: 'claude' } },
  ...(billing ? { billing } : {}) });

test('conversion changes only the format and loading never converts', () => {
  const form = { format: 'local-config-9', agents: { reviewer: { provider: 'codex' } }, extra: { kept: true } };
  assert.deepEqual(converted(form, 'local-config-10'), { ...form, format: 'local-config-10' });
  assert.equal(form.format, 'local-config-9');
  assert.deepEqual(globalIssues(form), {});
  assert.deepEqual(globalIssues({ ...form, billing: {} }), { billing: 'billing.format_required' });
});

test('profiles mirror the server field rules and keep conditions as sourced assertions', () => {
  assert.deepEqual(profileIssues(profile(), 'p'), {});
  const broken = { ...profile(), provider: 'other', basis: 'invoice', references: 'latest', unit: 'two words',
    conditions: { Speed: { value: 'standard', source: 'x' }, geography: { value: 'Global', source: 'x' }, tier: { value: 'base', source: ' ' } } };
  assert.deepEqual(profileIssues(broken, 'p'), {
    'p.unit': 'billing.identifier', 'p.provider': 'configuration.required', 'p.basis': 'configuration.required',
    'p.references': 'billing.references_required', 'p.conditions.Speed': 'billing.condition_name',
    'p.conditions.geography.value': 'billing.condition_value', 'p.conditions.tier.source': 'billing.condition_source' });
  const many = Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`c${i}`, { value: 'v', source: 's' }]));
  assert.equal(profileIssues({ ...profile(), conditions: many }, 'p')['p.conditions'], 'billing.conditions_limit');
});

test('defaults must name a profile of the role provider, and used profiles are reported', () => {
  const form = global({ profiles: { credits: profile() }, defaults: { reviewer: 'credits', executor: 'credits' } });
  assert.deepEqual(globalIssues(form), { 'billing.defaults.executor': 'billing.provider_mismatch' });
  assert.deepEqual(globalIssues(global({ profiles: {}, defaults: { reviewer: 'gone' } })), { 'billing.defaults.reviewer': 'billing.profile_missing' });
  assert.deepEqual(globalIssues(global({ profiles: { 'Bad Name': profile() } }))['billing.profiles.Bad Name'], 'billing.profile_name');
  assert.deepEqual(defaultUsers(form, 'credits'), ['reviewer', 'executor']);
  // The global form check adds billing issues to the other editor checks.
  const draft = { ...initialDraft({ version: 0, form: { ...form, git: {} } }), reason: 'x' };
  assert.equal(errors(draft)['billing.defaults.executor'], 'billing.provider_mismatch');
});

test('a listed scheme fills only identity, basis and bundle; required conditions are named, not invented', () => {
  const blank = { provider: 'codex', basis: 'api_usd', conditions: { speed: { value: 'fast', source: 'own contract' } }, note: 'kept' };
  const filled = fromScheme(blank, scheme, BUNDLE);
  assert.deepEqual(filled, { ...blank, platform: 'synthetic_platform', product: 'synthetic_product', scheme: 'synthetic_credit',
    unit: 'synthetic_credit', basis: 'subscription_equivalent', references: BUNDLE });
  assert.equal(fromScheme(profile(), scheme, BUNDLE).basis, 'token_credit');  // a supported basis is kept
  assert.equal(schemeOf(profile(), bundles), scheme);
  assert.equal(schemeOf({ ...profile(), unit: 'USD' }, bundles), undefined);
  assert.deepEqual(missingConditions(profile(), scheme), ['geography']);
  assert.deepEqual(missingConditions(profile(), undefined), []);
});

test('project selections name a global profile of the role provider; inherited defaults resolve or stay unknown', () => {
  const project = { format: 'project-config-2', agents: { reviewer: { provider: 'codex' }, executor: { provider: 'claude' } },
    billing: { reviewer: 'credits', executor: 'credits' } };
  const profiles = { credits: profile() };
  assert.deepEqual(selectionIssues(project, profiles), { 'billing.executor': 'billing.provider_mismatch' });
  assert.deepEqual(selectionIssues({ ...project, billing: { reviewer: 'missing' } }, profiles), { 'billing.reviewer': 'billing.profile_missing' });
  assert.deepEqual(selectionIssues({ ...project, billing: { reviewer: 'missing' } }, undefined), {});  // left to the server
  assert.deepEqual(selectionIssues({ ...project, format: 'project-config-1' }, profiles), { billing: 'billing.format_required' });
  assert.deepEqual(resolution('reviewer', {}, { reviewer: 'credits' }, profiles, 'codex'), { name: 'credits', origin: 'default', known: true });
  assert.deepEqual(resolution('executor', { executor: 'credits' }, {}, profiles, 'claude'), { name: 'credits', origin: 'selected', known: false });
  assert.deepEqual(resolution('executor', {}, {}, profiles, 'claude'), { name: undefined, origin: 'none', known: false });
  const editing = { stage: 'later', profile: false, agents: false };
  assert.equal(projectIssues({ ...project, billing: { reviewer: 'Bad' } }, editing, {})['billing.reviewer'], 'billing.profile_name');
});
