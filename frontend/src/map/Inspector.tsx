// Inspector of the selected map element (T018 §3, D304; P002-T022): every field of the contract with its source.
// A counter without evidence reads "not observed" with its reason, never zero. Harness attempts, revision rounds,
// native turns, the requested model and the reported model are separate fields. Nothing here is a command: links go
// to existing pages and the requests button opens T017's conversation panel over the map.
import { useContext } from "react";
import type { ReactNode } from "react";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { Link, RouteBase, withBase } from "../navigation";
import { href } from "../router.ts";
import type { Route } from "../router.ts";
import { listHref } from "./view-mode.ts";
import { MapStatusBadge, when } from "../ui";
import { chatTitle, durationText, invocationRoute, observed, roleText, stepLabel } from "./projection.ts";
import type { Card, Circle, Counter, LevelItem, PhaseNode, Step, TaskNode, Texts } from "./projection.ts";
import type { S } from "../managed-api";
import type { ActorRole } from "./labels.ts";

type Bubbles = S["MapBubbles"];
const SOURCES = ["supplied", "reported", "derived", "measured", "absent"] as const;

export function Source({ source }: { source?: string | null }) {
  const { t } = useI18n();
  const known = SOURCES.includes(source as typeof SOURCES[number]);
  return <span className="map-source" title={known ? t(`map.source.${source as typeof SOURCES[number]}.title`) : undefined}>
    {known ? t(`map.source.${source as typeof SOURCES[number]}`) : source ?? t("map.source.absent")}</span>;
}

export function NotObserved({ reason }: { reason?: string | null }) {
  const { t } = useI18n();
  return <span className="muted">{t("map.not_observed")}{reason && <> (<code>{reason}</code>)</>}</span>;
}

/** A T020 counter: its value (rendered by `show`) and source, or "not observed" with its reason. */
export function CounterField({ counter, show }: { counter: Counter | null | undefined; show?: (value: unknown) => ReactNode }) {
  const value = observed(counter);
  if (value === undefined) return <><NotObserved reason={counter?.reason ?? "not_observed"} /> <Source source="absent" /></>;
  return <>{show ? show(value) : plain(value)} <Source source={counter!.source} /></>;
}

function plain(value: unknown): ReactNode {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value && typeof value === "object") return <code>{JSON.stringify(value)}</code>;
  return String(value);
}

