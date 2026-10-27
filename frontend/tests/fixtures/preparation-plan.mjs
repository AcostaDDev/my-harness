export function genericPreparationPlan() {
  const technical = { write_paths: ['app/prepare.py', '.prepare/**'], local_paths: ['.prepare/**'], environment_paths: [],
    dependencies: [], network: [], scripts: false,
    executor_selection: { model: 'synthetic-executor', effort: 'medium', reason: 'Bounded synthetic preparation' },
    instructions: 'Write only app/prepare.py and the private preparation files.' };
  const environment = { HOME: '/synthetic/own/.prepare/home', TMPDIR: '/synthetic/own/.prepare/tmp' };
  const command = (stage, argv) => ({ kind: 'command', stage, index: 0,
    command: { argv, cwd: 'app', timeout_seconds: 120, environment: [['SYNTHETIC_VALUE', 'two words']] },
    executables: { python: '/synthetic/python' }, environment, max_timeout_seconds: 900,
    max_output_bytes: 65536, network: [], scripts: false });
  return { contract: 'project-profile-preparation-1', recipe: null, project_id: 'own', root: '/synthetic/own',
    preview_sha256: 'b'.repeat(64), mode: 'offline', work_language: 'en',
    configuration: { scope: 'project:own', revision: 2, sha256: 'c'.repeat(64) }, technical,
    files: technical.write_paths.map(path => ({ path, effect: 'may create or modify' })),
    steps: [{ kind: 'directories', paths: ['.prepare/home', '.prepare/tmp'] },
      { kind: 'executor', selection: technical.executor_selection, instructions: technical.instructions, write_paths: technical.write_paths },
      command('preparation', ['python', '-m', 'synthetic.prepare', '--name', 'two words']),
      command('validation', ['python', '-m', 'synthetic.tests', '<escaped>']), { kind: 'commit' }],
    commit: { message: 'harness: prepare project profile', author_name: 'Synthetic', author_email: 'test@example.invalid' } };
}

export function genericConfiguration() {
  return { scope: 'project:own', version: 1, status: 'UNCONFIGURED',
    saved: { scope: 'project:own', revision: 2, sha256: 'c'.repeat(64) },
    proposal_id: 'synthetic-profile', proposal_sha256: 'd'.repeat(64),
    configuration_state: 'PREPARATION_REQUIRED' };
}
