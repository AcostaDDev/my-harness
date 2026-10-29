import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { BASES, WORK, accountingQuery, activeFilters, ageDays, bucketState, captureFacts, counted, groupFilter, money,
  periodState, rateParts, reasonKey } from "../accounting.ts";
import type { Filters, Work } from "../accounting.ts";
import { useFormats } from "../charts";
import { useArchive } from "../ServiceMode";
import { useI18n } from "../Language";
import type { MessageKey, PluralKey } from "../i18n.ts";
import type { S } from "../managed-api";
import type { Projects, Scope } from "../metrics-query";
import { Link } from "../navigation";
import type { Route } from "../router.ts";
import { Empty, Evidence, Fields, Hash, Loading, PageHeader, Pagination, Stale, Status, usePoll, when } from "../ui";
import { PURPOSES } from "./shared";
import { ReferenceList } from "../BillingFields";

// Accounting (P001-T005a, D263) over /api/managed/accounting/* (D262): read-only, global or per project and
// available on a query-only archive. Valuations are calculated from pinned references; the client-reported
// estimate stays on Statistics and in each valuation's comparison, so the two never share a figure.

const INTERVAL = 15000;
const PAGE = 10;
const INVOCATIONS = 20;
const VALUATIONS = 5;

type Summary = S["AccountingSummaryRead"];
type AmountRead = S["AccountingAmountRead"];
type Invocation = S["AccountingInvocationRead"];
type Valuation = S["AccountingValuationRead"];
type Selection = { cohort?: string };

const TOKENS: [string, MessageKey][] = [
  ["uncached_input_tokens", "stats.column.uncached"], ["cache_read_tokens", "stats.column.cache_read"],
  ["cache_write_tokens", "stats.column.cache_write"], ["cache_write_5m_tokens", "accounting.tokens.write_5m"],
  ["cache_write_1h_tokens", "accounting.tokens.write_1h"], ["output_tokens", "stats.column.output"],
  ["reasoning_tokens", "stats.column.reasoning"]];
const SOURCES = ["managed_attempt", "preparation_step", "configuration_assistance"] as const;
const LAUNCHES = ["observed", "pending", "unknown_execution", "not_invoked"] as const;
const KINDS = ["reported", "mixed", "unknown"] as const;

/** Translated code from a `prefix.code` family; an unknown code is shown as is. */
function useCode() {
  const { t } = useI18n();
  const f = useFormats();
  return (family: "work" | "source" | "launch" | "kind" | "purpose" | "role" | "usage" | "status" | "origin", code: string | null | undefined) => {
    if (code == null) return t("common.undeclared");
    if (family === "role") return f.role(code);
    if (family === "purpose") return PURPOSES[code as keyof typeof PURPOSES] ? t(PURPOSES[code as keyof typeof PURPOSES]) : code;
    const known: Record<string, readonly string[]> = { work: WORK, source: SOURCES, launch: LAUNCHES, kind: KINDS,
      usage: ["complete", "partial", "absent"], status: ["complete", "incomplete", "unsupported"], origin: ["admission", "backfill", "repricing"] };
    return known[family].includes(code) ? t(`accounting.${family}.${code}` as MessageKey) : code;
  };
}

/** A calculator/selection code with its explanation; the code itself stays visible for searches. */
function Reason({ code, count }: { code: string; count?: number }) {
  const { t } = useI18n();
  const key = reasonKey(code);
  return <span className="chip" title={code}>{key ? t(key) : code}{count != null && <> · {count}</>} <code className="muted">{code}</code></span>;
}

function Reasons({ codes, empty }: { codes: string[] | [string, number][]; empty?: string }) {
  const { t } = useI18n();
  if (!codes.length) return <span className="muted">{empty ?? t("accounting.reasons.none")}</span>;
  return <span>{codes.map(item => Array.isArray(item) ? <Reason key={item[0]} code={item[0]} count={item[1]} /> : <Reason key={item} code={item} />)}</span>;
}

