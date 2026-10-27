import './helpers/tsx.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { agentIssues, argvIssue, commandsIssues, domId, fromLines, moved, profileIssues, profileTools, renamed,
  toLines, unmappedTools, withoutBlank, without } = await import('../src/profile-form.ts');
const { catalogIssues } = await import('../src/configuration.ts');
const { projectEditing, projectIssues } = await import('../src/project-profile.ts');

// Synthetic values only: no real project, path or command output.
const efforts = { codex: ['low', 'medium', 'high'], claude: ['low', 'medium', 'high'] };
const profile = () => ({ executor_instructions: 'Use the synthetic toolchain', preparation: [{ argv: ['tool', 'sync'], timeout_seconds: 60 }],
  validations: [{ argv: ['tool', 'test', 'a b'], timeout_seconds: 120, cwd: 'src', environment: { MODE: 'check' },
    junit: { path: 'reports/unit.xml', coverage: 'unit tests' } }],
  allowed_command_prefixes: [['tool', 'test']], protected_paths: ['AGENTS.md'], sensitive_paths: ['.env'], data_model_paths: [] });
const commands = () => ({ executables: { tool: '/synthetic/bin/tool' }, environment: { HOME: '/synthetic/home' },
  authorize_profile_commands: true, max_timeout_seconds: 1800, max_output_bytes: 1048576 });

test('argv stays shell free with a logical executable name first', () => {
  assert.equal(argvIssue(['tool', 'test', './...']), undefined);
  assert.equal(argvIssue([]), 'editor.argv_required');
  assert.equal(argvIssue(['tool', '']), 'editor.argv_blank');
  assert.equal(argvIssue(['tool', '   ']), 'editor.argv_blank');
  assert.equal(argvIssue(['/synthetic/bin/tool']), 'editor.argv_name');
  assert.equal(argvIssue(['bash', '-c', 'tool']), 'editor.argv_name');
  assert.equal(argvIssue(['tool', '&&', 'other']), 'editor.argv_shell');
  assert.equal(argvIssue(['tool', '$(other)']), 'editor.argv_shell');
  assert.equal(argvIssue(['tool', 'with space', 'a=b']), undefined, 'arguments are exact values, not shell words');
});

test('line editing keeps exact values and only drops blank lines explicitly', () => {
  assert.deepEqual(fromLines('tool\n  spaced arg \n'), ['tool', '  spaced arg ', '']);
  assert.deepEqual(withoutBlank(['tool', '', 'x']), ['tool', 'x']);
  assert.equal(toLines(['tool', ' a ']), 'tool\n a ');
  assert.deepEqual(fromLines(''), []);
  assert.deepEqual(moved(['a', 'b', 'c'], 2, -1), ['a', 'c', 'b']);
  assert.deepEqual(moved(['a', 'b'], 0, -1), ['a', 'b']);
  assert.deepEqual(Object.keys(renamed({ a: 1, b: 2, c: 3 }, 'b', 'z')), ['a', 'z', 'c']);
  assert.deepEqual(without({ a: 1, b: 2 }, 'a'), { b: 2 });
  assert.equal(domId('configuration', 'profiles.own.v1.validations.0.argv'), 'configuration-profiles-own-v1-validations-0-argv');
});

test('a complete profile has no issues; each policy names its own field', () => {
  assert.deepEqual(profileIssues(profile(), 'profile'), {});
  const broken = { ...profile(), executor_instructions: ' ', validations: [], protected_paths: [], sensitive_paths: ['/abs', '/abs'],
    data_model_paths: ['../outside'], formatter_argv: ['fmt', '--check'], formatter_paths: [] };
  assert.deepEqual(profileIssues(broken, 'profile'), {
    'profile.executor_instructions': 'configuration.required', 'profile.validations': 'editor.validations_required',
    'profile.protected_paths': 'editor.paths_required', 'profile.sensitive_paths': 'editor.relative',
    'profile.data_model_paths': 'editor.relative', 'profile.formatter_argv': 'editor.formatter_end',
    'profile.formatter_paths': 'editor.paths_required' });
  const reports = { ...profile(), validations: [profile().validations[0], { ...profile().validations[0], argv: ['tool', 'lint'] }] };
  assert.equal(profileIssues(reports, 'p')['p.validations'], 'editor.junit_repeated');
  const command = { ...profile(), preparation: [{ argv: ['tool'], cwd: '/abs' }], validations: [{ argv: ['tool'], timeout_seconds: 1, junit: { path: '.git/x', coverage: '' } }] };
  const issues = profileIssues(command, 'p');
  assert.equal(issues['p.preparation.0.timeout_seconds'], 'configuration.positive');
  assert.equal(issues['p.preparation.0.cwd'], 'editor.relative');
  assert.equal(issues['p.validations.0.junit.path'], 'editor.junit_path');
  assert.equal(issues['p.validations.0.junit.coverage'], 'configuration.required');
  assert.deepEqual(profileTools({ ...profile(), formatter_argv: ['fmt', '--'] }), ['tool', 'fmt']);
});

