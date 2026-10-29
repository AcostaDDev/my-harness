import { useState } from "react";
import type { ReactNode } from "react";
import { BarChart, ColumnChart, StackedColumns, useFormats } from "../charts";
import type { Datum, Stacked } from "../charts";
import { useArchive } from "../ServiceMode";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import type { S } from "../managed-api";
import { coverage } from "../metrics.ts";
import type { Sum } from "../metrics.ts";
import { Link } from "../navigation";
import { Empty, Loading, PageHeader, Pagination, Stale, Status, usePoll } from "../ui";
import { Attempts } from "./AttemptMetrics";
import { query } from "../metrics-query";
import type { Scope, Projects } from "../metrics-query";
import { PURPOSES } from "./shared";

// Statistics (H6.2 E6) over /api/managed/metrics/* (D074): each panel reads its resource, lists are paginated
// and null is shown as "no data", never as zero. The cost is the API equivalent the provider reports.

const INTERVAL = 15000;

/** Purpose of a run in the visual language; an unknown purpose is shown as is. */
function usePurpose() {
  const { t } = useI18n();
  return (purpose: string) => {
    const key = PURPOSES[purpose as keyof typeof PURPOSES] as MessageKey | undefined;
    return key ? t(key) : purpose;
  };
}

/** Sum with its coverage: "no data" if nobody contributes, a "partial" mark if only some attempts do. */
function Amount({ value, attempts, format }: { value: Sum; attempts: number; format?: (n: number | null) => string }) {
  const { t } = useI18n();
  const f = useFormats();
  const state = coverage(value, attempts);
  if (state === "absent") return <span className="muted" title={f.coverageText(value, attempts)}>{t("metrics.no_data")}</span>;
  return <span title={f.coverageText(value, attempts)}>{(format ?? f.count)(value.sum)}{state === "partial" && <sup className="partial"> {t("stats.partial")}</sup>}</span>;
}

