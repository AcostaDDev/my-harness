export function estimateMinutes(tasks: number): number {
  if (!Number.isSafeInteger(tasks) || tasks < 0) {
    throw new RangeError("Introduce un número entero de tareas, mayor o igual a cero.");
  }
  return tasks * 30;
}