function Tile({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return <div className="tile"><p className="tile-label">{label}</p><p className="tile-value">{value}</p>{children && <p className="tile-note">{children}</p>}</div>;
}

function Scroll({ label, children }: { label: string; children: ReactNode }) {
  return <div className="table-scroll" tabIndex={0} role="region" aria-label={label}>{children}</div>;
}

/** Name of a bucket's basis with its product/scheme; counterfactual and retrospective are always said. */
function BucketName({ bucket }: { bucket: Pick<AmountRead, "basis" | "unit" | "scheme" | "platform" | "product" | "counterfactual" | "retrospective"> }) {
  const { t } = useI18n();
  return <span>
    <strong>{BASES[bucket.basis] ? t(BASES[bucket.basis]) : bucket.basis}</strong>
    {bucket.counterfactual && <> <span className="status status-attention" title={t("accounting.counterfactual.hint")}><span className="status-mark" aria-hidden="true" />{t("accounting.counterfactual")}</span></>}
    {bucket.retrospective && <> <span className="status status-neutral" title={t("accounting.retrospective.hint")}><span className="status-mark" aria-hidden="true" />{t("accounting.retrospective")}</span></>}
    <br /><span className="muted mono">{[bucket.product ?? bucket.platform, bucket.scheme].filter(Boolean).join(" · ")}</span>
  </span>;
}

/** The full amount only when the API gives it; otherwise the known subtotal marked partial, or "no data". */
function BucketAmount({ bucket, unit }: { bucket: { amount: string | null; known_subtotal: string | null }; unit: string }) {
  const { t, language } = useI18n();
  const { state, value } = bucketState(bucket);
  if (state === "absent") return <span className="muted">{t("metrics.no_data")}</span>;
  return <span className="nowrap" title={value ?? undefined}>{money(value, unit, language, t)}{state === "partial" && <sup className="partial" title={t("accounting.partial.hint")}> {t("accounting.partial")}</sup>}</span>;
}

function exact(value: string | null | undefined, unit: string, language: Parameters<typeof money>[2], t: Parameters<typeof money>[3]) {
  return value == null ? <span className="muted">{t("metrics.no_data")}</span> : <span className="nowrap" title={value}>{money(value, unit, language, t)}</span>;
}

// --- page --------------------------------------------------------------------------------------

export function AccountingPage({ project, refresh = 0 }: { project?: string; refresh?: number }) {
  const { t, rich } = useI18n();
  const scope: Scope = { project };
  const [filters, setFilters] = useState<Filters>({});
  const [selection, setSelection] = useState<Selection>({});
  const [selected, setSelected] = useState<string>();
  const summary = usePoll<Summary>(`/accounting/summary${accountingQuery(scope, filters, selection.cohort)}`, INTERVAL, refresh);
  const projects = usePoll<S["ManagedProjectRead"][]>(project ? null : "/projects", 0);
  const list: Projects = projects.data ?? [];
  const s = summary.data;
  const stats: Route = project ? { name: "project-stats", project } : { name: "stats" };
  // A new filter or selection starts every list at its first page (the key remounts them).
  const view = accountingQuery(scope, filters, selection.cohort);
  return <>
    <PageHeader title={t("nav.accounting")}>
      <p>{project ? t("accounting.lede.project") : t("accounting.lede.all")}</p>
      <p>{rich("accounting.lede.estimates", { link: <Link to={stats}>{t("nav.stats")}</Link> })}</p>
    </PageHeader>
    <SelectionPanel selection={selection} current={s?.selection} onChange={value => { setSelection(value); setSelected(undefined); }} refresh={refresh} />
    <FilterPanel project={project} filters={filters} effective={s?.filters} onChange={value => setFilters(value)} />
    <Stale error={s ? summary.error : undefined} />
    {summary.missing ? <Empty title={t("project.missing", { project: project ?? "" })} />
      : !s ? summary.error ? <p role="alert" className="state state-error">{t("accounting.read_failed", { error: summary.error })}</p> : <Loading />
        : <>
          <Coverage coverage={s.coverage} cohort={!!selection.cohort} />
          <Amounts amounts={s.amounts} complete={s.selection.complete} />
          <Tokens totals={s} />
          <TaskIndicators key={`tasks${view}`} scope={scope} filters={filters} selection={selection} refresh={refresh} />
          <Groups key={`groups${view}`} scope={scope} filters={filters} selection={selection} projects={list} refresh={refresh}
            onFilter={value => setFilters({ ...filters, ...value })} />
          <Invocations key={`invocations${view}`} scope={scope} filters={filters} selection={selection} projects={list} refresh={refresh}
            selected={selected} onSelect={setSelected} />
          {selected && <InvocationDetail key={`${selected}/${selection.cohort ?? ""}`} id={selected} cohort={selection.cohort} onClose={() => setSelected(undefined)} />}
        </>}
    {!project && <ReferenceList />}
  </>;
}

// --- selection policy ---------------------------------------------------------------------------

function SelectionPanel({ selection, current, onChange, refresh }: { selection: Selection; current?: S["AccountingSelectionRead"]; onChange: (value: Selection) => void; refresh: number }) {
  const { t, rich } = useI18n();
  const archive = useArchive();
  const [offset, setOffset] = useState(0);
  const cohorts = usePoll<S["Page_AccountingCohortRead_"]>(`/accounting/cohorts?offset=${offset}&limit=${PAGE}`, INTERVAL, refresh);
  const cohort = current?.cohort;
  return <section className="panel" aria-labelledby="accounting-selection">
    <h2 id="accounting-selection">{t("accounting.selection")}</h2>
    <p className="hint">{t("accounting.selection.hint")}</p>
    <p role="status" className={`state ${current && !current.complete ? "state-attention" : "state-neutral"}`}>
      {!current ? t("common.loading") : current.policy === "admission" ? t("accounting.selection.admission_current")
        : t("accounting.selection.cohort_current", { name: cohort?.name ?? "" })}
      {current && !current.complete && <> {t("accounting.selection.building")}</>}
    </p>
    {selection.cohort && <div className="actions"><button type="button" className="button-quiet" onClick={() => onChange({})}>{t("accounting.selection.use_admission")}</button></div>}
    <Stale error={cohorts.data ? cohorts.error : undefined} />
    {!cohorts.data ? <Loading /> : !cohorts.data.items.length && !offset ? <p className="hint">{t("accounting.cohorts.empty")}</p>
      : <Scroll label={t("accounting.cohorts")}>
        <table className="table">
          <thead><tr><th scope="col">{t("accounting.cohorts.name")}</th><th scope="col">{t("accounting.cohorts.kind")}</th><th scope="col">{t("runs.column.status")}</th>
            <th scope="col" className="numeric">{t("accounting.cohorts.built")}</th><th scope="col">{t("accounting.basis")}</th><th scope="col">{t("accounting.cohorts.created")}</th><th scope="col"><span className="visually-hidden">{t("accounting.cohorts.use")}</span></th></tr></thead>
          <tbody>{cohorts.data.items.map(item => {
            const chosen = selection.cohort === item.id;
            return <tr key={item.id}>
              <th scope="row" className="mono">{item.name}</th>
              <td>{t(item.kind === "backfill" ? "accounting.cohorts.backfill" : "accounting.cohorts.repricing")}{item.retrospective && <span className="muted"> · {t("accounting.retrospective")}</span>}</td>
              <td>{item.status === "BUILDING" ? <span className="status status-attention" title="BUILDING"><span className="status-mark" aria-hidden="true" />{t("accounting.cohorts.building")}</span>
                : <span className="status status-ok" title="CLOSED"><span className="status-mark" aria-hidden="true" />{t("accounting.cohorts.closed")}</span>}</td>
              <td className="numeric">{t("stats.of", { part: item.built, whole: item.expected })}</td>
              <td>{item.basis ? BASES[item.basis] ? t(BASES[item.basis]) : item.basis : <span className="muted">{t("accounting.cohorts.basis_admission")}</span>}</td>
              <td>{when(item.created_at)}</td>
              <td><button type="button" className="button-quiet" aria-pressed={chosen} onClick={() => onChange(chosen ? {} : { cohort: item.id })}
                aria-label={t(chosen ? "accounting.cohorts.in_use_named" : "accounting.cohorts.use_named", { name: item.name })}>
                {t(chosen ? "accounting.cohorts.in_use" : "accounting.cohorts.use")}</button></td>
            </tr>;
          })}</tbody>
        </table>
      </Scroll>}
    <Pagination offset={offset} next={cohorts.data?.next_offset} onChange={setOffset} size={PAGE} label={t("accounting.pages.cohorts")} />
    {!archive && <p className="hint">{rich("accounting.cohorts.commands", {
      backfill: <code>my-harness accounting-backfill --database PATH --name NAME</code>,
      reprice: <code>my-harness accounting-reprice --database PATH --name NAME --profile PROFILE --scenario retrospective</code> })}</p>}
  </section>;
}

// --- filters -----------------------------------------------------------------------------------

function FilterPanel({ project, filters, effective, onChange }: { project?: string; filters: Filters; effective?: S["AccountingFiltersRead"]; onChange: (value: Filters) => void }) {
  const { t } = useI18n();
  const code = useCode();
  const [draft, setDraft] = useState<Filters>(filters);
  // A filter applied from a group replaces the draft shown.
  useEffect(() => { setDraft(filters); }, [filters]);
  const set = (name: keyof Filters, value: string) => setDraft({ ...draft, [name]: value });
  const toggle = (work: Work, on: boolean) => setDraft({ ...draft, work: on ? [...(draft.work ?? []), work] : (draft.work ?? []).filter(item => item !== work) });
  const submit = (event: FormEvent) => { event.preventDefault(); onChange(draft); };
  const active = activeFilters(filters);
  const field = (name: "provider" | "role" | "purpose" | "outcome" | "requested_model" | "effective_model", label: MessageKey) =>
    <label key={name}>{t(label)}<input value={draft[name] ?? ""} onChange={e => set(name, e.target.value)} spellCheck={false} autoComplete="off" /></label>;
  const choice = (name: "source_kind" | "launch" | "effective_model_kind", label: MessageKey, values: readonly string[], family: "source" | "launch" | "kind") =>
    <label key={name}>{t(label)}<select value={draft[name] ?? ""} onChange={e => set(name, e.target.value)}>
      <option value="">{t("accounting.filters.any")}</option>{values.map(value => <option key={value} value={value}>{code(family, value)}</option>)}</select></label>;
  const phaseDefault = !!effective?.phase && !filters.work?.length;
  return <details className="panel panel-collapsible" open={active > 0 || undefined}>
    <summary><h2>{t("accounting.filters")}{active > 0 && <span className="count">{t("accounting.filters.active", { count: active })}</span>}</h2></summary>
    <form onSubmit={submit}>
      <div className="form-row">
        {project && <label>{t("stats.dimension.phase")}<input value={draft.phase ?? ""} onChange={e => set("phase", e.target.value)} spellCheck={false} /></label>}
        {project && <label>{t("runs.column.task")}<input value={draft.task ?? ""} onChange={e => set("task", e.target.value)} spellCheck={false} disabled={!draft.phase} /></label>}
        {field("provider", "settings.provider")}
        {field("role", "stats.column.role")}
        {field("purpose", "accounting.column.purpose")}
        {field("outcome", "accounting.column.outcome")}
        {field("requested_model", "stats.dimension.requested_model")}
        {field("effective_model", "accounting.dimension.effective_model")}
        {choice("effective_model_kind", "accounting.filters.model_kind", KINDS, "kind")}
        {choice("source_kind", "accounting.dimension.source_kind", SOURCES, "source")}
        {choice("launch", "accounting.dimension.launch", LAUNCHES, "launch")}
        <label>{t("accounting.filters.from")}<input type="date" value={draft.from_day ?? ""} onChange={e => set("from_day", e.target.value)} /></label>
        <label>{t("accounting.filters.until")}<input type="date" value={draft.until_day ?? ""} onChange={e => set("until_day", e.target.value)} /></label>
      </div>
      <fieldset>
        <legend>{t("accounting.dimension.work")}</legend>
        {WORK.map(work => <label key={work} className="check"><input type="checkbox" checked={draft.work?.includes(work) ?? false} onChange={e => toggle(work, e.target.checked)} />{code("work", work)}</label>)}
      </fieldset>
      <p className="hint">{t("accounting.filters.hint")}</p>
      {phaseDefault && <p className="hint" role="status">{t("accounting.filters.phase_default")}</p>}
      <div className="actions">
        <button type="submit">{t("accounting.filters.apply")}</button>
        <button type="button" className="button-quiet" disabled={!active && !activeFilters(draft)} onClick={() => { setDraft({}); onChange({}); }}>{t("accounting.filters.clear")}</button>
      </div>
    </form>
  </details>;
}

// --- summary -----------------------------------------------------------------------------------

function Coverage({ coverage: c, cohort }: { coverage: S["AccountingCoverageRead"]; cohort: boolean }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const unpriced = counted(c.unpriced_reasons);
  return <section className="panel" aria-labelledby="accounting-coverage">
    <h2 id="accounting-coverage">{t("accounting.coverage")}</h2>
    <p className="hint">{t("accounting.coverage.hint")}</p>
    <div className="tiles tiles-compact">
      <Tile label={t("accounting.coverage.expected")} value={f.count(c.expected)}>
        {n("accounting.coverage.invocations", c.invocations)} · {n("accounting.coverage.not_invoked", c.launch.not_invoked)}</Tile>
      <Tile label={t("accounting.coverage.launch")} value={t("stats.of", { part: c.launch.observed, whole: c.expected })}>
        {t("accounting.coverage.launch_note", { pending: c.launch.pending, unknown: c.launch.unknown_execution })}</Tile>
      <Tile label={t("accounting.coverage.captured")} value={t("stats.of", { part: c.captured, whole: c.expected })}>{t("accounting.coverage.captured_note")}</Tile>
      <Tile label={t("accounting.coverage.usage")} value={t("stats.of", { part: c.usage.complete, whole: c.expected })}>
        {t("accounting.coverage.usage_note", { partial: c.usage.partial, absent: c.usage.absent })}</Tile>
      <Tile label={t("accounting.coverage.priced")} value={t("stats.of", { part: c.valuation.complete, whole: c.expected })}>
        {t("accounting.coverage.priced_note", { incomplete: c.valuation.incomplete, unsupported: c.valuation.unsupported, unpriced: c.valuation.unpriced })}</Tile>
    </div>
    <p className={`state ${c.full_scope_priced ? "state-ok" : "state-attention"}`} role="status">
      {c.full_scope_priced ? t("accounting.coverage.full") : c.expected ? t("accounting.coverage.not_full") : t("accounting.coverage.none")}
      {cohort && c.outside_selection != null && <> {n("accounting.coverage.outside", c.outside_selection)}</>}
    </p>
    {unpriced.length > 0 && <><h3>{t("accounting.coverage.unpriced_reasons")}</h3><Reasons codes={unpriced} /></>}
  </section>;
}

function Amounts({ amounts, complete }: { amounts: AmountRead[]; complete: boolean }) {
  const { t, n } = useI18n();
  return <section className="panel" aria-labelledby="accounting-amounts">
    <h2 id="accounting-amounts">{t("accounting.amounts")}</h2>
    <p className="hint">{t("accounting.amounts.hint")}</p>
    {!complete && <p className="state state-attention" role="status">{t("accounting.selection.building")}</p>}
    {!amounts.length ? <Empty title={t("accounting.amounts.empty")} /> : <Scroll label={t("accounting.amounts")}>
      <table className="table">
        <thead><tr><th scope="col">{t("accounting.basis")}</th><th scope="col" className="numeric">{t("accounting.amount")}</th><th scope="col" className="numeric">{t("accounting.column.priced")}</th>
          <th scope="col">{t("accounting.column.reasons")}</th><th scope="col">{t("accounting.column.comparison")}</th></tr></thead>
        <tbody>{amounts.map((bucket, index) => <tr key={index}>
          <th scope="row"><BucketName bucket={bucket} /></th>
          <td className="numeric"><BucketAmount bucket={bucket} unit={bucket.unit} /></td>
          <td className="numeric nowrap">{t("stats.of", { part: bucket.complete, whole: bucket.denominator })}
            <br /><span className="muted">{t("accounting.amounts.incomplete", { incomplete: bucket.incomplete, unsupported: bucket.unsupported })}</span></td>
          <td><Reasons codes={counted(bucket.reasons)} /></td>
          <td>{counted(bucket.discrepancies).map(([status, count]) => <span key={status} className="chip" title={status}>{n(`accounting.discrepancy.count.${status === "compared" || status === "precision_unknown" || status === "not_comparable" ? status : "other"}` as PluralKey, count, { status })}</span>)}
            {!counted(bucket.discrepancies).length && <span className="muted">{t("accounting.discrepancy.none")}</span>}</td>
        </tr>)}</tbody>
      </table>
    </Scroll>}
  </section>;
}

function Tokens({ totals }: { totals: Summary }) {
  const { t, n, language } = useI18n();
  const f = useFormats();
  const expected = totals.coverage.expected;
  const hit = totals.cache_hit, speed = totals.wall_throughput;
  const rate = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 1 });
  return <section className="panel" aria-labelledby="accounting-tokens">
    <h2 id="accounting-tokens">{t("accounting.tokens")}</h2>
    <p className="hint">{t("accounting.tokens.hint")}</p>
    <div className="tiles tiles-compact">
      <Tile label={t("accounting.cache_hit")} value={hit.ratio == null ? t("metrics.no_data") : percent.format(hit.ratio)}>
        {t("accounting.cache_hit.note", { read: f.count(hit.cache_read_tokens), input: f.count(hit.input_tokens) })} · {n("accounting.indicator.over", hit.invocations, { excluded: hit.excluded })}</Tile>
      <Tile label={t("accounting.throughput")} value={speed.output_tokens_per_wall_second == null ? t("metrics.no_data") : t("accounting.throughput.value", { value: rate.format(speed.output_tokens_per_wall_second) })}>
        {t("accounting.throughput.note")} · {n("accounting.indicator.over", speed.invocations, { excluded: speed.excluded })}</Tile>
    </div>
    <Scroll label={t("accounting.tokens")}>
      <table className="table">
        <thead><tr><th scope="col">{t("accounting.tokens.category")}</th><th scope="col" className="numeric">{t("accounting.tokens.sum")}</th>
          <th scope="col" className="numeric">{t("accounting.tokens.contributors")}</th><th scope="col" className="numeric">{t("accounting.tokens.partial")}</th></tr></thead>
        <tbody>{TOKENS.map(([name, label]) => {
          const value = totals.tokens[name];
          return <tr key={name}>
            <th scope="row">{t(label)}</th>
            <td className="numeric">{value?.sum == null ? <span className="muted">{t("metrics.no_data")}</span> : <>{f.count(value.sum)}{(value.partial > 0 || value.invocations < expected) && <sup className="partial"> {t("accounting.partial")}</sup>}</>}</td>
            <td className="numeric">{t("stats.of", { part: value?.invocations ?? 0, whole: expected })}</td>
            <td className="numeric">{value?.partial ?? 0}</td>
          </tr>;
        })}</tbody>
      </table>
    </Scroll>
  </section>;
}

