import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runBody, sourcePhases, sourceTasks } from '../src/task-sources.ts';

const item = (task_id, title = 't') => ({ task_id, phase_id: task_id.split('-')[0], title, text: `## ${task_id} — ${title}`, sha256: task_id.toLowerCase().padEnd(64, '0') });
const items = [item('P001-T001'), item('P001-T002'), item('P002-T001')];

test('phases and tasks come from the document, narrowed to what the page fixes', () => {
  assert.deepEqual(sourcePhases(items), ['P001', 'P002']);
  assert.deepEqual(sourcePhases(items, 'P002'), ['P002']);
  assert.deepEqual(sourcePhases(items, 'P009'), []);
  assert.deepEqual(sourceTasks(items, 'P001').map(i => i.task_id), ['P001-T001', 'P001-T002']);
  assert.deepEqual(sourceTasks(items, 'P001', 'P001-T002').map(i => i.task_id), ['P001-T002']);
  assert.deepEqual(sourceTasks(items, ''), []);
});

test('a chosen task sends its literal text and hash; blank notes are omitted', () => {
  const manual = { task: ' P003-T001 ', phase: ' P003 ', text: 'contract' };
  assert.deepEqual(runBody(items[1], manual, '  '), { task_id: 'P001-T002', phase_id: 'P001', text: items[1].text, source_sha256: items[1].sha256 });
  assert.deepEqual(runBody(items[1], manual, ' Keep it small \n'), { task_id: 'P001-T002', phase_id: 'P001', text: items[1].text, source_sha256: items[1].sha256, notes: 'Keep it small' });
  assert.deepEqual(runBody(null, manual, ''), { task_id: 'P003-T001', phase_id: 'P003', text: 'contract' });
});
