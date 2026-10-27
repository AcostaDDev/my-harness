import { useEffect, useState } from 'react';
import { useI18n } from './Language';
import type { MessageKey, Translate } from './i18n.ts';
import { managed } from './managed-api';
import type { S } from './managed-api';
import { message } from './ui';

const observer = (t: Translate) => (value: unknown) => value === null || value === undefined ? t('tests.not_observed') : String(value);
const results: Record<S['JUnitCaseRead']['result'], MessageKey> = {
  passed: 'tests.result.passed', failed: 'tests.result.failed', error: 'tests.result.error', skipped: 'tests.result.skipped',
  unknown: 'tests.result.unknown',
};
const statuses: Record<S['JUnitReportRead']['status'], MessageKey> = {
  complete: 'tests.report.complete', partial: 'tests.report.partial', invalid: 'tests.report.invalid', missing: 'tests.report.missing',
  unreadable: 'tests.report.unreadable', limit: 'tests.report.limit', stale: 'tests.report.stale',
};
const freshness: Record<S['JUnitReportRead']['freshness'], MessageKey> = {
  created: 'tests.freshness.created', changed: 'tests.freshness.changed', unchanged: 'tests.freshness.unchanged',
  unknown: 'tests.freshness.unknown',
};

export function Tests({ runId, cycle, validation }: { runId: string; cycle: number; validation: S['ValidationRead'] }) {
  const { t } = useI18n();
  const observed = observer(t);
  return <section className="tests"><h4>{t('tests.title')}</h4>
    <p>{t('tests.evidence', { attempt: observed(validation.source_attempt_id), base: observed(validation.evidence.base_revision),
      fingerprint: observed(validation.evidence.fingerprint) })}</p>
    {validation.entries.map((entry, index) => <div className="entry" key={entry.command_id ?? index}>
      <strong><code>{entry.requested}</code></strong>
      <p>{t('tests.command', { exit: observed(entry.result.exit_code), duration: entry.result.duration_seconds == null
        ? t('tests.duration_not_observed') : t('tests.seconds', { seconds: typeof entry.result.duration_seconds === 'number'
          ? entry.result.duration_seconds : String(entry.result.duration_seconds) }) })}</p>
      {entry.result.error != null && <p className="state state-error">{String(entry.result.error)}</p>}
      {entry.result.timed_out === true && <p className="state state-error">{t('tests.timed_out')}</p>}
      {!entry.reports.length && <p>{t('tests.no_report')}</p>}
      {entry.reports.map((report, number) => <Report key={`${report.sha256}:${number}`} report={report}
        path={`/runs/${runId}/cycles/${cycle}/validations/${index}/reports/${number}`} />)}
    </div>)}
  </section>;
}

function Report({ report, path }: { report: S['JUnitReportRead']; path: string }) {
  const { t, n, language } = useI18n();
  const observed = observer(t);
  const seconds = new Intl.NumberFormat(language);
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<S['JUnitCasesRead']>();
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    let active = true;
    setPage(undefined); setError('');
    void managed<S['JUnitCasesRead']>(`${path}?offset=${offset}&limit=50`).then(value => {
      if (active) setPage(value);
    }).catch(e => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [open, offset, path]);
  return <div>
    <p><code>{report.path}</code> · {t(statuses[report.status])} · {n('tests.cases', report.case_count)}</p>
    <p>{t('tests.coverage', { coverage: report.coverage })}</p>
    <p>SHA-256: <code>{observed(report.sha256)}</code> · {t('tests.report_bytes', { bytes: observed(report.size_bytes), freshness: t(freshness[report.freshness]) })}</p>
    {report.diagnostics.map((diagnostic, index) => <p className="state state-error" key={index}>{diagnostic}</p>)}
    {report.original_available && <p><a href={`/api/managed${path}/original`} download="junit.xml">{t('tests.download')}</a></p>}
    <button className="button-quiet" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? t('tests.hide') : t('tests.show')}</button>
    {open && <>
      <p>{t('tests.durations_hint')}</p>
      {error && <p role="alert" className="state state-error">{error}</p>}
      {!page && !error && <p role="status">{t('tests.loading')}</p>}
      {page && <>
        <p>{t('tests.command_id', { command: observed(page.command_id) })}</p>
        <div className="test-table-scroll" role="region" aria-label={t('tests.table')} tabIndex={0}>
        <table className="test-table"><thead><tr><th>{t('tests.column.test')}</th><th>{t('tests.column.result')}</th><th>{t('tests.column.duration')}</th><th>{t('tests.column.error')}</th></tr></thead>
          <tbody>{page.items.map(test => <tr key={test.id}>
            <td>{test.suite.length ? test.suite.map(observed).join(' / ') : t('tests.not_observed')}<br />{observed(test.classname)} · {observed(test.name)}
              <details className="evidence"><summary>{t('tests.identifier')}</summary><p>{t('tests.reported_id', { id: observed(test.reported_id) })}</p><code>{test.id}</code></details></td>
            <td>{t(results[test.result])}</td><td>{test.duration_seconds == null ? t('tests.not_observed') : seconds.format(test.duration_seconds)}</td>
            <td>{test.message != null && <p>{test.message}</p>}{test.error_type != null && <p>{test.error_type}</p>}
              {test.error === null ? t('tests.not_observed') : <pre>{test.error}</pre>}</td>
          </tr>)}</tbody></table></div>
        {!page.items.length && <p>{t('tests.no_cases')}</p>}
        <div className="pagination"><button className="button-quiet" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('common.previous')}</button>
          <button className="button-quiet" disabled={page.next_offset === null} onClick={() => setOffset(page.next_offset!)}>{t('common.next')}</button></div>
      </>}
    </>}
  </div>;
}