function TaskIndicators({ scope, filters, selection, refresh }: { scope: Scope; filters: Filters; selection: Selection; refresh: number }) {
  const { t, n, language } = useI18n();
  const read = usePoll<S["AccountingTasksRead"]>(`/accounting/tasks${accountingQuery(scope, filters, selection.cohort)}`, INTERVAL, refresh);
  const data = read.data;
  const pair = (value: S["AccountingAmountPairRead"], unit: string) => <BucketAmount bucket={value} unit={unit} />;
  return <section className="panel" aria-labelledby="accounting-tasks">
    <h2 id="accounting-tasks">{t("accounting.tasks")}</h2>
    <p className="hint">{t("accounting.tasks.hint")}</p>
    <Stale error={data ? read.error : undefined} />
    {!data ? <Loading /> : !data.tasks.attempted ? <Empty title={t("accounting.tasks.empty")} /> : <>
      <p>{n("accounting.tasks.attempted", data.tasks.attempted)} · {n("accounting.tasks.committed", data.tasks.committed)} · {n("accounting.tasks.not_committed", data.tasks.not_committed)}
        {data.tasks.acceptance_unknown > 0 && <> · <strong>{n("accounting.tasks.unknown", data.tasks.acceptance_unknown)}</strong></>}</p>
      {data.tasks.acceptance_unknown > 0 && <p className="state state-attention" role="status">{t("accounting.tasks.unknown_hint")}</p>}
      {!data.indicators.length ? <p className="hint">{t("accounting.amounts.empty")}</p> : <Scroll label={t("accounting.tasks")}>
        <table className="table">
          <thead><tr><th scope="col">{t("accounting.basis")}</th><th scope="col" className="numeric">{t("accounting.tasks.total")}</th>
            <th scope="col" className="numeric">{t("accounting.tasks.per_committed", { count: data.tasks.committed })}</th>
            <th scope="col" className="numeric">{t("accounting.tasks.per_attempted", { count: data.tasks.attempted })}</th>
            <th scope="col" className="numeric">{t("accounting.tasks.committed_work")}</th>
            <th scope="col" className="numeric">{t("accounting.tasks.committed_work_per_task", { count: data.tasks.committed })}</th></tr></thead>
          <tbody>{data.indicators.map((item, index) => <tr key={index}>
            <th scope="row"><BucketName bucket={item} /></th>
            <td className="numeric">{pair(item.total, item.unit)}</td>
            <td className="numeric">{exact(item.per_committed_task, item.unit, language, t)}</td>
            <td className="numeric">{exact(item.per_attempted_task, item.unit, language, t)}</td>
            <td className="numeric">{pair(item.committed_work, item.unit)}</td>
            <td className="numeric">{exact(item.committed_work_per_committed_task, item.unit, language, t)}</td>
          </tr>)}</tbody>
        </table>
      </Scroll>}
      <p className="hint">{t("accounting.tasks.denominators")}</p>
    </>}
  </section>;
}

