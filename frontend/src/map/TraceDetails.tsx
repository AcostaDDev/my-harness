import { useState } from "react";
import { useI18n } from "../Language";
import { managed } from "../managed-api";
import type { S } from "../managed-api";
import { Alert, MapStatusBadge, message, when } from "../ui";
import { NotObserved, Source } from "./Inspector";
import { sourcePath, traceTitle, tracePosition } from "./trace.ts";
import type { TraceItem } from "./trace.ts";

/** Original reads are explicit and independent of projection refresh; unmounting discards route-local content. */
export function OriginalRead({ path, label, source }: { path: string; label: string; source?: S["MapSourceRecord"] }) {
  const { t } = useI18n();
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true); setError(undefined);
    try {
      const data = await managed<unknown>(path);
      if (source) {
        const items = (data as S["ManagedEventsRead"]).items;
        const event = items?.find(item => item.sequence === source.sequence && item.kind === "agent_event"
          && item.payload.attempt_id === source.attempt_id);
        if (!event) throw new Error(t("trace.source_mismatch"));
        setResult(event);
      } else setResult(data);
    } catch (error) { setError(message(error)); }
    finally { setBusy(false); }
  }
  return <div className="trace-original">
    <button type="button" className="button-quiet" disabled={busy} onClick={() => void load()}>{label}</button>
    {error && <Alert>{error}</Alert>}
    {result !== undefined && <><button type="button" className="button-quiet" onClick={() => setResult(undefined)}>{t("common.close")}</button>
      <pre className="trace-json" tabIndex={0}>{JSON.stringify(result, null, 2)}</pre></>}
  </div>;
}
const STEP_FIELDS = ["unit", "parent_seq", "call_id", "tool", "origin", "outcome", "status_code", "reason", "parallel", "max_concurrency",
  "started_at", "finished_at", "duration_ms", "timing", "arguments", "result", "message", "reasoning", "source_record_count", "bound", "remaining", "remaining_total", "event_type", "detail", "record_size", "record_sha256", "stream_record", "client"];

export function LogOriginalRead({ source }: { source: S["MapSourceRecord"] }) {
  const { t } = useI18n();
  const [result, setResult] = useState<S["ManagedOriginalRead"]>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true); setError(undefined); setResult(undefined);
    try {
      const data = await managed<S["ManagedOriginalRead"]>(`${sourcePath(source.log!)}?sequence=${source.sequence}`);
      if (data.run_id !== source.run_id || data.attempt_id !== source.attempt_id || data.sequence !== source.sequence
        || data.sha256 !== source.log?.sha256 || data.size_bytes !== source.log?.size || data.offset !== source.log?.offset)
        throw new Error(t("trace.source_mismatch"));
      setResult(data);
    } catch (error) { setError(message(error)); }
    finally { setBusy(false); }
  }
  return <div className="trace-original">
    <button type="button" className="button-quiet" disabled={busy} onClick={() => void load()}>{t("trace.open_large")}</button>
    {error && <Alert>{error}</Alert>}
    {result && <>
      <p role="status">{t(`logs.${result.state}`)}{result.diagnostic && <> · {result.diagnostic}</>}</p>
      {result.content != null && <><button type="button" className="button-quiet" onClick={() => setResult(undefined)}>{t("common.close")}</button>
        <pre className="trace-json" tabIndex={0}>{result.content}</pre></>}
    </>}
  </div>;
}