function Rows({ items }: { items: [string, ReactNode][] }) {
  return <dl className="fields map-fields">{items.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="map-inspector-section"><h3>{title}</h3>{children}</section>;
}

function Code({ value }: { value?: string | null }) {
  const { t } = useI18n();
  return value ? <code>{value}</code> : <span className="muted">{t("common.not_recorded")}</span>;
}

function Circles({ circles, project }: { circles: readonly Circle[]; project: string }) {
  const { t, n } = useI18n();
  if (!circles.length) return <p className="muted">{t("map.inspector.no_circles")}</p>;
  return <ul className="map-circle-list">{circles.map(circle => {
    const actor = t(`map.actor.${circle.circle}`);
    return <li key={circle.circle}>
      <span className={`map-circle-chip${circle.active ? " map-circle-active" : ""}`} aria-hidden="true">{circle.circle}</span>{" "}
      <strong>{actor}</strong>
      {" · "}{t(`map.shown.${circle.shown}`)}
      {circle.active && <> · {n("map.inspector.active_invocations", circle.active_invocations || 1)}</>}
      {circle.chat && <> · {t("map.circle.chat")}</>}
      {circle.waiting && <> · {n("map.circle.requests", circle.bubbles, { actor })}</>}
      {circle.harness.length > 0 && <> · {circle.harness.map(work => work.stage ?? work.reason).join(", ")}</>}
      {" · "}{circle.latest_invocation
        ? <Link to={invocationRoute(project, circle.latest_invocation.invocation_id)}>{t("map.circle.open", { actor })}</Link>
        : <span className="muted">{t("map.circle.inert", { actor })}</span>}
    </li>;
  })}</ul>;
}

function ActiveInvocations({ items, project }: { items: readonly S["MapActiveInvocation"][]; project: string }) {
  const { t } = useI18n();
  if (!items.length) return <p className="muted">{t("map.inspector.none_active")}</p>;
  return <ul className="map-active-list">{items.map((item, i) => <li key={item.invocation_id ?? `${item.source_kind}:${i}`}>
    <span className="map-circle-chip map-circle-active" aria-hidden="true">{item.circle ?? "?"}</span>{" "}
    {roleText(item.role, t)}{item.number != null && <> #{item.number}</>}{item.chat && <> · {t("map.circle.chat")}</>}
    {" · "}<code>{item.lane}</code>{" · "}{item.agent ?? t("common.not_recorded")}{" · "}<code>{item.process}</code>
    {" · "}{when(item.started_at)}
    {item.invocation_id && <> · <Link to={invocationRoute(project, item.invocation_id)}>{t("map.inspector.open_invocation")}</Link></>}
  </li>)}</ul>;
}

function Errors({ errors }: { errors: readonly S["MapError"][] }) {
  const { t } = useI18n();
  if (!errors.length) return <p className="muted">{t("map.inspector.no_errors")}</p>;
  return <ul>{errors.map(error => <li key={`${error.kind}:${error.id}`}><code>{error.kind}</code> <code>{error.id}</code> <MapStatusBadge status={error.status} /></li>)}</ul>;
}

export function RequestsSummary({ bubbles, onOpen }: { bubbles: Bubbles; onOpen?: (role?: ActorRole) => void }) {
  const { t, n } = useI18n();
  if (!bubbles.total) return <p className="muted">{t("map.requests.none")}</p>;
  const kinds = Object.entries(bubbles.by_kind).map(([kind, count]) => `${t(`inbox.kind.${kind}` as MessageKey)} ${count}`).join(" · ");
  const circles = Object.entries(bubbles.by_circle).map(([circle, count]) => `${circle} ${count}`).join(" · ");
  return <>
    <p>{n("map.node.requests", bubbles.total)} <Source source={bubbles.source} /></p>
    <Rows items={[[t("map.requests.by_kind"), kinds], [t("map.requests.by_circle"), circles],
      ...(bubbles.unattributed ? [[t("map.requests.unattributed"), String(bubbles.unattributed)] as [string, ReactNode]] : [])]} />
    {onOpen && <button type="button" className="button-quiet" onClick={() => onOpen()}>{t("map.requests.open")}</button>}
  </>;
}

function Configuration({ card }: { card: Card }) {
  const { t } = useI18n();
  if (card.configuration_source === "absent" || !card.configuration) return <p className="muted">{t("map.inspector.configuration_absent")} <Source source="absent" /></p>;
  const config = card.configuration as Record<string, Record<string, unknown> | string | undefined>;
  const agent = (role: string) => {
    const value = config[role];
    if (!value || typeof value !== "object") return <span className="muted">{t("common.not_recorded")}</span>;
    const models = Array.isArray(value.models) ? (value.models as unknown[]).join(", ") : value.model;
    const efforts = Array.isArray(value.efforts) ? (value.efforts as unknown[]).join(", ") : value.effort;
    return <>{String(value.provider ?? t("common.undeclared"))} · <code>{String(models ?? "—")}</code> · {String(efforts ?? "—")}</>;
  };
  return <Rows items={[
    [t("map.actor.R"), agent("reviewer")], [t("map.role.planner"), agent("planner")], [t("map.actor.E"), agent("executor")],
    [t("map.actor.J"), config.judge ? agent("judge") : <span className="muted">{t("map.inspector.no_judge")}</span>],
  ]} />;
}

function ProjectFields({ card, project, onRequests }: { card: Card; project: string; onRequests?: (role?: ActorRole) => void }) {
  const { t } = useI18n();
  const run = card.mode.autonomous_run;
  return <>
    <Rows items={[
      [t("map.field.status"), <><MapStatusBadge status={card.status} /> <Source source="derived" /></>],
      [t("map.field.mode"), t(card.mode.kind === "autonomous" ? "map.mode.autonomous" : "map.mode.manual")],
      [t("map.field.autonomous_run"), run ? <><Code value={run.id} /> <MapStatusBadge status={run.status} />{run.reason && <> <code>{run.reason}</code></>}</> : <span className="muted">{t("map.inspector.no_autonomous")}</span>],
      ...(run?.bounds ? [[t("map.field.bounds"), <code className="map-json">{JSON.stringify(run.bounds)}</code>] as [string, ReactNode]] : []),
      [t("map.field.active_phase"), card.active_phase ? <><Code value={card.active_phase.code} /> {card.active_phase.title} <MapStatusBadge status={card.active_phase.status} /></> : <span className="muted">{t("map.card.no_open_phase")}</span>],
      [t("map.field.phases"), <CounterField counter={card.phases} show={value => `${value} / ${card.phases.total ?? "?"}`} />],
      [t("map.field.last_activity"), <CounterField counter={card.last_activity} show={value => when(String(value))} />],
      [t("map.field.identity"), <><Code value={card.id} />{card.knowledge_project_id && <> · <Code value={card.knowledge_project_id} /></>}{card.registered_project_id && <> · <Code value={card.registered_project_id} /></>}</>],
    ]} />
    <Section title={t("map.inspector.agents")}><Configuration card={card} /></Section>
    <Section title={t("map.inspector.circles")}><Circles circles={card.circles} project={project} /></Section>
    <Section title={t("map.inspector.active")}><ActiveInvocations items={card.active_invocations} project={project} /></Section>
    <Section title={t("map.inspector.errors")}><Errors errors={card.errors} /></Section>
    <Section title={t("map.inspector.requests")}><RequestsSummary bubbles={card.bubbles} onOpen={onRequests} /></Section>
  </>;
}

function Slot({ slot, project }: { slot: S["MapSlot"] | null | undefined; project: string }) {
  const { t } = useI18n();
  if (!slot) return <span className="muted">{t("map.slot.none")}</span>;
  return <><MapStatusBadge status={slot.status} /> {when(slot.finished_at ?? slot.created_at)}
    {slot.history > 1 && <> · {t("map.slot.history", { count: slot.history })}</>}
    {slot.actors.length > 0 && <ul className="map-slot-list">{slot.actors.map((actor, i) => <li key={`${actor.circle}:${i}`}>
      <span className="map-circle-chip" aria-hidden="true">{actor.circle}</span> {t(`map.actor.${actor.circle}`)}
      {actor.status && <> <MapStatusBadge status={actor.status} /></>}
      {actor.invocation_id && <> · <Link to={invocationRoute(project, actor.invocation_id)}>{t("map.inspector.open_invocation")}</Link></>}
    </li>)}</ul>}</>;
}

function PhaseFields({ phase, project, onRequests }: { phase: PhaseNode; project: string; onRequests?: (role?: ActorRole) => void }) {
  const { t } = useI18n();
  const covered = phase.criteria.covered as number | null | undefined;
  return <>
    <Rows items={[
      [t("map.field.status"), <MapStatusBadge status={phase.status} />],
      [t("map.field.origin"), t(`map.origin.${phase.origin}`)],
      ...(phase.instance ? [[t("map.field.instance"), <><code>{phase.instance.status}</code> · v{phase.instance.version}</>] as [string, ReactNode]] : []),
      [t("map.field.objective"), phase.objective ?? <span className="muted">{t("common.not_recorded")}</span>],
      [t("map.field.criteria"), <CounterField counter={phase.criteria} show={value => covered != null ? t("map.field.criteria_covered", { count: Number(value), covered }) : String(value)} />],
      [t("map.field.ready"), phase.ready ? t("common.yes") : t("common.no")],
      [t("map.field.last_check"), <Slot slot={phase.last_check} project={project} />],
      [t("map.field.tasks"), <CounterField counter={phase.tasks} show={value => `${value} / ${phase.tasks.total ?? "?"}`} />],
      ...(phase.tag ? [[t("map.field.tag"), <code>{phase.tag}</code>] as [string, ReactNode]] : []),
    ]} />
    <Section title={t("map.inspector.slots")}><Rows items={(["plan", "check", "close"] as const).map(key => [t(`map.slot.${key}`), <Slot slot={phase.slots[key]} project={project} />])} /></Section>
    <Section title={t("map.inspector.circles")}><Circles circles={phase.circles} project={project} /></Section>
    <Section title={t("map.inspector.active")}><ActiveInvocations items={phase.active_invocations} project={project} /></Section>
    <Section title={t("map.inspector.errors")}><Errors errors={phase.errors} /></Section>
    <Section title={t("map.inspector.requests")}><RequestsSummary bubbles={phase.bubbles} onOpen={onRequests} /></Section>
  </>;
}

function Text({ value }: { value: S["MapText"] }) {
  const { t } = useI18n();
  if (value.value == null) return <><NotObserved reason={value.reason} /> <Source source={value.source} /></>;
  return <>{value.value}{value.truncated && <span className="muted"> {t("map.field.truncated")}</span>} <Source source={value.source} /></>;
}

function TaskFields({ task, project, phase, onRequests }: { task: TaskNode; project: string; phase: string; onRequests?: (role?: ActorRole) => void }) {
  const { t } = useI18n();
  const latest = task.latest;
  const runStatus = (task.status as { run_status?: string | null }).run_status;
  const runRoute: Route | undefined = latest ? { name: "run", project, phase, task: task.code, run: latest.run_id } : undefined;
  const codes = (items: readonly string[]) => items.length ? items.map(code => <code key={code}>{code} </code>) : <span className="muted">—</span>;
  return <>
    <Rows items={[
      [t("map.field.status"), <><MapStatusBadge status={task.status} />{runStatus && <> · {t("map.field.run_status", { code: runStatus })}</>}</>],
      [t("map.field.in_plan"), task.in_plan ? t("common.yes") : t("common.no")],
      [t("map.field.problem"), <Text value={task.problem} />],
      [t("map.field.expected_result"), <Text value={task.expected_result} />],
      [t("map.field.runs"), String(task.runs)],
      [t("map.field.depends_on"), codes(task.depends_on)],
      [t("map.field.replaces"), codes(task.replaces)],
      [t("map.field.replaced_by"), codes(task.replaced_by)],
    ]} />
    <Section title={t("map.inspector.latest_run")}>{latest && runRoute ? <Rows items={[
      [t("map.field.run"), <Link to={runRoute} className="mono">{latest.run_id.slice(0, 12)}</Link>],
      [t("map.field.status"), <MapStatusBadge status={latest.status} />],
      [t("map.field.stage"), <code>{latest.stage}</code>],
      [t("map.field.attempts"), <CounterField counter={latest.attempts} show={value => t("map.field.attempts_value", { value: String(value), limit: String(latest.attempts.revision_limit ?? "?") })} />],
      [t("map.field.revision_rounds"), <>{latest.revisions} <Source source="supplied" /></>],
      [t("map.field.cycles"), latest.cycles == null ? <NotObserved reason="no_projection" /> : String(latest.cycles)],
      [t("map.field.acceptance"), <>{t(`map.acceptance.${latest.acceptance.state}`)} <Source source={latest.acceptance.source} />
        {latest.acceptance.reasons.length > 0 && <ul>{latest.acceptance.reasons.map(reason => <li key={reason}><code>{reason}</code></li>)}</ul>}</>],
      [t("map.field.commit"), latest.commit ? <><MapStatusBadge status={latest.commit.status} /> <Code value={latest.commit.commit?.slice(0, 12)} /></> : <span className="muted">{t("map.field.no_commit")}</span>],
    ]} /> : <p className="muted">{t("map.counter.no_runs")}</p>}</Section>
    <Section title={t("map.inspector.circles")}><Circles circles={task.circles} project={project} /></Section>
    <Section title={t("map.inspector.active")}><ActiveInvocations items={task.active_invocations} project={project} /></Section>
    <Section title={t("map.inspector.errors")}><Errors errors={task.errors} /></Section>
    <Section title={t("map.inspector.requests")}><RequestsSummary bubbles={task.bubbles} onOpen={onRequests} /></Section>
  </>;
}

type Observation = { source?: string; persisted?: boolean; counters?: Record<string, Counter & { coverage?: string; by_name?: Record<string, number> }>; usage?: Record<string, unknown>; missing?: { signal: string; reason: string }[] };

/** Every field of one L3 step (also the L4 header's step). */
export function StepFields({ step, project, texts }: { step: Step; project: string; texts: Texts }) {
  const { t } = useI18n();
  const extra = step as Step & { started_at?: string | null; finished_at?: string | null; cycle?: number; evidence?: Record<string, unknown>; termination?: Record<string, unknown> | null; launch?: S["MapStatus"] | null; status: S["MapStatus"] & { process?: string | null } };
  if (step.kind === "harness") {
    const evidence = extra.evidence ?? {};
    return <Rows items={[
      [t("map.field.stage"), stepLabel(step, t)],
      [t("map.field.status"), <MapStatusBadge status={step.status} />],
      ...(extra.cycle != null ? [[t("map.field.cycle"), String(extra.cycle + 1)] as [string, ReactNode]] : []),
      [t("map.field.duration"), <CounterField counter={step.duration_ms} show={() => durationText(step, texts)} />],
      ...((step.duration_ms as { includes?: string[] }).includes?.length ? [[t("map.field.includes"), (step.duration_ms as { includes?: string[] }).includes!.join(", ")] as [string, ReactNode]] : []),
      [t("map.field.started"), when(extra.started_at)], [t("map.field.finished"), when(extra.finished_at)],
      [t("map.field.evidence"), Object.keys(evidence).length ? <code className="map-json">{JSON.stringify(evidence)}</code> : <NotObserved />],
    ]} />;
  }
  const identity = (step.identity ?? {}) as Record<string, string | null | undefined>;
  const observation = (step.observation ?? null) as Observation | null;
  const counters = observation?.counters ?? {};
  const records = step.records ?? {};
  const stepsState = (step.steps ?? {}) as { state?: string; reason?: string | null };
  const termination = extra.termination as { class?: string; source?: string; reason?: string } | null | undefined;
  const reported = step.reported_model as (Counter & { provenance?: unknown }) | null | undefined;
  const native = (name: string) => <CounterField counter={counters[name]} show={value => <>{String(value)}{counters[name]?.coverage && counters[name]!.coverage !== "complete" ? <span className="muted"> ({counters[name]!.coverage})</span> : null}</>} />;
  return <>
    <Rows items={[
      [t("map.field.status"), <><MapStatusBadge status={step.status} />{extra.status.process && <> · <code>{extra.status.process}</code></>}</>],
      [t("map.field.harness_attempt"), <CounterField counter={step.harness_attempt} />],
      [t("map.field.revision_round"), <CounterField counter={step.revision_round} />],
      [t("map.field.duration"), <CounterField counter={step.duration_ms} show={() => durationText(step, texts)} />],
      [t("map.field.started"), when(extra.started_at)], [t("map.field.finished"), when(extra.finished_at)],
      [t("map.field.launch"), extra.launch ? <MapStatusBadge status={extra.launch} /> : <NotObserved reason="no_ledger_row" />],
      [t("map.field.termination"), termination?.class ? <><code>{termination.class}</code> <Source source={termination.source} />{termination.reason && <> (<code>{termination.reason}</code>)</>}</> : <NotObserved reason={termination?.reason ?? "no_observation"} />],
    ]} />
    <Section title={t("map.inspector.identity")}><Rows items={[
      [t("map.field.agent"), <Code value={identity.agent} />], [t("map.field.client"), <Code value={identity.client} />],
      [t("map.field.client_version"), <Code value={identity.client_version} />], [t("map.field.adapter_version"), <Code value={identity.adapter_version} />],
      [t("map.field.requested_model"), <Code value={identity.requested_model} />], [t("map.field.requested_effort"), <Code value={identity.requested_effort} />],
      [t("map.field.reported_model"), <CounterField counter={reported} />],
      [t("map.field.identity_source"), <Source source={identity.source} />],
    ]} /></Section>
    <Section title={t("map.inspector.telemetry")}>{observation ? <Rows items={[
      [t("map.field.native_turns"), native("native_turns")],
      [t("map.field.tool_calls"), <>{native("tool_calls")}{counters.tool_calls?.by_name && Object.keys(counters.tool_calls.by_name).length > 0 &&
        <ul>{Object.entries(counters.tool_calls.by_name).map(([name, count]) => <li key={name}><code>{name}</code> {count}</li>)}</ul>}</>],
      [t("map.field.permission_denials"), native("permission_denials")],
      [t("map.field.usage"), observation.usage?.view ? <><code>{String(observation.usage.view)}</code> <Source source={String(observation.usage.source)} /> ({String(observation.usage.coverage)})</> : <><NotObserved reason={String(observation.usage?.reason ?? "not_observed")} /> <Source source="absent" /></>],
      [t("map.field.observation_source"), <><code>{observation.source}</code>{observation.persisted ? "" : <span className="muted"> {t("map.field.not_persisted")}</span>}</>],
      ...(observation.missing?.length ? [[t("map.field.missing"), <ul>{observation.missing.map(item => <li key={item.signal}><code>{item.signal}</code> · <code>{item.reason}</code></li>)}</ul>] as [string, ReactNode]] : []),
    ]} /> : <p><NotObserved reason="no_observation" /> <Source source="absent" /></p>}</Section>
    <Section title={t("map.inspector.records")}><Rows items={(["deliveries", "discovery", "rulings", "permission_requests"] as const).map(name =>
      [t(`map.field.${name}`), <CounterField counter={records[name]} />])} /></Section>
    <Section title={t("map.inspector.observed_steps")}><p>{stepsState.state ? <><code>{stepsState.state}</code>{stepsState.reason && <> · <code>{stepsState.reason}</code></>} · {t(`map.steps_state.${stepsState.state}` as MessageKey)}</> : <NotObserved />}</p></Section>
    {step.invocation_id && <p><Link to={invocationRoute(project, step.invocation_id)}>{t("map.inspector.open_invocation")}</Link></p>}
  </>;
}

/**
 * Link to a run's evidence: the existing run page with its evidence and controls (`?view=list`, so a remembered map
 * choice does not turn it back into the map, and the choice itself is kept), or the archive's run consultation.
 * Without a task context the short run URL resolves the canonical one and keeps the query.
 */
export function EvidenceLink({ project, run, phase, task, archive }: { project: string; run: string; phase?: string | null; task?: string | null; archive: boolean }) {
  const { t } = useI18n();
  const base = useContext(RouteBase);
  const route: Route = !archive && phase && task ? { name: "run", project, phase, task, run } : { name: "run-short", run };
  // Archives: `/runs/:id` is the read-only run consultation itself (never a map level there).
  return <Link to={withBase(base, archive ? href(route) : listHref(route))}>{t("map.summary.evidence")}</Link>;
}

export type InspectorProps = {
  item?: LevelItem;
  texts: Texts;
  onRequests?: (role?: ActorRole) => void;
  summary?: ReactNode;
};

/** Fields of the selected element, or the level summary when nothing is selected. */
export function InspectorBody({ item, texts, onRequests, summary }: InspectorProps) {
  const { t } = useI18n();
  if (!item) return <>{summary}<p className="muted">{t("map.inspector.hint")}</p></>;
  switch (item.level) {
    case 0: return <ProjectFields card={item.item} project={item.project} onRequests={onRequests} />;
    case 1: return <PhaseFields phase={item.item} project={item.project} onRequests={onRequests} />;
    case 2: return <TaskFields task={item.item} project={item.project} phase={item.phase} onRequests={onRequests} />;
    case 3: return item.chat ? <>
      <p className="hint">{t("map.chat.hint")}</p>
      <Section title={t("map.inspector.active")}><ActiveInvocations items={[item.item]} project={item.project} /></Section>
    </> : <>
      <StepFields step={item.item} project={item.project} texts={texts} />
      {item.item.bubbles && <Section title={t("map.inspector.requests")}><RequestsSummary bubbles={item.item.bubbles} onOpen={onRequests} /></Section>}
    </>;
  }
}

export function itemTitle(item: LevelItem, t: Texts["t"]): string {
  switch (item.level) {
    case 0: return item.item.name;
    case 1: return item.item.title ? `${item.item.code} · ${item.item.title}` : item.item.code;
    case 2: return item.item.title ? `${item.item.code} · ${item.item.title}` : item.item.code;
    case 3: return item.chat ? `${t("map.chat.lane")} · ${chatTitle(item.item, t)}` : stepLabel(item.item, t);
  }
}