// --- groups ------------------------------------------------------------------------------------

type Dimension = S["AccountingGroupsRead"]["dimension"];
const DIMENSIONS: [Dimension, MessageKey][] = [
  ["provider", "stats.dimension.provider"], ["effective_model", "accounting.dimension.effective_model"],
  ["requested_model", "stats.dimension.requested_model"], ["role", "stats.dimension.role"], ["purpose", "accounting.column.purpose"],
  ["work", "accounting.dimension.work"], ["source_kind", "accounting.dimension.source_kind"], ["root", "stats.dimension.root"],
  ["phase", "stats.dimension.phase"], ["task", "runs.column.task"], ["day", "stats.dimension.day"],
  ["outcome", "accounting.column.outcome"], ["launch", "accounting.dimension.launch"]];

function useGroupLabel() {
  const { t } = useI18n();
  const f = useFormats();
  const code = useCode();
  return (dimension: Dimension, group: S["AccountingGroupRead"], projects: Projects, project?: string) => {
    const { key, key_kind: kind } = group;
    const where = project ? "" : `${f.rootLabel(group.root, projects)} · `;
    if (dimension === "effective_model" && (kind === "mixed" || kind === "unknown")) return code("kind", kind);
    if (dimension === "root") return f.rootLabel(key, projects);
    if (key == null) return t("accounting.group.unknown");
    switch (dimension) {
      case "role": return code("role", key);
      case "purpose": return code("purpose", key);
      case "work": return code("work", key);
      case "source_kind": return code("source", key);
      case "launch": return code("launch", key);
      case "phase": return `${where}${key}`;
      case "task": return `${where}${group.phase_code ?? "?"}/${key}`;
      default: return key;
    }
  };
}