function Tile({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return <div className="tile"><p className="tile-label">{label}</p><p className="tile-value">{value}</p>{children && <p className="tile-note">{children}</p>}</div>;
}

function TableView({ title, children }: { title: string; children: ReactNode }) {
  return <details className="chart-table"><summary>{title}</summary><div className="table-scroll" tabIndex={0} role="region" aria-label={title}>{children}</div></details>;
}

// --- page --------------------------------------------------------------------------------------

export function StatsPage({ project, refresh = 0 }: { project?: string; refresh?: number }) {
  const { t, n, rich } = useI18n();
  const archive = useArchive();
  const scope: Scope = { project };
  const summary = usePoll<S["MetricsSummaryRead"]>(`/metrics/summary${query(scope)}`, INTERVAL, refresh);
  const projects = usePoll<S["ManagedProjectRead"][]>(project ? null : "/projects", 0);
  const list: Projects = projects.data ?? [];
  const s = summary.data;
  return <>
    <PageHeader title={t("nav.stats")}>
      <p>{project ? t("stats.lede.project") : t("stats.lede.all")} {t("stats.lede.tokens")}</p>
      <p>{rich("stats.accounting", { link: <Link to={project ? { name: "project-accounting", project } : { name: "accounting" }}>{t("nav.accounting")}</Link> })}</p>
    </PageHeader>
    <Stale error={s ? summary.error : undefined} />
    {summary.missing ? <Empty title={t("project.missing", { project: project ?? "" })} />
      : !s ? summary.error ? <p role="alert" className="state state-error">{t("stats.read_failed", { error: summary.error })}</p> : <Loading />
        : <Headline summary={s} />}
    {s && s.attempts_without_metrics > 0 && <p className="state state-attention" role="status">
      {n("stats.without_metrics", s.attempts_without_metrics)} {!archive && rich("stats.backfill", { command: <code>my-harness metrics-backfill --database PATH</code> })}</p>}
    {s && <>
      <Consumption scope={scope} projects={list} refresh={refresh} />
      <Favorites scope={scope} refresh={refresh} />
      {project && <Tasks scope={scope} refresh={refresh} />}
      <TestsEvolution scope={scope} projects={list} refresh={refresh} />
      <Stops summary={s} />
      <Attempts scope={scope} projects={list} refresh={refresh} />
    </>}
  </>;
}

function Headline({ summary }: { summary: S["MetricsSummaryRead"] }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const c = summary.consumption;
  const tasks = summary.tasks;
  const tests = summary.tests;
  const cases = tests.cases;
  return <section className="tiles" aria-label={t("stats.summary")}>
    <Tile label={t("stats.tile.attempts")} value={f.count(c.attempts)}>
      {t("stats.tile.attempts_note", { terminal: c.accounting.terminal, messages: c.accounting.messages, absent: c.accounting.absent })}
    </Tile>
    <Tile label={t("stats.tile.tokens")} value={<Amount value={c.tokens.total_tokens} attempts={c.attempts} format={f.compact} />}>
      {f.coverageText(c.tokens.total_tokens, c.attempts)}
    </Tile>
    <Tile label={t("stats.api_equivalent")} value={<Amount value={c.cost_usd} attempts={c.attempts} format={f.usd} />}>
      {t("stats.tile.cost_note", { coverage: f.coverageText(c.cost_usd, c.attempts) })}
    </Tile>
    <Tile label={t("stats.agent_time")} value={<Amount value={c.attempt_wall_ms} attempts={c.attempts} format={v => f.duration(v, "ms")} />}>
      {t("stats.tile.time_note")}
    </Tile>
    <Tile label={t("stats.tile.first_time")} value={tasks.reviewed ? t("stats.of", { part: tasks.accepted_first_time, whole: tasks.reviewed }) : t("metrics.no_data")}>
      {tasks.reviewed ? t("stats.tile.first_time_note", { percent: f.percent(tasks.accepted_first_time, tasks.reviewed) }) : t("stats.tile.none_reviewed")}
    </Tile>
    <Tile label={t("stats.revisions")} value={tasks.corrections ? f.count(tasks.corrections.sum) : t("metrics.no_data")}>
      {tasks.corrections ? n("stats.tile.corrections_note", tasks.corrections.tasks) : t("stats.tile.none_executed")}
    </Tile>
    <Tile label={t("stats.to_commit")} value={tasks.seconds_to_commit ? f.duration(tasks.seconds_to_commit.sum / tasks.seconds_to_commit.tasks) : t("metrics.no_data")}>
      {tasks.seconds_to_commit ? n("stats.tile.commit_note", tasks.seconds_to_commit.tasks, { max: f.duration(tasks.seconds_to_commit.max) })
        : n("stats.tile.committed", tasks.committed)}
    </Tile>
    <Tile label={t("stats.tile.tests")} value={tests.tasks_with_validation ? t("stats.ok_ko", { ok: tests.commands_passed, ko: tests.commands_failed }) : t("metrics.no_data")}>
      {!tests.tasks_with_validation ? t("stats.tile.none_validated") : cases
        ? <>{n("stats.tile.commands_of", tests.tasks_with_validation)} · {t("stats.tile.junit", { ok: cases.passed, ko: cases.failed + cases.error })}{cases.skipped ? ` · ${n("stats.skipped", cases.skipped)}` : ""}</>
        : <>{n("stats.tile.commands_of", tests.tasks_with_validation)} · {t("stats.tile.no_junit")}</>}
    </Tile>
  </section>;
}

// --- consumption -------------------------------------------------------------------------------

type Dimension = S["MetricGroupsRead"]["dimension"] | "reported_model";
const DIMENSIONS: [Dimension, MessageKey, MessageKey][] = [
  ["phase", "stats.dimension.phase", "stats.consumption.hint.phase"],
  ["root", "stats.dimension.root", "stats.consumption.hint.root"],
  ["day", "stats.dimension.day", "stats.consumption.hint.day"],
  ["role", "stats.dimension.role", "stats.consumption.hint.role"],
  ["provider", "stats.dimension.provider", "stats.consumption.hint.provider"],
  ["requested_model", "stats.dimension.requested_model", "stats.consumption.hint.requested_model"],
  ["requested_effort", "stats.dimension.requested_effort", "stats.consumption.hint.requested_effort"],
  ["reported_model", "stats.dimension.reported_model", "stats.consumption.hint.reported_model"]];
const PAGE = 10;

function useKeyLabel() {
  const { t } = useI18n();
  const f = useFormats();
  return (dimension: Dimension, key: string | null, projects: Projects) => {
    if (dimension === "root") return f.rootLabel(key, projects);
    if (key == null) return t("common.undeclared");
    if (dimension === "role") return f.role(key);
    return key;
  };
}

function Consumption({ scope, projects, refresh }: { scope: Scope; projects: Projects; refresh: number }) {
  const { t } = useI18n();
  const choices = DIMENSIONS.filter(([value]) => scope.project ? value !== "root" : value !== "phase");
  const [dimension, setDimension] = useState<Dimension>(scope.project ? "phase" : "root");
  const [offset, setOffset] = useState(0);
  const day = dimension === "day";
  const size = day ? 30 : PAGE;
  const models = dimension === "reported_model";
  const path = models ? `/metrics/models${query(scope, { order: "tokens", offset, limit: size })}`
    : `/metrics/groups${query(scope, { dimension, order: day ? "key" : "tokens", offset, limit: size })}`;
  const read = usePoll<S["MetricGroupsRead"] | S["ModelMetricGroupsRead"]>(path, INTERVAL, refresh);
  // When the grouping changes, the previous read (another schema) remains in the first render: only the one
  // matching the chosen dimension is painted.
  const data = read.data?.dimension === dimension ? read.data : undefined;
  const choose = (value: Dimension) => { setDimension(value); setOffset(0); };
  const hint = choices.find(([value]) => value === dimension)![2];
  return <section className="panel" aria-labelledby="consumption">
    <div className="panel-head">
      <h2 id="consumption">{t("stats.consumption")}</h2>
      <label className="inline-select">{t("stats.group_by")}<select value={dimension} onChange={e => choose(e.target.value as Dimension)}>
        {choices.map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label>
    </div>
    <p className="hint">{t(hint)}</p>
    <Stale error={data ? read.error : undefined} />
    {!data ? <Loading /> : !data.items.length ? <Empty title={t("stats.no_attempts")} />
      : models ? <ModelConsumption groups={data as S["ModelMetricGroupsRead"]} />
        : <GroupConsumption groups={data as S["MetricGroupsRead"]} dimension={dimension} projects={projects} />}
    <Pagination offset={offset} next={data?.next_offset} onChange={setOffset} size={size} label={day ? t("stats.pages.days") : t("stats.pages.groups")} />
  </section>;
}

function GroupConsumption({ groups, dimension, projects }: { groups: S["MetricGroupsRead"]; dimension: Dimension; projects: Projects }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const keyLabel = useKeyLabel();
  const items = dimension === "day" ? [...groups.items].reverse() : groups.items;
  const data: Datum[] = items.map(g => {
    const label = keyLabel(dimension, g.key, projects);
    const total = g.tokens.total_tokens;
    return { key: String(g.key), label, value: total.sum,
      tip: [total.sum == null ? t("metrics.no_data") : t("stats.tokens", { value: f.count(total.sum) }), label,
        `${n("stats.attempts", g.attempts)} · ${f.coverageText(total, g.attempts)}`, t("stats.tip.cost", { value: f.usd(g.cost_usd.sum) })] };
  });
  return <>
    {dimension === "day" ? <ColumnChart data={data} label={t("stats.chart.day")} /> : <BarChart data={data} label={t("stats.chart.group")} />}
    <TableView title={t("stats.as_table")}>
      <table className="table">
        <thead><tr><th scope="col">{t("stats.column.group")}</th><th scope="col" className="numeric">{t("stats.column.attempts")}</th><th scope="col" className="numeric">{t("stats.column.uncached")}</th>
          <th scope="col" className="numeric">{t("stats.column.cache_read")}</th><th scope="col" className="numeric">{t("stats.column.cache_write")}</th><th scope="col" className="numeric">{t("stats.column.output")}</th>
          <th scope="col" className="numeric" title={t("stats.column.reasoning_hint")}>{t("stats.column.reasoning")}</th><th scope="col" className="numeric">{t("stats.column.total")}</th>
          <th scope="col" className="numeric" title={t("stats.column.turns_reported_hint")}>{t("stats.column.turns_reported")}</th><th scope="col" className="numeric" title={t("stats.column.turns_derived_hint")}>{t("stats.column.turns_derived")}</th>
          <th scope="col" className="numeric">{t("stats.api_equivalent")}</th><th scope="col" className="numeric">{t("stats.agent_time")}</th></tr></thead>
        <tbody>{items.map(g => <tr key={String(g.key)}>
          <th scope="row">{keyLabel(dimension, g.key, projects)}</th>
          <td className="numeric">{g.attempts}</td>
          {(["uncached_input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "total_tokens"] as const).map(name =>
            <td key={name} className="numeric"><Amount value={g.tokens[name]} attempts={g.attempts} /></td>)}
          <td className="numeric"><Amount value={g.turns_reported} attempts={g.attempts} /></td>
          <td className="numeric"><Amount value={g.turns_derived} attempts={g.attempts} /></td>
          <td className="numeric"><Amount value={g.cost_usd} attempts={g.attempts} format={f.usd} /></td>
          <td className="numeric"><Amount value={g.attempt_wall_ms} attempts={g.attempts} format={v => f.duration(v, "ms")} /></td>
        </tr>)}</tbody>
      </table>
    </TableView>
  </>;
}

function ModelConsumption({ groups }: { groups: S["ModelMetricGroupsRead"] }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const data: Datum[] = groups.items.map(g => ({ key: g.key, label: g.key, value: g.tokens.output_tokens.sum,
    tip: [g.tokens.output_tokens.sum == null ? t("metrics.no_data") : t("stats.output_tokens", { value: f.count(g.tokens.output_tokens.sum) }), g.key,
      n("stats.attempts", g.attempts), t("stats.tip.cost", { value: f.usd(g.cost_usd.sum) })] }));
  return <>
    <BarChart data={data} label={t("stats.chart.model")} />
    <TableView title={t("stats.as_table")}>
      <table className="table">
        <thead><tr><th scope="col">{t("stats.column.model")}</th><th scope="col" className="numeric">{t("stats.column.attempts")}</th><th scope="col" className="numeric">{t("stats.column.input")}</th>
          <th scope="col" className="numeric">{t("stats.column.cache_read")}</th><th scope="col" className="numeric">{t("stats.column.cache_write")}</th><th scope="col" className="numeric">{t("stats.column.output")}</th>
          <th scope="col" className="numeric">{t("stats.column.reasoning")}</th><th scope="col" className="numeric">{t("stats.api_equivalent")}</th></tr></thead>
        <tbody>{groups.items.map(g => <tr key={g.key}>
          <th scope="row" className="mono">{g.key}</th><td className="numeric">{g.attempts}</td>
          {(["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"] as const).map(name =>
            <td key={name} className="numeric"><Amount value={g.tokens[name]} attempts={g.attempts} /></td>)}
          <td className="numeric"><Amount value={g.cost_usd} attempts={g.attempts} format={f.usd} /></td>
        </tr>)}</tbody>
      </table>
    </TableView>
  </>;
}

// --- favorites by role -------------------------------------------------------------------------

function Favorites({ scope, refresh }: { scope: Scope; refresh: number }) {
  const { t } = useI18n();
  const f = useFormats();
  const [order, setOrder] = useState<"attempts" | "tokens">("attempts");
  const roles = usePoll<S["MetricGroupsRead"]>(`/metrics/groups${query(scope, { dimension: "role", order: "attempts", limit: 20 })}`, INTERVAL, refresh);
  return <section className="panel" aria-labelledby="favorites">
    <div className="panel-head">
      <h2 id="favorites">{t("stats.favorites")}</h2>
      <label className="inline-select">{t("stats.favorites.order")}<select value={order} onChange={e => setOrder(e.target.value as "attempts" | "tokens")}>
        <option value="attempts">{t("stats.favorites.by_attempts")}</option><option value="tokens">{t("stats.favorites.by_tokens")}</option></select></label>
    </div>
    <p className="hint">{t("stats.favorites.hint")}</p>
    {!roles.data ? <Loading /> : !roles.data.items.length ? <Empty title={t("stats.no_attempts")} />
      : <div className="table-scroll" tabIndex={0} role="region" aria-label={t("stats.favorites")}>
        <table className="table">
          <thead><tr><th scope="col">{t("stats.column.role")}</th><th scope="col" className="numeric">{t("stats.column.attempts")}</th><th scope="col">{t("settings.provider")}</th><th scope="col">{t("settings.model")}</th><th scope="col">{t("settings.effort")}</th></tr></thead>
          <tbody>{roles.data.items.map(r => r.key && <tr key={r.key}>
            <th scope="row">{f.role(r.key)}</th><td className="numeric">{r.attempts}</td>
            {(["provider", "requested_model", "requested_effort"] as const).map(dimension =>
              <td key={dimension}><Favorite scope={scope} role={r.key!} dimension={dimension} order={order} refresh={refresh} /></td>)}
          </tr>)}</tbody>
        </table>
      </div>}
  </section>;
}

function Favorite({ scope, role, dimension, order, refresh }: { scope: Scope; role: string; dimension: string; order: string; refresh: number }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const read = usePoll<S["MetricGroupsRead"]>(`/metrics/groups${query(scope, { dimension, role, order, limit: 2 })}`, INTERVAL, refresh);
  if (!read.data) return <span className="muted">…</span>;
  const [first, second] = read.data.items;
  if (!first) return <span className="muted">{t("metrics.no_data")}</span>;
  const metric = (g: S["MetricGroupRead"]) => order === "tokens" ? t("stats.tokens", { value: f.compact(g.tokens.total_tokens.sum) }) : n("stats.attempts", g.attempts);
  return <span><span className="mono">{first.key ?? t("common.undeclared")}</span> <span className="muted">({second
    ? t("stats.favorite.then", { metric: metric(first), next: second.key ?? t("common.undeclared") }) : metric(first)})</span></span>;
}

// --- tasks -------------------------------------------------------------------------------------

function Tasks({ scope, refresh }: { scope: Scope; refresh: number }) {
  const { t } = useI18n();
  const f = useFormats();
  const [offset, setOffset] = useState(0);
  const read = usePoll<S["Page_TaskMetricsRead_"]>(`/metrics/tasks${query(scope, { offset, limit: PAGE })}`, INTERVAL, refresh);
  return <section className="panel" aria-labelledby="task-quality">
    <h2 id="task-quality">{t("stats.tasks")}</h2>
    <p className="hint">{t("stats.tasks.hint")}</p>
    {!read.data ? <Loading /> : !read.data.items.length && !offset ? <Empty title={t("stats.tasks.empty")} />
      : <div className="table-scroll" tabIndex={0} role="region" aria-label={t("stats.tasks.table")}>
        <table className="table">
          <thead><tr><th scope="col">{t("runs.column.task")}</th><th scope="col">{t("runs.column.status")}</th><th scope="col">{t("stats.column.first_verdict")}</th><th scope="col" className="numeric">{t("stats.revisions")}</th>
            <th scope="col" className="numeric">{t("stats.to_commit")}</th><th scope="col">{t("stats.column.tests")}</th><th scope="col" className="numeric">{t("stats.column.tokens")}</th><th scope="col" className="numeric">{t("stats.stops")}</th></tr></thead>
          <tbody>{read.data.items.map(task => <tr key={`${task.phase_code}/${task.task_id}`}>
            <th scope="row"><Link className="mono" to={{ name: "task", project: scope.project!, phase: task.phase_code, task: task.task_id }}>{task.task_id}</Link></th>
            <td>{task.status ? <Status value={task.status} /> : <span className="muted">{t("stats.no_run")}</span>}</td>
            <td>{task.first_verdict ?? <span className="muted">{t("stats.no_review")}</span>}{task.accepted_first_time && <span className="muted"> {t("stats.first_time")}</span>}</td>
            <td className="numeric">{task.corrections ?? <span className="muted">{t("metrics.no_data")}</span>}</td>
            <td className="numeric">{task.seconds_to_commit == null ? <span className="muted">{t("stats.no_commit")}</span> : f.duration(task.seconds_to_commit)}</td>
            <td><TestCounts tests={task.tests} /></td>
            <td className="numeric"><Amount value={task.consumption.tokens.total_tokens} attempts={task.consumption.attempts} format={f.compact} /></td>
            <td className="numeric">{task.stops.length}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    <Pagination offset={offset} next={read.data?.next_offset} onChange={setOffset} size={PAGE} label={t("stats.pages.tasks")} />
  </section>;
}

function TestCounts({ tests }: { tests: S["ValidationCountsRead"] | null }) {
  const { t } = useI18n();
  if (!tests) return <span className="muted">{t("stats.not_validated")}</span>;
  const cases = tests.cases;
  return <span className="nowrap">
    <span className={tests.commands_failed ? "count-ko" : "count-ok"}>{tests.commands_failed ? "KO" : "OK"}</span>{" "}
    {t("stats.commands_ratio", { passed: tests.commands_passed, total: tests.commands_passed + tests.commands_failed })}
    {cases && <span className="muted"> · {t("stats.cases_ok_ko", { ok: cases.passed, ko: cases.failed + cases.error })}</span>}
  </span>;
}

// --- tests: trend ------------------------------------------------------------------------------

function TestsEvolution({ scope, projects, refresh }: { scope: Scope; projects: Projects; refresh: number }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const [offset, setOffset] = useState(0);
  const dimension = scope.project ? "phase" : "root";
  const read = usePoll<S["ValidationGroupsRead"]>(`/metrics/validations${query(scope, { dimension, offset, limit: 30 })}`, INTERVAL, refresh);
  const items = read.data ? [...read.data.items].reverse() : [];
  const label = (key: string) => dimension === "root" ? f.rootLabel(key, projects) : key;
  const data: Stacked[] = items.map(g => ({ key: g.key, label: label(g.key), ok: g.passed, ko: g.failed,
    tip: [t("stats.ok_ko", { ok: g.passed, ko: g.failed }), label(g.key),
      `${n("stats.validations", g.validations)} · ${t("stats.commands_ok_ko", { ok: g.commands_passed, ko: g.commands_failed })}`] }));
  return <section className="panel" aria-labelledby="tests-evolution">
    <h2 id="tests-evolution">{scope.project ? t("stats.tests.by_phase") : t("stats.tests.by_project")}</h2>
    <p className="hint">{t("stats.tests.hint")}</p>
    {!read.data ? <Loading /> : !items.length ? <Empty title={t("stats.tests.empty")} /> : <>
      <StackedColumns data={data} label={scope.project ? t("stats.chart.validations_phase") : t("stats.chart.validations_project")} />
      <TableView title={t("stats.as_table")}>
        <table className="table">
          <thead><tr><th scope="col">{dimension === "root" ? t("stats.dimension.root") : t("stats.dimension.phase")}</th><th scope="col" className="numeric">{t("stats.column.validations")}</th><th scope="col" className="numeric">OK</th>
            <th scope="col" className="numeric">KO</th><th scope="col" className="numeric">{t("stats.column.commands_ok")}</th><th scope="col" className="numeric">{t("stats.column.commands_ko")}</th><th scope="col">{t("stats.column.junit")}</th></tr></thead>
          <tbody>{items.map(g => <tr key={g.key}>
            <th scope="row">{dimension === "phase" && scope.project ? <Link className="mono" to={{ name: "phase", project: scope.project, phase: g.key }}>{g.key}</Link> : label(g.key)}</th>
            <td className="numeric">{g.validations}</td><td className="numeric">{g.passed}</td><td className="numeric">{g.failed}</td>
            <td className="numeric">{g.commands_passed}</td><td className="numeric">{g.commands_failed}</td>
            <td>{g.cases ? <>{t("stats.ok_ko", { ok: g.cases.passed, ko: g.cases.failed + g.cases.error })}{g.cases.skipped ? ` · ${n("stats.skipped", g.cases.skipped)}` : ""} ({n("stats.with_report", g.validations_with_cases)})</>
              : <span className="muted">{t("stats.no_readable_reports")}</span>}</td>
          </tr>)}</tbody>
        </table>
      </TableView>
    </>}
    <Pagination offset={offset} next={read.data?.next_offset} onChange={setOffset} size={30} label={t("stats.pages.validations")} />
  </section>;
}

// --- stops -------------------------------------------------------------------------------------

function Stops({ summary }: { summary: S["MetricsSummaryRead"] }) {
  const { t } = useI18n();
  const purpose = usePurpose();
  const stops = summary.stops;
  return <section className="panel" aria-labelledby="stops">
    <h2 id="stops">{t("stats.stops")}</h2>
    {!stops.items.length ? <Empty title={t("stats.stops.empty")} /> : <>
      <p className="hint">{stops.distinct > stops.items.length ? t("stats.stops.hint_partial", { shown: stops.items.length, distinct: stops.distinct }) : t("stats.stops.hint")}</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={t("stats.stops.table")}>
        <table className="table">
          <thead><tr><th scope="col" className="numeric">{t("stats.column.times")}</th><th scope="col">{t("runs.column.type")}</th><th scope="col">{t("stats.column.stage")}</th><th scope="col">{t("stats.column.reason")}</th></tr></thead>
          <tbody>{stops.items.map((item, index) => <tr key={index}>
            <td className="numeric">{item.count}</td><td>{purpose(item.purpose)}</td><td>{item.stage}</td><td className="wide">{item.reason}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
  </section>;
}

// --- task --------------------------------------------------------------------------------------

/** Metrics of a task (H6.2 E6): agents, attempts, tokens (failures included), turns and latest validation. */
export function TaskMetrics({ project, phase, task, refresh }: { project: string; phase: string; task: string; refresh: number }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const scope: Scope = { project, phase, task };
  const read = usePoll<S["Page_TaskMetricsRead_"]>(`/metrics/tasks${query(scope, { limit: 1 })}`, INTERVAL, refresh);
  const validations = usePoll<S["ValidationGroupsRead"]>(`/metrics/validations${query(scope, { dimension: "task" })}`, INTERVAL, refresh);
  const m = read.data?.items[0];
  if (!read.data) return <section className="panel"><h2>{t("stats.metrics")}</h2><Loading /></section>;
  if (!m) return null;
  const c = m.consumption;
  const all = validations.data?.items[0];
  return <>
    <section className="panel" aria-labelledby="task-metrics">
      <h2 id="task-metrics">{t("stats.metrics")}</h2>
      <div className="tiles tiles-compact">
        <Tile label={t("stats.column.attempts")} value={f.count(c.attempts)}>{Object.entries(m.attempts_by_role).map(([role, number]) => `${f.role(role)} ${number}`).join(" · ") || t("stats.none")}</Tile>
        <Tile label={t("stats.tile.tokens_failures")} value={<Amount value={c.tokens.total_tokens} attempts={c.attempts} format={f.compact} />}>{f.coverageText(c.tokens.total_tokens, c.attempts)}</Tile>
        <Tile label={t("stats.column.turns")} value={<>{c.turns_reported.sum != null && <><Amount value={c.turns_reported} attempts={c.attempts} /> <abbr className="provenance provenance-reported" title={t("metrics.provenance.reported.title")}>{t("metrics.provenance.reported.mark")}</abbr></>}
          {c.turns_reported.sum != null && c.turns_derived.sum != null && " · "}
          {c.turns_derived.sum != null && <><Amount value={c.turns_derived} attempts={c.attempts} /> <abbr className="provenance provenance-derived" title={t("metrics.provenance.derived.title")}>{t("metrics.provenance.derived.mark")}</abbr></>}
          {c.turns_reported.sum == null && c.turns_derived.sum == null && <span className="muted">{t("metrics.no_data")}</span>}</>}>
          {t("stats.tile.turns_note")}</Tile>
        <Tile label={t("stats.api_equivalent")} value={<Amount value={c.cost_usd} attempts={c.attempts} format={f.usd} />}>{f.coverageText(c.cost_usd, c.attempts)}</Tile>
        <Tile label={t("stats.revisions")} value={m.corrections == null ? t("metrics.no_data") : f.count(m.corrections)}>
          {n("stats.tile.executions", m.executions)} · {t("stats.tile.first_verdict", { verdict: m.first_verdict ?? t("stats.no_review") })}</Tile>
        <Tile label={t("stats.to_commit")} value={m.seconds_to_commit == null ? t("stats.no_commit") : f.duration(m.seconds_to_commit)}>
          {m.seconds_to_accept == null ? t("stats.tile.no_acceptance") : t("stats.tile.accepted_after", { duration: f.duration(m.seconds_to_accept) })}</Tile>
        <Tile label={t("stats.tile.latest_validation")} value={<TestCounts tests={m.tests} />}>
          {all ? n("stats.tile.validations_total", all.validations, { ok: all.passed, ko: all.failed }) : t("stats.tile.no_validations")}</Tile>
      </div>
      {m.agents.length > 0 && <>
        <h3>{t("settings.agents")}</h3>
        <div className="table-scroll" tabIndex={0} role="region" aria-label={t("stats.task_agents")}>
          <table className="table">
            <thead><tr><th scope="col">{t("stats.column.role")}</th><th scope="col">{t("settings.provider")}</th><th scope="col">{t("stats.dimension.requested_model")}</th><th scope="col">{t("settings.effort")}</th><th scope="col" className="numeric">{t("stats.column.attempts")}</th></tr></thead>
            <tbody>{m.agents.map((a, index) => <tr key={index}>
              <td>{f.role(a.role)}</td><td>{a.provider ?? <span className="muted">{t("stats.no_process")}</span>}</td>
              <td className="mono">{a.requested_model ?? "—"}</td><td>{a.requested_effort ?? "—"}</td><td className="numeric">{a.attempts}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </>}
      {m.stops.length > 0 && <>
        <h3>{t("stats.stops")}</h3>
        <ul className="checklist">{m.stops.map((stop, index) => <li key={index}><strong>{stop.stage}</strong>: {stop.reason}</li>)}</ul>
      </>}
    </section>
    <Attempts scope={scope} refresh={refresh} title={t("stats.attempts.task")} />
  </>;
}
