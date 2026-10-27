import { useState } from "react";
import { useFormats } from "../charts";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import type { S } from "../managed-api";
import { PROVENANCE } from "../metrics.ts";
import { query } from "../metrics-query";
import type { Scope, Projects } from "../metrics-query";
import { Link } from "../navigation";
import { useArchive } from "../ServiceMode";
import { Empty, Loading, Pagination, Stale, usePoll, when } from "../ui";
import { PURPOSES } from "./shared";

const PAGE = 10;
const INTERVAL = 15000;

function Provenance({ of, row }: { of: string; row: S["AttemptMetricRead"] }) {
  const { t } = useI18n();
  const value = row.provenance[of] ?? "absent";
  const known = PROVENANCE[value];
  return <abbr className={`provenance provenance-${value}`} title={known ? t(known[1]) : value}>{known ? t(known[0]) : value}</abbr>;
}

// --- attempts ----------------------------------------------------------------------------------

// Attempt outcome (D074): `COMPLETE`/`FAILED`/`INVALID`/`PARTIAL` come from the CLI adapter stream,
// `COMPLETED` from adapters without a stream and `INTERRUPTED` from confirming a stopped writer.
const ATTEMPT: Record<string, [MessageKey, string]> = {
  COMPLETE: ["stats.attempt.complete", "ok"], COMPLETED: ["stats.attempt.complete", "ok"], FAILED: ["stats.attempt.failed", "danger"],
  INVALID: ["stats.attempt.invalid", "danger"], PARTIAL: ["stats.attempt.partial", "attention"], INTERRUPTED: ["stats.attempt.interrupted", "danger"],
};

function AttemptStatus({ value }: { value: string }) {
  const { t } = useI18n();
  const known = ATTEMPT[value];
  const [label, tone] = known ? [t(known[0]), known[1]] : [value, "neutral"];
  return <span className={`status status-${tone}`} title={value}><span className="status-mark" aria-hidden="true" />{label}</span>;
}

export function Attempts({ scope, projects = [], refresh, title, interval = INTERVAL }: { scope: Scope; projects?: Projects; refresh: number; title?: string; interval?: number }) {
  const { t, rich } = useI18n();
  const archive = useArchive();
  const f = useFormats();
  const purpose = (value: string) => {
    const key = PURPOSES[value as keyof typeof PURPOSES];
    return key ? t(key) : value;
  };
  const [offset, setOffset] = useState(0);
  const read = usePoll<S["Page_AttemptMetricRead_"]>(`/metrics/attempts${query(scope, { offset, limit: PAGE })}`, interval, refresh);
  const projectOf = (root: string) => scope.project ?? projects.find(p => p.root === root)?.id;
  const heading = title ?? t("stats.attempts.title");
  return <section className="panel" aria-labelledby="attempts">
    <h2 id="attempts">{heading}</h2>
    <p className="hint">{t("stats.attempts.hint")}
      {Object.entries(PROVENANCE).map(([key, [mark, text, name]]) => <span key={key}> {rich("stats.attempts.provenance", { mark: <abbr className={`provenance provenance-${key}`} title={t(text)}>{t(mark)}</abbr>, name: t(name) })}</span>)}</p>
    <Stale error={read.error} />
    {!read.data ? read.error ? null : <Loading /> : !read.data.items.length && !offset ? <Empty title={t("stats.no_attempts")} />
      : <div className="table-scroll" tabIndex={0} role="region" aria-label={heading}>
        <table className="table">
          <thead><tr><th scope="col">{t("stats.column.start")}</th>{!scope.project && <th scope="col">{t("stats.dimension.root")}</th>}{!scope.task && <th scope="col">{t("runs.column.task")}</th>}<th scope="col">{t("stats.column.role")}</th><th scope="col">{t("stats.column.provider_model")}</th>
            <th scope="col">{t("stats.column.result")}</th><th scope="col" className="numeric">{t("stats.column.tokens")}</th><th scope="col" className="numeric">{t("stats.column.turns")}</th>
            <th scope="col" className="numeric">{t("stats.api_equivalent")}</th><th scope="col" className="numeric">{t("stats.column.duration")}</th></tr></thead>
          <tbody>{read.data.items.map(a => {
            const project = projectOf(a.root);
            return <tr key={a.attempt_id}>
              <td className="nowrap">{archive ? <Link to={{ name: "run-short", run: a.run_id }}>{when(a.started_at)}</Link> : project && a.purpose === "task"
                ? <Link to={{ name: "run", project, phase: a.phase_code, task: a.task_id, run: a.run_id }}>{when(a.started_at)}</Link> : when(a.started_at)}</td>
              {!scope.project && <td className="nowrap">{f.rootLabel(a.root, projects)}</td>}
              {!scope.task && <td className="mono nowrap">{a.task_id}{a.purpose !== "task" && <span className="muted"> · {purpose(a.purpose)}</span>}</td>}
              <td>{f.role(a.role)}<span className="muted"> #{a.number}</span></td>
              <td><span className="nowrap">{a.provider ?? <span className="muted">{t("stats.no_process")}</span>}{" "}
                <span className="mono" title={t("stats.requested")}>{a.requested_model ?? "—"}</span>{a.requested_effort && <span className="muted"> / {a.requested_effort}</span>}</span>
                {a.reported_models && <span className="cell-note" title={t("metrics.provenance.reported.title")}>{t("stats.used", { models: a.reported_models.join(", ") })}</span>}</td>
              <td><AttemptStatus value={a.status} />{a.verdict && <span className="cell-note">{a.verdict}</span>}{a.error && <p className="cell-error" title={a.error}>{a.error}</p>}</td>
              <td className="numeric nowrap">{f.count(a.total_tokens)} <Provenance of="total_tokens" row={a} /></td>
              <td className="numeric nowrap">{f.count(a.turns)} <Provenance of="turns" row={a} /></td>
              <td className="numeric nowrap">{f.usd(a.cost_usd)} <Provenance of="cost_usd" row={a} /></td>
              <td className="numeric nowrap">{f.duration(a.wall_ms, "ms")} <Provenance of="wall_ms" row={a} /></td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
    <Pagination offset={offset} next={read.data?.next_offset} onChange={setOffset} size={PAGE} label={t("stats.pages.attempts")} />
  </section>;
}
