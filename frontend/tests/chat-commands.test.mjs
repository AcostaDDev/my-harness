import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isCommand, phaseSection, commandNames } from '../src/chat-commands.ts';

test('slash syntax is routed to the deterministic server, including unknown commands', () => {
  for (const text of ['/estado', '  /tarea algo', '/unknown', '/CHECK', '/']) assert.equal(isCommand(text), true);
  for (const text of ['hola', 'usa /estado', '']) assert.equal(isCommand(text), false);
});
test('commands reuse the equivalent phase control without dispatching an effect', () => {
  assert.deepEqual(commandNames, ['estado', 'tests', 'siguiente', 'lote', 'check', 'cerrar', 'exportar', 'abrir-fase', 'tarea']);
  assert.equal(phaseSection('check'), 'phase-check');
  assert.equal(phaseSection('cerrar'), 'phase-check');
  assert.equal(phaseSection('siguiente'), 'phase-batch');
  assert.equal(phaseSection('lote'), 'phase-batch');
  assert.equal(phaseSection('exportar'), 'phase-documents');
  assert.equal(phaseSection('estado'), 'phase-definition');
  assert.equal(phaseSection('tarea'), undefined);
});
