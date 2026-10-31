import { useState } from "react";
import { useI18n } from "../Language";
import type { S } from "../managed-api";
import { Link, navigate } from "../navigation";
import { Empty, Loading, PageHeader, Pagination, Stale, usePoll } from "../ui";
import { RunEvidence } from "./RunEvidence";
import { Attempts } from "./AttemptMetrics";
import { useArchive } from "../ServiceMode";

export function ArchiveNotice() {
  const { t } = useI18n();
  return <p role="status" className="state state-attention">{t("archive.notice")}</p>;
}

export function ArchiveHome() {
  const { t } = useI18n();
  const [id, setId] = useState("");
  return <>
    <Link to={{ name: "knowledge" }}>{t("knowledge.title")}</Link>
    <PageHeader title={t("archive.title")}><p>{t("archive.lede")}</p></PageHeader>
    <form className="panel" onSubmit={event => { event.preventDefault(); if (id.trim()) navigate({ name: "run-short", run: id.trim() }); }}>
      <label>{t("archive.run_id")}<input value={id} required onChange={event => setId(event.target.value)} /></label>
      <p className="hint">{t("archive.id_hint")}</p>
      <button type="submit" disabled={!id.trim()}>{t("archive.open")}</button>
    </form>
  </>;
}

export function ArchiveBlocked() {
  const { t } = useI18n();
  return <><PageHeader title={t("archive.title")} /><Empty title={t("archive.blocked")}>
    <p><Link to={{ name: "home" }}>{t("archive.back")}</Link></p>
  </Empty></>;
}

/** Every request is a bounded read by run id. Historical ACTIVE/QUEUED never starts polling. */
export function ArchiveRun({ run: id }: { run: string }) {
  const { t } = useI18n();
  const archive = useArchive();
  const [refresh, setRefresh] = useState(0);
  const [jobOffset, setJobOffset] = useState(0);
  const [offset, setOffset] = useState(0);
  const [cycleOffset, setCycleOffset] = useState(0);
  const [cursors, setCursors] = useState([0]);
  const [eventPage, setEventPage] = useState(0);
  const after = cursors[eventPage];
  const path = `/runs/${encodeURIComponent(id)}`;
  const read = usePoll<S["ManagedRunRead"]>(path, 0, refresh);
  const found = read.data !== undefined && !read.missing;
  const jobs = usePoll<S["Page_ManagedJobRead_"]>(found ? `${path}/jobs?offset=${jobOffset}` : null, 0, refresh);
  const attempts = usePoll<S["Page_ManagedAttemptRead_"]>(found ? `${path}/attempts?offset=${offset}` : null, 0, refresh);
  const cycles = usePoll<S["Page_CycleRead_"]>(found ? `${path}/cycles?offset=${cycleOffset}` : null, 0, refresh);
  const events = usePoll<S["ManagedEventsRead"]>(found ? `${path}/events?after=${after}&limit=50` : null, 0, refresh);
  if (read.missing) return <Empty title={t("run.missing")}><Link to={{ name: archive ? "home" : "configuration" }}>{t(archive ? "archive.back" : "configuration.title")}</Link></Empty>;
  if (!read.data) return read.error ? <p role="alert" className="state state-error">{read.error}</p> : <Loading>{t("run.loading")}</Loading>;
  const errors = [read.error, jobs.error, attempts.error, cycles.error, events.error].filter(Boolean).join(" · ");
  return <>
    <button type="button" className="button-quiet" onClick={() => setRefresh(n => n + 1)}>{t("archive.reload")}</button>
    <Stale error={errors || undefined} />
    {(jobs.loading || attempts.loading || cycles.loading || events.loading) && <Loading />}
    <RunEvidence run={read.data} jobs={jobs.data} attempts={attempts.data} cycles={cycles.data} events={events.data?.items}
      jobOffset={jobOffset} offset={offset} cycleOffset={cycleOffset} setJobOffset={setJobOffset} setOffset={setOffset} setCycleOffset={setCycleOffset} />
    <Pagination offset={eventPage} next={events.data?.has_more ? eventPage + 1 : null} onChange={page => {
      if (page > eventPage && events.data) setCursors(previous => [...previous.slice(0, page), events.data!.cursor]);
      setEventPage(page);
    }} size={1} label={t("run.events")} />
    <Attempts key={id} scope={{ run: id }} refresh={refresh} title={t("stats.metrics")} interval={0} />
  </>;
}
