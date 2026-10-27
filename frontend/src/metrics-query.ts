export type Scope = { project?: string; phase?: string; task?: string; run?: string };
export type Projects = { id: string; root: string }[];

export function query(scope: Scope, extra: Record<string, string | number> = {}) {
  const params = new URLSearchParams();
  if (scope.run) params.set("run_id", scope.run);
  if (scope.project) params.set("project_id", scope.project);
  if (scope.phase) params.set("phase", scope.phase);
  if (scope.task) params.set("task", scope.task);
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  const text = params.toString();
  return text ? `?${text}` : "";
}