function Groups({ scope, filters, selection, projects, refresh, onFilter }: { scope: Scope; filters: Filters; selection: Selection; projects: Projects; refresh: number; onFilter: (value: Filters) => void }) {
  const { t } = useI18n();
  const f = useFormats();
  const label = useGroupLabel();
  const choices = DIMENSIONS.filter(([value]) => !(scope.project && value === "root"));
  const [dimension, setDimension] = useState<Dimension>("provider");
  const [order, setOrder] = useState<"invocations" | "key">("invocations");
  const [offset, setOffset] = useState(0);
  const read = usePoll<S["AccountingGroupsRead"]>(`/accounting/groups${accountingQuery(scope, filters, selection.cohort, { dimension, order, offset, limit: PAGE })}`, INTERVAL, refresh);
  const data = read.data?.dimension === dimension ? read.data : undefined;
  return <section className="panel" aria-labelledby="accounting-groups">
    <div className="panel-head">
      <h2 id="accounting-groups">{t("accounting.groups")}</h2>
      <div className="actions">
        <label className="inline-select">{t("stats.group_by")}<select value={dimension} onChange={e => { setDimension(e.target.value as Dimension); setOffset(0); }}>
          {choices.map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label>
        <label className="inline-select">{t("accounting.groups.order")}<select value={order} onChange={e => { setOrder(e.target.value as "invocations" | "key"); setOffset(0); }}>
          <option value="invocations">{t("accounting.groups.by_invocations")}</option><option value="key">{t("accounting.groups.by_key")}</option></select></label>
      </div>
    </div>
    <p className="hint">{t("accounting.groups.hint")}</p>
    <Stale error={data ? read.error : undefined} />
    {!data ? <Loading /> : !data.items.length ? <Empty title={t("accounting.invocations.empty")} /> : <Scroll label={t("accounting.groups")}>
      <table className="table">
        <thead><tr><th scope="col">{t("stats.column.group")}</th><th scope="col" className="numeric">{t("accounting.coverage.expected")}</th>
          <th scope="col" className="numeric">{t("accounting.coverage.usage")}</th><th scope="col" className="numeric">{t("accounting.column.priced")}</th>
          <th scope="col" className="numeric">{t("stats.column.output")}</th><th scope="col">{t("accounting.amounts")}</th><th scope="col"><span className="visually-hidden">{t("accounting.groups.filter")}</span></th></tr></thead>
        <tbody>{data.items.map(group => {
          const name = label(dimension, group, projects, scope.project);
          const narrow = groupFilter(dimension, group, scope.project);
          const output = group.tokens.output_tokens;
          return <tr key={`${group.key_kind}/${group.root}/${group.phase_code}/${group.key}`}>
            <th scope="row" className={dimension.endsWith("model") || dimension === "provider" ? "mono" : undefined}>{name}</th>
            <td className="numeric">{f.count(group.coverage.expected)}{group.coverage.launch.not_invoked > 0 && <span className="muted"> (+{group.coverage.launch.not_invoked})</span>}</td>
            <td className="numeric">{t("stats.of", { part: group.coverage.usage.complete, whole: group.coverage.expected })}</td>
            <td className="numeric">{t("stats.of", { part: group.coverage.valuation.complete, whole: group.coverage.expected })}</td>
            <td className="numeric">{output?.sum == null ? <span className="muted">{t("metrics.no_data")}</span> : f.compact(output.sum)}</td>
            <td>{!group.amounts.length ? <span className="muted">{t("metrics.no_data")}</span>
              : group.amounts.map((bucket, index) => <div key={index} className="nowrap">
                <span className="muted">{BASES[bucket.basis] ? t(BASES[bucket.basis]) : bucket.basis}{bucket.counterfactual && ` · ${t("accounting.counterfactual")}`}:</span> <BucketAmount bucket={bucket} unit={bucket.unit} /></div>)}</td>
            <td>{narrow && <button type="button" className="button-quiet" onClick={() => onFilter(narrow)} aria-label={t("accounting.groups.filter_named", { group: name })}>{t("accounting.groups.filter")}</button>}</td>
          </tr>;
        })}</tbody>
      </table>
    </Scroll>}
    <Pagination offset={offset} next={data?.next_offset} onChange={setOffset} size={PAGE} label={t("stats.pages.groups")} />
  </section>;
}

// --- invocations -------------------------------------------------------------------------------

/** Requested versus effective model: the requested model is never presented as the one that answered. */
function Models({ item }: { item: Pick<Invocation, "requested_model" | "effective_model" | "effective_model_kind"> }) {
  const { t } = useI18n();
  const code = useCode();
  return <span className="nowrap">
    <span className="mono" title={t("accounting.model.requested")}>{item.requested_model ?? t("common.undeclared")}</span>
    {" → "}
    {item.effective_model_kind === "reported" && item.effective_model ? <span className="mono" title={t("accounting.model.effective")}>{item.effective_model}</span>
      : <span className="muted">{code("kind", item.effective_model_kind)}</span>}
  </span>;
}

function Priced({ item }: { item: Invocation }) {
  const { t } = useI18n();
  const code = useCode();
  if (item.launch === "not_invoked") return <span className="muted">{t("accounting.invocation.not_expected")}</span>;
  if (!item.in_selection) return <span className="muted">{t("accounting.invocation.outside")}</span>;
  if (!item.valuations.length) return item.unpriced_reason ? <Reason code={item.unpriced_reason} /> : <span className="muted">{t("metrics.no_data")}</span>;
  return <>{item.valuations.map(v => <div key={v.id} className="nowrap">
    <BucketAmount bucket={v} unit={v.unit} /> <span className="muted">· {code("status", v.status)}{v.counterfactual && ` · ${t("accounting.counterfactual")}`}</span></div>)}</>;
}

function Invocations({ scope, filters, selection, projects, refresh, selected, onSelect }: { scope: Scope; filters: Filters; selection: Selection; projects: Projects; refresh: number; selected?: string; onSelect: (id: string) => void }) {
  const { t } = useI18n();
  const f = useFormats();
  const code = useCode();
  const [offset, setOffset] = useState(0);
  const read = usePoll<S["AccountingInvocationsRead"]>(`/accounting/invocations${accountingQuery(scope, filters, selection.cohort, { offset, limit: INVOCATIONS })}`, INTERVAL, refresh);
  const data = read.data;
  return <section className="panel" aria-labelledby="accounting-invocations">
    <h2 id="accounting-invocations">{t("accounting.invocations")}</h2>
    <p className="hint">{t("accounting.invocations.hint")}</p>
    <Stale error={data ? read.error : undefined} />
    {!data ? <Loading /> : !data.items.length && !offset ? <Empty title={t("accounting.invocations.empty")} /> : <Scroll label={t("accounting.invocations")}>
      <table className="table">
        <thead><tr><th scope="col">{t("stats.column.start")}</th>{!scope.project && <th scope="col">{t("stats.dimension.root")}</th>}<th scope="col">{t("accounting.column.work")}</th>
          <th scope="col">{t("stats.column.role")}</th><th scope="col">{t("settings.provider")}</th><th scope="col">{t("accounting.column.models")}</th>
          <th scope="col">{t("accounting.column.outcome")}</th><th scope="col">{t("accounting.coverage.usage")}</th><th scope="col">{t("accounting.column.valuation")}</th>
          <th scope="col"><span className="visually-hidden">{t("accounting.invocation.open")}</span></th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.id}>
          <td className="nowrap">{when(item.started_at)}</td>
          {!scope.project && <td>{f.rootLabel(item.root, projects)}</td>}
          <td>{code("work", item.work)}<br /><span className="muted">{item.task_id ? `${item.phase_code}/${item.task_id}` : code("purpose", item.purpose)}</span></td>
          <td>{code("role", item.role)}</td>
          <td className="mono">{item.provider ?? t("common.undeclared")}</td>
          <td><Models item={item} /></td>
          <td>{item.launch !== "observed" ? <span className="muted">{code("launch", item.launch)}</span> : item.outcome ? <Status value={item.outcome} /> : <span className="muted">{t("metrics.no_data")}</span>}</td>
          <td>{item.usage.coverage ? code("usage", item.usage.coverage) : <span className="muted">—</span>}</td>
          <td><Priced item={item} /></td>
          <td><button type="button" className="button-quiet" aria-pressed={selected === item.id} onClick={() => onSelect(item.id)}
            aria-label={t("accounting.invocation.open_named", { id: item.id.slice(0, 8) })}>{t("accounting.invocation.open")}</button></td>
        </tr>)}</tbody>
      </table>
    </Scroll>}
    <Pagination offset={offset} next={data?.next_offset} onChange={setOffset} size={INVOCATIONS} label={t("accounting.pages.invocations")} />
  </section>;
}

