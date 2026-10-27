import type { S } from './managed-api';

export const commandNames = ['estado', 'tests', 'siguiente', 'lote', 'check', 'cerrar', 'exportar', 'abrir-fase', 'tarea'] as const;
export type CommandName = typeof commandNames[number];
/** Client recognition only selects a control; the server validates the same closed syntax. */
export function isCommand(text: string): boolean { return text.trimStart().startsWith('/'); }
export function phaseSection(command: S['ChatCommandRead']['name']): 'phase-definition' | 'phase-documents' | 'phase-check' | 'phase-batch' | undefined {
  if (command === 'estado') return 'phase-definition';
  if (command === 'exportar') return 'phase-documents';
  if (command === 'check' || command === 'cerrar') return 'phase-check';
  if (command === 'siguiente' || command === 'lote') return 'phase-batch';
}