export function TraceDetails({ item, knowledgeProject }: { item: TraceItem; knowledgeProject?: string }) {
  const { t } = useI18n();
  const step = item.step, record = item.record, permission = item.permission;
  return <>
    <h3>{traceTitle(item, t)}</h3>
    {!step && <p className="hint">{tracePosition(item, t)} · {t(item.anchorSeq === undefined ? "trace.unpositioned_hint" : "trace.correlation_hint")}</p>}
    {step && <>
      <p>{t("trace.presence")} <Source source="measured" /></p>
      <p className="hint">{t("trace.timing")}</p>
      <dl className="fields map-fields"><div><dt>{t("trace.sequence")}</dt><dd>{step.seq}</dd></div>
        {STEP_FIELDS.map(field => <div key={field}><dt>{t(`trace.field.${field}` as Parameters<typeof t>[0])}</dt><dd>
          {step[field] == null ? <NotObserved /> : <code className="map-json">{JSON.stringify(step[field])}</code>}</dd></div>)}</dl>
      {typeof step.parent_seq === "number" && <p className="hint">{t("trace.parent", { seq: step.parent_seq })}</p>}
      <h4>{t("trace.sources")}</h4>
      {!step.source_records.length && <NotObserved reason="no_source_record" />}
      {step.source_records.map(ref => <section className="trace-source" key={`${ref.run_id}:${ref.attempt_id}:${ref.sequence}`}>
        <p><code>{ref.run_id} / {ref.attempt_id} / {ref.sequence}</code> · {t("trace.source_record", { record: ref.record ?? "?" })}</p>
        <p>{t(ref.availability === "available" ? "trace.available" : "trace.retained")} <Source source={ref.availability_source} /></p>
        <OriginalRead path={sourcePath(ref.event)} source={ref} label={t("trace.open_event")} />
        {ref.oversize && <>
          {ref.availability === "unavailable_after_retention" && <p role="note" className="state state-attention">{t("trace.retained")}</p>}
          {ref.log && <><pre className="trace-json">{JSON.stringify(ref.log, null, 2)}</pre>
            <OriginalRead path={sourcePath(ref.log)} label={t("trace.open_log")} />
            <LogOriginalRead source={ref} /></>}
        </>}
      </section>)}
    </>}
    {record && <>
      <p><Source source={record.source} /> · {when(record.recorded_at)}</p>
      <dl className="fields map-fields">{["event_id", "sequence", "operation_id", "thread_id", "parent_event_id", "causation_id", "truncated", "redactions"].map(field => <div key={field}>
        <dt>{t(`trace.field.${field}` as Parameters<typeof t>[0])}</dt><dd><code>{String(record[field as keyof typeof record] ?? t("map.not_observed"))}</code></dd></div>)}</dl>
      <pre className="trace-json">{JSON.stringify(record.fields, null, 2)}</pre>
      <p className="hint">{t("trace.receipt_hint")}</p>
      {knowledgeProject && record.thread_id && <OriginalRead path={`/knowledge/projects/${encodeURIComponent(knowledgeProject)}/traces/${encodeURIComponent(record.thread_id)}/events?after=${record.sequence - 1}&limit=1`} label={t("trace.open_record")} />}
      {record.artifacts.map(artifact => <div key={artifact.sha256}><p><code>{artifact.sha256}</code> · {artifact.size} B · {artifact.media}</p>
        {artifact.path ? <OriginalRead path={artifact.path.replace(/^\/api\/managed/, "")} label={t("trace.open_artifact")} /> : <NotObserved />}</div>)}
    </>}
    {permission && <>
      <MapStatusBadge status={permission.status} />
      <dl className="fields map-fields">
        <div><dt>{t("trace.field.identity")}</dt><dd><code>{permission.id}</code> · <code>{permission.source}</code></dd></div>
        <div><dt>{t("trace.response")}</dt><dd>{permission.response ? t(`trace.response.${permission.response}`) : <NotObserved />}</dd></div>
        <div><dt>{t("trace.authority")}</dt><dd>{permission.authority ? t(`trace.authority.${permission.authority}`) : <NotObserved />}</dd></div>
        <div><dt>{t("map.field.started")}</dt><dd>{when(permission.created_at)}</dd></div>
        <div><dt>{t("trace.expires")}</dt><dd>{when(permission.expires_at)}</dd></div>
      </dl><p className="hint">{t("trace.authority_hint")}</p>
      <OriginalRead path={`/inbox/${encodeURIComponent(permission.inbox_item_id)}`} label={t("trace.open_record")} />
    </>}
  </>;
}
