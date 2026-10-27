import { mkdirSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

mkdirSync('.local', { recursive: true });
const files = readdirSync('tests').filter(name => name.endsWith('.test.mjs')).sort().map(name => `tests/${name}`);
const result = spawnSync(process.execPath, ['--test', '--test-reporter=tap', '--test-reporter=junit',
  '--test-reporter-destination=stdout', '--test-reporter-destination=.local/junit.xml', ...files], { stdio: 'inherit' });
process.exit(result.status ?? 1);
