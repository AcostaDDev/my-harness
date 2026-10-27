import { LocalizedError } from "./i18n.ts";
import { sessionResponse } from "./session.ts";
import type { components, operations } from "./api.generated";

export type Simulation = components["schemas"]["SimulationRead"];
type SimulationCreate = operations["create_simulation"]["requestBody"]["content"]["application/json"];
type SimulationList = operations["list_simulations"]["responses"][200]["content"]["application/json"];

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

// Every mutation carries the local CSRF header required by the service guard (D033).
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  const init = SAFE.has(method) ? options : { ...options, headers: { ...(options?.headers as Record<string, string> | undefined), "X-My-Harness": "1" } };
  const response = await fetch(path, init);
  sessionResponse(response);
  if (!response.ok) {
    throw new LocalizedError("error.request_status", { status: response.status });
  }
  return response.json() as Promise<T>;
}

export const api = {
  list: () => request<SimulationList>("/api/simulations"),
  create: (body: SimulationCreate) => request<Simulation>("/api/simulations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
};