// --- invocation detail -------------------------------------------------------------------------

function runLink(item: Invocation): Route | undefined {
  if (item.run_id && item.project_id && item.phase_code && item.task_id) return { name: "run", project: item.project_id, phase: item.phase_code, task: item.task_id, run: item.run_id };
  return item.run_id ? { name: "run-short", run: item.run_id } : undefined;
}

function InvocationDetail({ id, cohort, onClose }: { id: string; cohort?: string; onClose: () => void }) {
  const { t, n } = useI18n();
  const f = useFormats();
  const code = useCode();
  const read = usePoll<S["AccountingInvocationDetailRead"]>(`/accounting/invocations/${encodeURIComponent(id)}${cohort ? `?cohort=${encodeURIComponent(cohort)}` : ""}`, 0);
  // Opening a detail moves the focus to its heading (keyboard and screen readers).
  useEffect(() => { globalThis.document?.getElementById?.("accounting-detail")?.focus?.(); }, [id]);
  const d = read.data;
  const facts = captureFacts(d?.capture_document?.document);
  const run = d && runLink(d);
  const none = <span className="muted">{t("metrics.no_data")}</span>;
  return <section className="panel" aria-labelledby="accounting-detail">
    <div className="panel-head">
      <h2 id="accounting-detail" tabIndex={-1}>{t("accounting.invocation.title", { id: id.slice(0, 8) })}</h2>
      <button type="button" className="button-quiet" onClick={onClose}>{t("accounting.invocation.close")}</button>
    </div>
    <Stale error={d ? read.error : undefined} />
    {read.missing ? <Empty title={t("accounting.invocation.missing")} /> : !d ? read.error ? <p role="alert" className="state state-error">{read.error}</p> : <Loading /> : <>
      <Fields items={[
        [t("accounting.dimension.source_kind"), <>{code("source", d.source_kind)}<br /><Hash value={d.source_id} /></>],
        [t("accounting.column.work"), <>{code("work", d.work)} · {code("purpose", d.purpose)}</>],
        [t("runs.column.task"), d.task_id ? `${d.phase_code}/${d.task_id}` : d.phase_code ?? none],
        [t("accounting.invocation.run"), run ? <Link to={run} className="mono">{d.run_id!.slice(0, 8)}</Link> : none],
        [t("stats.column.role"), <>{code("role", d.role)}{d.agent && <span className="muted"> · {d.agent}</span>}</>],
        [t("accounting.invocation.client"), <><span className="mono">{d.provider ?? t("common.undeclared")}</span>{facts.cli_version && <span className="muted"> · {facts.cli_version}</span>}</>],
        [t("accounting.model.requested"), <><span className="mono">{d.requested_model ?? t("common.undeclared")}</span>{d.requested_effort && <span className="muted"> · {d.requested_effort}</span>}</>],
        [t("accounting.model.effective"), <>{d.effective_model ? <span className="mono">{d.effective_model}</span> : none} <span className="muted">({code("kind", d.effective_model_kind)})</span></>],
        [t("accounting.model.reported_selection"), facts.reported_model ? <span className="mono" title={t("accounting.model.reported_selection_hint")}>{facts.reported_model}</span> : none],
        [t("accounting.dimension.launch"), code("launch", d.launch)],
        [t("accounting.column.outcome"), d.outcome ? <Status value={d.outcome} /> : none],
        [t("accounting.invocation.native_status"), facts.native_status ? <>{facts.native_status}{facts.exit_code != null && <span className="muted"> · {t("accounting.invocation.exit", { code: facts.exit_code })}</span>}</> : none],
        [t("stats.column.start"), when(d.started_at)],
        [t("accounting.invocation.finished"), when(d.finished_at)],
        [t("accounting.invocation.wall"), d.wall_ms == null ? none : f.duration(d.wall_ms, "ms")],
        [t("accounting.invocation.client_duration"), facts.duration_ms == null ? none : <>{f.duration(facts.duration_ms, "ms")}{facts.api_duration_ms != null && <span className="muted"> · {t("accounting.invocation.api_duration", { value: f.duration(facts.api_duration_ms, "ms") })}</span>}</>],
        [t("stats.column.turns"), facts.turns == null ? none : f.count(facts.turns)],
        [t("accounting.invocation.capture"), d.capture ? <>{d.capture.version} · {d.capture.source} · {when(d.capture.recorded_at)}<br /><span className="muted">{n("accounting.invocation.captures", d.captures)}</span></> : none],
      ]} />
      <h3>{t("accounting.invocation.tools")}</h3>
      {facts.tools?.length ? <p>{facts.tools.map(([name, number]) => <span key={name} className="chip"><span className="mono">{name}</span> × {number}</span>)}
        {facts.permission_denials ? <span className="muted"> · {n("accounting.invocation.denials", facts.permission_denials)}</span> : null}</p>
        : <p className="muted">{facts.tools ? t("accounting.invocation.no_tools") : t("accounting.invocation.tools_unreported")}</p>}
      <h3>{t("accounting.invocation.usage")}</h3>
      <p>{d.usage.coverage ? code("usage", d.usage.coverage) : t("accounting.invocation.not_expected")}
        {d.usage.partition && <span className="muted"> · {t("accounting.invocation.partition", { value: d.usage.partition })}</span>}
        {d.usage.delegation && <span className="muted"> · {t("accounting.invocation.delegation", { value: d.usage.delegation })}</span>}
        {d.usage.charges_complete === false && <span className="muted"> · {t("accounting.invocation.charges_incomplete")}</span>}</p>
      {d.usage.reasons.length > 0 && <p><Reasons codes={d.usage.reasons} /></p>}
      <Scroll label={t("accounting.invocation.usage")}>
        <table className="table">
          <thead><tr>{TOKENS.map(([name, label]) => <th key={name} scope="col" className="numeric">{t(label)}</th>)}</tr></thead>
          <tbody><tr>{TOKENS.map(([name]) => <td key={name} className="numeric">{d.usage.tokens[name] == null ? none : f.count(d.usage.tokens[name])}</td>)}</tr></tbody>
        </table>
      </Scroll>
      {d.components.length > 0 && <>
        <h3>{t("accounting.components")}</h3>
        <p className="hint">{t("accounting.components.hint")}</p>
        <Scroll label={t("accounting.components")}>
          <table className="table">
            <thead><tr><th scope="col">{t("accounting.components.key")}</th><th scope="col">{t("accounting.components.grain")}</th><th scope="col">{t("stats.column.model")}</th>
              <th scope="col">{t("accounting.coverage.usage")}</th><th scope="col" className="numeric">{t("stats.column.input")}</th><th scope="col" className="numeric">{t("stats.column.cache_read")}</th>
              <th scope="col" className="numeric">{t("stats.column.cache_write")}</th><th scope="col" className="numeric">{t("stats.column.output")}</th><th scope="col" className="numeric">{t("stats.column.reasoning")}</th>
              <th scope="col">{t("accounting.column.reasons")}</th></tr></thead>
            <tbody>{d.components.map(part => <tr key={part.key}>
              <th scope="row" className="mono">{part.key}{part.parent_key && <span className="muted"> ⊂ {part.parent_key}</span>}</th>
              <td>{part.grain}{part.inclusion && <span className="muted"> · {part.inclusion}</span>}</td>
              <td className="mono">{part.reported_model ?? <span className="muted">{t("common.undeclared")}</span>}{part.model_source && <span className="muted"> · {part.model_source}</span>}</td>
              <td>{code("usage", part.coverage)}</td>
              {(["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"] as const).map(name =>
                <td key={name} className="numeric">{part[name] == null ? none : f.count(part[name])}</td>)}
              <td><Reasons codes={part.reasons} /></td>
            </tr>)}</tbody>
          </table>
        </Scroll>
      </>}
      {facts.reported_cost && <p className="hint">{t(facts.reported_cost.legacy ? "accounting.invocation.reported_cost_legacy" : "accounting.invocation.reported_cost", { value: facts.reported_cost.value })}</p>}
      <Valuations id={id} cohort={d.selection.cohort?.id} chosen={d.valuations.map(v => v.id)} />
      {d.capture_document && <Evidence title={t("accounting.invocation.capture_document")} value={d.capture_document.document} />}
      <Evidence title={t("accounting.invocation.binding")} value={d.binding} />
    </>}
  </section>;
}

