import { memo, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useArchive } from "./ServiceMode";
import { errorText, translateNow, useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";
import { managed, ManagedError } from "./managed-api";
import type { S } from "./managed-api";
import { refusalLine } from "./configuration.ts";
import { STATUS_ICONS, STATUS_LABELS, statusClassOf } from "./map/status.ts";
import type { StatusClass } from "./map/status.ts";
import { listStatusClass } from "./status-class.ts";
import type { LiveRefusal } from "./configuration.ts";

/** Text of an error to show: a service problem without a diagnostic gets the interface's own sentence. */
export const message = (e: unknown) => (e instanceof ManagedError && e.diagnostic === undefined
  ? translateNow("error.no_diagnostic", { status: e.status, code: e.code ?? "request_failed" }) : errorText(e)) + corrections(e);

/** Structured corrections of a refused candidate (D238/D263): where, code and diagnostic, one per line. */
function corrections(e: unknown) {
  if (!(e instanceof ManagedError) || !e.details?.length) return "";
  return e.details.map(item => "\n" + refusalLine((item && typeof item === "object" ? item : {}) as LiveRefusal)).join("");
}

/** Full uninterpreted evidence: null is shown as "not recorded", never as empty. */
export function Evidence({ title, value }: { title: string; value: unknown }) {
  const { t } = useI18n();
  return <details className="evidence"><summary>{title}</summary>
    <pre>{value === null ? t("common.not_recorded_null") : JSON.stringify(value, null, 2)}</pre></details>;
}

export type Poll<T> = { data?: T; error?: string; missing: boolean; loading: boolean };

/**
 * Periodic read of an /api/managed resource. A failure keeps the last read and says so;
 * a 404 marks the resource as absent. A null `path` queries nothing.
 */
export function usePoll<T>(path: string | null, interval = 1500, refresh = 0): Poll<T> {
  const archive = useArchive();
  const effectiveInterval = archive ? 0 : interval;
  const [state, setState] = useState<Poll<T>>({ missing: false, loading: path !== null });
  const current = useRef(path);
  useEffect(() => {
    // Rereading the same resource after an action keeps the shown read (and what hangs from it) until the new one.
    const same = current.current === path;
    current.current = path;
    setState(previous => same && previous.data !== undefined ? { ...previous, loading: true } : { missing: false, loading: path !== null });
    if (path === null) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await managed<T>(path!);
        if (active) setState({ data, missing: false, loading: false });
      } catch (e) {
        if (!active) return;
        const missing = e instanceof ManagedError && e.status === 404;
        setState(previous => ({ data: missing ? undefined : previous.data, error: message(e), missing, loading: false }));
      }
      if (active && effectiveInterval > 0) timer = setTimeout(() => void poll(), effectiveInterval);
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [path, effectiveInterval, refresh]);
  return state;
}

/** Unified diff colored by line type; display only, the authority is the hash the server confirms. */
export function DiffBlock({ diff, label }: { diff: string; label: string }) {
  return <pre className="diff" aria-label={label}><DiffLines text={diff.endsWith("\n") ? diff : `${diff}\n`} /></pre>;
}

/**
 * Lines of a diff chunk with their exact text: only the newline the chunk carries is added, so a long line
 * split across two pages reads continuously. Memoized: a painted chunk is not repainted when another is added.
 */
export const DiffLines = memo(function DiffLines({ text }: { text: string }) {
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  const closed = text.endsWith("\n");
  return <>{lines.map((line, index) => {
    const kind = line.startsWith("+++") || line.startsWith("---") ? "file" : line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    return <span key={index} className={kind ? `diff-${kind}` : undefined}>{line}{index < lines.length - 1 || closed ? "\n" : ""}</span>;
  })}</>;
});

export function Loading({ children }: { children?: ReactNode }) {
  const { t } = useI18n();
  return <p role="status" className="state state-loading">{children ?? t("common.loading")}</p>;
}

export function Stale({ error }: { error?: string }) {
  const { t } = useI18n();
  return error ? <p role="status" className="state state-stale">{t("common.stale", { error })}</p> : null;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="state state-empty"><p className="state-title">{title}</p>{children}</div>;
}

export function Alert({ children }: { children: ReactNode }) {
  return <p role="alert" className="state state-error">{children}</p>;
}

/** Heading of a resource: its identifier (`P001-T003`) is the heading, in monospace. */
export function PageHeader({ title, code = false, children, aside }: { title: ReactNode; code?: boolean; children?: ReactNode; aside?: ReactNode }) {
  return <header className="page-header">
    <div className="page-heading">
      <h1 tabIndex={-1} id="page-title" className={code ? "page-code" : undefined}>{title}</h1>
      {children && <div className="page-lede">{children}</div>}
    </div>
    {aside && <div className="page-aside">{aside}</div>}
  </header>;
}

/**
 * Page body with a side rail (OT002): the rail sits to the right, sticky, when the body itself is wide enough
 * (a container query, so it also works inside other columns) and follows the main column when it is not.
 * Without a rail the body renders as is. The main column comes first in reading and keyboard order.
 */
export function Workbench({ aside, label, children }: { aside?: ReactNode; label?: string; children: ReactNode }) {
  if (!aside) return <>{children}</>;
  return <div className="workbench"><div className="workbench-grid">
    <div className="workbench-main">{children}</div>
    <aside className="workbench-aside" aria-label={label}>{aside}</aside>
  </div></div>;
}

export function Fields({ items }: { items: [string, ReactNode][] }) {
  return <dl className="fields">{items.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>;
}

export function Hash({ value, length = 12 }: { value?: string | null; length?: number }) {
  const { t } = useI18n();
  if (!value) return <span className="muted">{t("common.not_recorded")}</span>;
  return <code className="hash" title={value}>{value.slice(0, length)}</code>;
}

// Labels of the persisted codes the lists show; the class (colour and icon) comes from `status-class.ts`.
const RUN: Record<string, MessageKey> = {
  QUEUED: "status.run.QUEUED", ACTIVE: "status.run.ACTIVE", PLANNING: "status.run.PLANNING", PREPARING: "status.run.PREPARING",
  EXECUTING: "status.run.EXECUTING", REVIEWING: "status.run.REVIEWING", VALIDATING: "status.run.VALIDATING",
  COMMITTING: "status.run.COMMITTING", ANSWERING: "status.run.ANSWERING", DISCOVERING: "status.run.DISCOVERING",
  CHECKING: "status.run.CHECKING", ACCEPTANCE_READY: "status.run.ACCEPTANCE_READY", BLOCKED: "status.run.BLOCKED",
  REVISION_LIMIT: "status.run.REVISION_LIMIT", RECOVERY_REQUIRED: "status.run.RECOVERY_REQUIRED", STOPPED: "status.run.STOPPED",
  INTERRUPTED: "status.run.INTERRUPTED", COMMITTED: "status.run.COMMITTED", COMPLETED: "status.run.COMPLETED", DONE: "status.run.DONE",
  FAILED: "status.run.FAILED", ABORTED: "status.run.ABORTED", REFUSED: "status.run.REFUSED", INTENT: "status.run.INTENT",
  // Attempt outcomes: the adapter's stream status, upper-cased when the attempt is stored.
  COMPLETE: "status.run.COMPLETE", PARTIAL: "status.run.PARTIAL", INVALID: "status.run.INVALID", CANCELLED: "status.run.CANCELLED",
  TIMEOUT: "status.run.TIMEOUT", TIMED_OUT: "status.run.TIMEOUT", REPETITIVE: "status.run.REPETITIVE",
};

export const PHASE: Record<S["PhaseRead"]["status"], MessageKey> = {
  ACTIVE: "status.phase.ACTIVE", CHECKING: "status.phase.CHECKING", READY_TO_CLOSE: "status.phase.READY_TO_CLOSE",
  NEEDS_RECONCILIATION: "status.phase.NEEDS_RECONCILIATION", BLOCKED: "status.phase.BLOCKED", CLOSING: "status.phase.CLOSING",
  CLOSED: "status.phase.CLOSED", ABANDONED: "status.phase.ABANDONED",
};

/** Icon of a status class (T018 §5.1): check, arrow, hand, cross, empty circle, dash or question mark. */
export function StatusIcon({ cls }: { cls: StatusClass }) {
  const icon = STATUS_ICONS[cls];
  return <svg className="status-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
    {icon.kind === "circle" ? <circle cx="10" cy="10" r="6" /> : <path d={icon.d} />}
  </svg>;
}

/**
 * Status in one of the six classes plus `unknown` (D304): icon, translated text and the original code for assistive
 * technology; colour is never the only signal. A code without a mapping is `unknown` and shows its raw value.
 */
export function Status({ value, kind = "run" }: { value: string; kind?: "run" | "phase" }) {
  const { t } = useI18n();
  const cls = listStatusClass(kind, value);
  const key = kind === "phase" ? PHASE[value as S["PhaseRead"]["status"]] : RUN[value];
  const label = key ? t(key) : cls === "unknown" ? t("map.status.unknown_code", { code: value }) : t(STATUS_LABELS[cls]);
  return <span className={`status status-${cls}`} title={value} data-status-class={cls}>
    <StatusIcon cls={cls} /><span>{label}</span>{cls !== "unknown" && <span className="visually-hidden"> ({value})</span>}
  </span>;
}

/** A projected status (`{code, class}` from T020): the class is shown as projected, never recomputed. */
export function MapStatusBadge({ status }: { status: { code?: string | null; class: string } }) {
  const { t } = useI18n();
  const cls = statusClassOf(status.class);
  const code = status.code ?? undefined;
  const label = cls === "unknown" && code ? t("map.status.unknown_code", { code }) : t(STATUS_LABELS[cls]);
  return <span className={`status status-${cls}`} title={code} data-status-class={cls}>
    <StatusIcon cls={cls} /><span>{label}</span>{code && cls !== "unknown" && <span className="visually-hidden"> ({code})</span>}
  </span>;
}

const TRACK: S["PhaseRead"]["status"][] = ["ACTIVE", "CHECKING", "READY_TO_CLOSE", "CLOSING", "CLOSED"];
const SIDINGS: Partial<Record<S["PhaseRead"]["status"], S["PhaseRead"]["status"]>> = {
  NEEDS_RECONCILIATION: "CHECKING", BLOCKED: "CHECKING", ABANDONED: "ACTIVE",
};

/** Phase lifecycle (D032/D034): the main track and, off it, the detours. */
export function PhaseRail({ status }: { status: S["PhaseRead"]["status"] }) {
  const { t } = useI18n();
  const siding = SIDINGS[status];
  const position = TRACK.indexOf(siding ?? status);
  return <div className="rail" role="img" aria-label={t("phase.rail", { status: t(PHASE[status]) })}>
    <ol className="rail-track">
      {TRACK.map((step, index) => <li key={step} className={index < position ? "rail-past" : index === position ? (siding ? "rail-branch" : "rail-now") : "rail-next"}>
        <span className="rail-stop" aria-hidden="true" /><span className="rail-label">{t(PHASE[step])}</span>
        {index === position && siding && <span className="rail-siding">{t(PHASE[status])}</span>}
      </li>)}
    </ol>
  </div>;
}

export function Pagination({ offset, next, onChange, size = 30, label }: { offset: number; next: number | null | undefined; onChange: (offset: number) => void; size?: number; label: string }) {
  const { t } = useI18n();
  if (!offset && next == null) return null;
  return <nav className="pagination" aria-label={label}>
    <button type="button" className="button-quiet" disabled={!offset} onClick={() => onChange(Math.max(0, offset - size))}>{t("common.previous_page")}</button>
    <button type="button" className="button-quiet" disabled={next == null} onClick={() => onChange(next!)}>{t("common.next_page")}</button>
  </nav>;
}

/** Date and time in the visual language; the original value stays in the tooltip. */
export function when(value: string | null | undefined) {
  return <When value={value} />;
}

function When({ value }: { value: string | null | undefined }) {
  const { t, language } = useI18n();
  if (!value) return <span className="muted">{t("common.no_date")}</span>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return <time dateTime={value} title={value}>{date.toLocaleString(language, { dateStyle: "short", timeStyle: "short" })}</time>;
}
