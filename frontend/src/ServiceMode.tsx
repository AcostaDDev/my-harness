import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { errorText } from "./Language";
import { managed } from "./managed-api";
import type { S } from "./managed-api";

export const ServiceModeContext = createContext<S["SupervisorRead"] | undefined>(undefined);
const ServiceErrorContext = createContext<string | undefined>(undefined);
export function useServiceError() { return useContext(ServiceErrorContext); }
export function useServiceMode() { return useContext(ServiceModeContext); }
export function useArchive() { return useServiceMode()?.read_only_archive === true; }

/** Resolve the persistent archive mark before mounting any operational page or workspace. */
export function ServiceModeProvider({ children }: { children: ReactNode }) {
  const [error, setError] = useState<string>();
  const [status, setStatus] = useState<S["SupervisorRead"]>();
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const value = await managed<S["SupervisorRead"]>("/supervisor");
        if (!active) return;
        setStatus(value); setError(undefined);
        if (value.read_only_archive) return;
      } catch (error) { if (active) setError(errorText(error)); }
      if (active) timer = setTimeout(() => void read(), 5000);
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, []);
  return <ServiceModeContext.Provider value={status}><ServiceErrorContext.Provider value={error}>{children}</ServiceErrorContext.Provider></ServiceModeContext.Provider>;
}