function Valuations({ id, cohort, chosen }: { id: string; cohort?: string; chosen: string[] }) {
  const { t } = useI18n();
  const [offset, setOffset] = useState(0);
  const read = usePoll<S["Page_AccountingValuationRead_"]>(`/accounting/invocations/${encodeURIComponent(id)}/valuations?offset=${offset}&limit=${VALUATIONS}`, 0);
  return <>
    <h3>{t("accounting.valuations")}</h3>
    <p className="hint">{t("accounting.valuations.hint")}</p>
    <Stale error={read.data ? read.error : undefined} />
    {!read.data ? <Loading /> : !read.data.items.length && !offset ? <p className="muted">{t("accounting.valuations.empty")}</p>
      : read.data.items.map(v => <ValuationView key={v.id} valuation={v} selected={chosen.includes(v.id)} cohort={cohort} />)}
    <Pagination offset={offset} next={read.data?.next_offset} onChange={setOffset} size={VALUATIONS} label={t("accounting.pages.valuations")} />
  </>;
}

function ValuationView({ valuation: v, selected, cohort }: { valuation: Valuation; selected: boolean; cohort?: string }) {
  const { t, n, language } = useI18n();
  const code = useCode();
  const period = periodState(v, v.references.length);
  const detail = v.discrepancy_detail as { status?: string; delta?: string | null; tolerance?: string | null; within_precision?: boolean | null; reasons?: string[]; reported?: { value?: string; representation?: string } } | null;
  const now = new Date();
  return <article className="panel" aria-label={t("accounting.valuation.label", { id: v.id.slice(0, 8) })}>
    <p><BucketName bucket={v} /></p>
    <p className="tile-value"><BucketAmount bucket={v} unit={v.unit} /></p>
    <p className="muted">{code("origin", v.origin)} · {code("status", v.status)} · {when(v.recorded_at)}
      {selected && <> · <strong>{t(cohort ? "accounting.valuation.selected_cohort" : "accounting.valuation.selected_admission")}</strong></>}
      {v.supersedes && <> · {t("accounting.valuation.supersedes", { id: v.supersedes.slice(0, 8) })}</>}</p>
    {v.cohorts.length > 0 && <p>{t("accounting.valuation.cohorts")} {v.cohorts.map(c => <span key={c.id} className="chip mono">{c.name}</span>)}</p>}
    <Fields items={[
      [t("accounting.valuation.exact_sum"), exact(v.exact_sum, v.unit, language, t)],
      [t("accounting.valuation.rounding"), v.rounding_adjustment == null ? <span className="muted">{t("metrics.no_data")}</span> : <span className="mono">{v.rounding_adjustment}</span>],
      [t("accounting.valuation.period"), period === "applies" ? t("accounting.period.applies") : <span className="status status-attention"><span className="status-mark" aria-hidden="true" />{t(`accounting.period.${period}` as MessageKey)}</span>],
      [t("accounting.column.reasons"), <Reasons codes={v.reasons} />],
      [t("accounting.valuation.warnings"), <Reasons codes={v.warnings} empty={t("accounting.reasons.no_warnings")} />],
    ]} />
    <h4>{t("accounting.column.comparison")}</h4>
    {!detail ? <p className="muted">{t("accounting.discrepancy.no_estimate")}</p> : <>
      <p>{t("accounting.discrepancy.reported", { value: detail.reported?.value ?? t("metrics.no_data") })}
        {detail.reported?.representation === "legacy_float" && <span className="muted"> · {t("accounting.reason.legacy_float")}</span>}</p>
      <p>{t(`accounting.discrepancy.${detail.status === "compared" || detail.status === "precision_unknown" ? detail.status : "not_comparable"}` as MessageKey,
        { delta: detail.delta ?? "", tolerance: detail.tolerance ?? "" })}
        {detail.status === "compared" && <> {t(detail.within_precision ? "accounting.discrepancy.within" : "accounting.discrepancy.outside")}</>}</p>
      {detail.reasons && detail.reasons.length > 0 && <p><Reasons codes={detail.reasons} /></p>}
    </>}
    <h4>{t("accounting.references")}</h4>
    {!v.references.length ? <p className="muted">{t("accounting.references.empty")}</p> : <Scroll label={t("accounting.references")}>
      <table className="table">
        <thead><tr><th scope="col">{t("accounting.references.id")}</th><th scope="col">{t("accounting.references.kind")}</th><th scope="col">{t("accounting.references.source")}</th>
          <th scope="col">{t("accounting.references.subject")}</th><th scope="col">{t("accounting.references.observed")}</th></tr></thead>
        <tbody>{v.references.map(ref => {
          const age = ageDays(ref.observed_at, now);
          return <tr key={ref.id}>
            <th scope="row"><Hash value={ref.id} /></th>
            <td>{t(ref.kind === "tariff" ? "accounting.references.tariff" : ref.kind === "model_identity" ? "accounting.references.identity" : "accounting.references.other", { kind: ref.kind })}</td>
            <td>{t(ref.source === "packaged" ? "accounting.references.packaged" : ref.source === "import" ? "accounting.references.imported" : "accounting.references.other", { kind: ref.source })}</td>
            <td className="mono">{[ref.provider, ref.product, ref.model].filter(Boolean).join(" · ")}</td>
            <td>{ref.observed_at ? <>{when(ref.observed_at)}{age != null && <span className="muted"> · {n("accounting.references.age", age)}</span>}</> : <span className="muted">{t("metrics.no_data")}</span>}</td>
          </tr>;
        })}</tbody>
      </table>
    </Scroll>}
    <h4>{t("accounting.lines")}</h4>
    {!v.lines.length ? <p className="muted">{t("accounting.lines.empty")}</p> : <Scroll label={t("accounting.lines")}>
      <table className="table">
        <thead><tr><th scope="col" className="numeric">#</th><th scope="col">{t("accounting.components.key")}</th><th scope="col">{t("accounting.tokens.category")}</th>
          <th scope="col" className="numeric">{t("accounting.lines.quantity")}</th><th scope="col">{t("accounting.lines.rate")}</th><th scope="col">{t("accounting.lines.case")}</th>
          <th scope="col">{t("accounting.lines.reference")}</th><th scope="col" className="numeric">{t("accounting.amount")}</th></tr></thead>
        <tbody>{v.lines.map(line => {
          const rate = rateParts(line.rate);
          return <tr key={line.number}>
            <td className="numeric">{line.number}</td><td className="mono">{line.component_key}</td><td className="mono">{line.category}</td>
            <td className="numeric">{new Intl.NumberFormat(language).format(line.quantity)}</td>
            <td className="nowrap">{rate ? t("accounting.lines.rate_value", { amount: money(rate.amount, v.unit, language, t), quantity: new Intl.NumberFormat(language).format(rate.quantity), unit: rate.unit })
              : <code className="inline-json">{JSON.stringify(line.rate)}</code>}
              {(line.factors.length > 0 || line.included_adjustments.length > 0) && <span className="muted"> · {t("accounting.lines.factors", { count: line.factors.length + line.included_adjustments.length })}</span>}</td>
            <td className="mono">{line.rate_case}</td>
            <td><Hash value={line.tariff_reference} />{line.identity_reference && <> · <Hash value={line.identity_reference} /></>}</td>
            <td className="numeric">{exact(line.exact_amount, v.unit, language, t)}</td>
          </tr>;
        })}</tbody>
      </table>
    </Scroll>}
    <Evidence title={t("accounting.valuation.evidence")} value={{ calculator: v.calculator, normalization: v.normalization, capture_id: v.capture_id,
      profile_digest: v.profile_digest, reference_set_digest: v.reference_set_digest, scenario_digest: v.scenario_digest,
      evidence_digest: v.evidence_digest, scenario: v.scenario, selected_components: v.selected_components, discrepancy: v.discrepancy_detail }} />
  </article>;
}