test('commands distinguish logical names from installed paths and keep authorization exact', () => {
  assert.deepEqual(commandsIssues(commands(), 'commands', profile()), {});
  assert.equal(commandsIssues({ ...commands(), executables: { tool: 'bin/tool' } }, 'c', profile())['c.executables.tool'], 'configuration.absolute');
  assert.equal(commandsIssues({ ...commands(), executables: { 'bin/tool': '/synthetic/tool' } }, 'c')['c.executables.bin/tool'], 'editor.argv_name');
  assert.deepEqual(unmappedTools({ ...profile(), formatter_argv: ['fmt', '--'] }, commands()), ['fmt']);
  assert.equal(commandsIssues(commands(), 'c', { ...profile(), formatter_argv: ['fmt', '--'] })['c.executables'], 'editor.unmapped');
  const manual = { ...commands(), authorize_profile_commands: false };
  assert.equal(commandsIssues(manual, 'c', profile())['c.authorize_profile_commands'], 'editor.authorize_all');
  const exact = { ...manual, authorized: [...profile().preparation, ...profile().validations.map(({ junit, ...rest }) => rest)] };
  assert.deepEqual(commandsIssues(exact, 'c', profile()), {});
  assert.equal(commandsIssues({ ...exact, executables: { ...exact.executables, fmt: '/synthetic/fmt' } }, 'c',
    { ...profile(), formatter_argv: ['fmt', '--'], formatter_paths: ['*.x'] })['c.authorize_profile_commands'], 'editor.formatter_authorize');
  assert.equal(commandsIssues({ ...commands(), max_output_bytes: 1048577 }, 'c')['c.max_output_bytes'], 'editor.max_output');
  assert.equal(commandsIssues({ ...commands(), max_timeout_seconds: 0 }, 'c')['c.max_timeout_seconds'], 'editor.max_timeout');
});

test('tool capabilities exist only for a Claude Code executor and are never dropped silently', () => {
  const executor = { provider: 'claude', timeout_seconds: 300, environment: { USER: 'synthetic' }, tools: ['Read', 'Edit'], grantable_tools: ['Bash(tool test)'] };
  assert.deepEqual(agentIssues(executor, 'a', ['executor'], efforts), {});
  assert.equal(agentIssues({ ...executor, provider: 'codex' }, 'a', ['executor'], efforts)['a.tools'], 'editor.tools_unsupported');
  assert.equal(agentIssues(executor, 'a', ['reviewer'], efforts)['a.tools'], 'editor.tools_unsupported');
  assert.equal(agentIssues(executor, 'a', ['reviewer', 'executor'], efforts)['a.tools'], 'editor.tools_unsupported');
  assert.equal(agentIssues({ ...executor, allowed_tools: ['-x'] }, 'a', ['executor'], efforts)['a.allowed_tools'], 'editor.tool_invalid');
  assert.equal(agentIssues({ ...executor, environment: { USER: 'synthetic', CLAUDE_CODE_DISABLE_AUTO_MEMORY: '0' } }, 'a', ['executor'], efforts)['a.environment'], 'editor.memory');
  assert.equal(agentIssues({ ...executor, environment: {} }, 'a', ['executor'], efforts)['a.environment'], 'editor.user_required');
  assert.equal(agentIssues({ ...executor, cli_version: '2.1' }, 'a', ['executor'], efforts)['a.cli_version'], 'editor.version');
  assert.equal(agentIssues({ ...executor, executable: ['claude'] }, 'a', ['executor'], efforts)['a.executable'], 'configuration.absolute');
});

test('global reusable profiles, compositions and presets are checked where they are declared', () => {
  const form = { profiles: { 'own.v1': profile() }, compositions: { own: { profile: 'own.v1', ...commands() },
      recipe: { profile: 'python-django-recipe', recipe: 'django', executables: { python: { project_venv: 'python' } } } },
    agent_presets: { 'claude-reviewer': { provider: 'claude', roles: ['reviewer'], models: ['synthetic-model'], efforts: ['medium'],
      allow_open_executor: false, timeout_seconds: 300, environment: { USER: 'synthetic' }, tools: ['Read'] } } };
  assert.deepEqual(catalogIssues(form), { 'agent_presets.claude-reviewer.tools': 'editor.tools_unsupported' });
  form.agent_presets['claude-reviewer'] = { ...form.agent_presets['claude-reviewer'], roles: [], models: ['-bad'], efforts: ['ultra'], tools: [] };
  form.compositions.own.executables = {};
  assert.deepEqual(catalogIssues(form), { 'compositions.own.executables': 'editor.executables_required',
    'agent_presets.claude-reviewer.roles': 'editor.roles_required', 'agent_presets.claude-reviewer.models': 'editor.models_invalid',
    'agent_presets.claude-reviewer.efforts': 'configuration.effort_invalid' });
});

test('project stages limit what the editor checks and offers', () => {
  const form = { profile: { ...profile(), validations: [] }, commands: { ...commands(), executables: { tool: '' } },
    agents: { reviewer: { provider: 'codex', model: '', effort: 'ultra', timeout_seconds: 1, environment: { USER: 's' } },
      executor: { provider: 'codex', timeout_seconds: 1, environment: { USER: 's' } } }, provenance: { source: 'profile-proposal' } };
  const initial = projectEditing({ active: null }, form);
  assert.deepEqual(initial, { stage: 'initial', profile: false, agents: false });
  assert.deepEqual(projectIssues(form, initial, efforts), { 'commands.executables.tool': 'configuration.required' });
  const later = projectEditing({ active: { revision: 1 } }, { ...form, edit: { head: 'h' } });
  assert.deepEqual(later, { stage: 'later', profile: true, agents: true });
  const issues = projectIssues(form, later, efforts);
  assert.equal(issues['profile.validations'], 'editor.validations_required');
  assert.equal(issues['agents.reviewer.model'], 'configuration.required');
  assert.equal(issues['agents.reviewer.effort'], 'configuration.effort_invalid');
  assert.deepEqual(projectEditing({ active: null }, { provenance: { source: 'legacy-configuration' } }), { stage: 'later', profile: false, agents: true });
});
