import { useEffect, useState } from 'react';
import { useI18n } from './Language';
import { confirmOnce, managed } from './managed-api';
import type { S } from './managed-api';
import { useWorkspace } from './workspace';
import { Loading, message, Stale, usePoll } from './ui';

// Accepted G11 defaults only
// prefill the inputs on request; the owner still confirms every bound in the preview hash.
const BOUNDS = ['task_attempts', 'judge_reconsiderations', 'replacement_plans', 'remediation_per_cause', 'no_progress'] as const;
type Bound = typeof BOUNDS[number];
const DELEGATION: S['AutonomousDelegation'] = {
  duties: [], duration_ceiling: { kind: 'operation' },
  tiers: { active: ['files.write.task_contract'], delegable: ['files.write.task_contract'],
           owner_only: ['secrets', 'global_configuration', 'outside_root_writes', 'destructive_git', 'push', 'publication', 'deployment'] },
};

export function AutonomousRun({ runId }: { runId?: string } = {}) {
  const { t } = useI18n();
  const { project, refresh, operate, busy } = useWorkspace();
  const [bounds, setBounds] = useState<Partial<Record<Bound, number>>>({});
  const [caps, setCaps] = useState<S['AutonomousCaps']>({});
  const [writerStopped, setWriterStopped] = useState(false);
  const [report, setReport] = useState<S['AutonomousReadinessRead']>();
  const [preview, setPreview] = useState<S['AutonomousPreviewRead']>();
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [gapAnswers, setGapAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const base = `/projects/${encodeURIComponent(project)}/autonomous`;
  const status = usePoll<S['AutonomousRunRead']>(runId ? `${base}/runs/${encodeURIComponent(runId)}` : base, 3000, refresh);
  const run = status.data;
  const revising = run?.status === 'LIMIT_REACHED';
  useEffect(() => {
    if (revising) {
      setBounds({ ...(run.authorization.bounds as S['AutonomousBounds']) });
      setCaps({ ...(run.authorization.caps as S['AutonomousCaps']) });
    }
  }, [revising, run?.authorization.id]);
  useEffect(() => { setPreview(undefined); setConfirmed(false); setWriterStopped(false); }, [run?.version]);
  const complete = BOUNDS.every(name => Number.isInteger(bounds[name]) && (bounds[name] ?? 0) >= 1);
  const request = (): S['AutonomousRequest'] => ({ bounds: complete ? bounds as S['AutonomousBounds'] : null,
    caps: revising ? caps : {}, delegation: revising ? run.authorization.delegation as S['AutonomousDelegation'] : DELEGATION });
  const runPath = run ? `${base}/runs/${encodeURIComponent(run.id)}` : undefined;
  const disabled = busy || (!!status.error && !status.missing);
  function invalidatePreview() { setPreview(undefined); setConfirmed(false); }

  async function check() {
    setError(''); setPreview(undefined); setConfirmed(false);
    try { setReport(await managed<S['AutonomousReadinessRead']>(`${base}/readiness`, request())); }
    catch (e) { setError(message(e)); }
  }
  async function prepare() {
    setError(''); setConfirmed(false);
    try {
      const path = revising ? `${runPath}/revision-preview` : `${base}/preview`;
      const body = revising ? { request: request(), expected_version: run.version } satisfies S['AutonomousRevisionPreviewCreate'] : request();
      setPreview(await managed<S['AutonomousPreviewRead']>(path, body));
    }
    catch (e) { setError(message(e)); }
  }
  function start() {
    if (!preview || !confirmed || (revising && preview.run_version !== run.version)) return;
    const saved = preview;
    void operate(async () => {
      try {
        await confirmOnce(revising ? `${runPath}/revise` : `${base}/confirm`,
          { request: request(), preview_sha256: saved.preview_sha256, reason, confirmed: true,
            acknowledgement_version: (saved.acknowledgement.version as string | null) ?? null } satisfies S['AutonomousConfirmCreate']);
        setPreview(undefined); setConfirmed(false);
      } catch (e) { setError(message(e)); }
    });
  }
  function answerGap(gap: string) {
    void operate(async () => {
      try {
        await managed(`${base}/gaps/answer`, { gap_sha256: gap, text: gapAnswers[gap] ?? '' } satisfies S['AutonomousGapAnswerCreate'],
          crypto.randomUUID());
        await check();
      } catch (e) { setError(message(e)); }
    });
  }
  function control(action: 'pause' | 'resume' | 'revoke' | 'recover') {
    if (!run || (action === 'recover' && !writerStopped)) return;
    const body = action === 'resume' ? { expected_version: run.version }
      : action === 'recover' ? { expected_version: run.version, reason, writer_stopped: true } : { expected_version: run.version, reason };
    void operate(async () => {
      try { await managed(`${runPath}/${action}`, body); } catch (e) { setError(message(e)); }
    });
  }
  function answer(question: S['AutonomousQuestionRead']) {
    if (!run) return;
    void operate(async () => {
      try {
        await confirmOnce(`${runPath}/questions/${encodeURIComponent(question.id)}/answer`,
          { expected_version: question.version, text: answers[question.id] ?? '' } satisfies S['AutonomousAnswerCreate']);
      } catch (e) { setError(message(e)); }
    });
  }
  if (!run && !status.missing) return runId ? status.error ? <Stale error={status.error} /> : <Loading /> : null;
  if (runId && status.missing) return <p role="status">{t('inbox.unavailable')}</p>;
  const active = run && !['COMPLETED', 'REVOKED'].includes(run.status);
  const acknowledgement = preview?.acknowledgement.text as Record<string, string> | null | undefined;
  return <details className="panel" open={runId ? true : undefined}><summary>{t('autonomy.title')}</summary>
    <p>{t('autonomy.hint')}</p>
    <Stale error={run ? status.error : undefined} />
    {error && <p role="alert">{error}</p>}
    <label>{t('autonomy.reason')}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
    {run && <div className="entry">
      <p><strong>{t('autonomy.status')}</strong>: {run.status}{run.reason ? ` · ${run.reason}` : ''}</p>
      <p>{t('autonomy.authorization')}: {String(run.authorization.number)} · {String(run.authorization.origin)}</p>
      <pre>{JSON.stringify(run.consumption, null, 2)}</pre>
      {run.questions.filter(q => q.status === 'OPEN').map(q => <div className="entry" key={q.id}>
        <p>{t('autonomy.question')}: {q.kind}</p>
        <pre>{JSON.stringify(q.subject, null, 2)}</pre>
        <label>{t('autonomy.answer')}<input value={answers[q.id] ?? ''} maxLength={8000}
          onChange={e => setAnswers({ ...answers, [q.id]: e.target.value })} /></label>
        <button disabled={disabled || !(answers[q.id] ?? '').trim()} onClick={() => answer(q)}>{t('autonomy.send_answer')}</button>
      </div>)}
      {active && <>
        {run.status === 'RUNNING' && <button disabled={disabled || !reason.trim()} onClick={() => control('pause')}>{t('autonomy.pause')}</button>}
        {['WAITING_FOR_OWNER', 'PAUSED', 'FAILED'].includes(run.status) && <button disabled={disabled || run.questions.some(q => q.status === 'OPEN')} onClick={() => control('resume')}>{t('autonomy.resume')}</button>}
        {run.status === 'RECOVERY_REQUIRED' && <>
          <label className="check"><input type="checkbox" checked={writerStopped} onChange={e => setWriterStopped(e.target.checked)} />{t('autonomy.writer_stopped')}</label>
          <button disabled={disabled || !writerStopped || !reason.trim()} onClick={() => control('recover')}>{t('autonomy.recover')}</button>
        </>}
        <button disabled={disabled || !reason.trim()} onClick={() => control('revoke')}>{t('autonomy.revoke')}</button>
      </>}
    </div>}
    {((!active && !runId) || revising) && <div className="entry">
      {BOUNDS.map(name => <label key={name}>{t(`autonomy.bound.${name}` as 'autonomy.bound.task_attempts')}
        <input type="number" min={1} max={1000} value={bounds[name] ?? ''} onChange={e => {
          setBounds({ ...bounds, [name]: e.target.value === '' ? undefined : Number(e.target.value) });
          setReport(undefined); setPreview(undefined); setConfirmed(false);
        }} /></label>)}
      {revising ? <>
        {(['invocations', 'observed_tokens'] as const).map(cap => (run.authorization.caps as S['AutonomousCaps'])[cap] != null && <label key={cap}>{t(`autonomy.cap.${cap}`)}
          <input type="number" min={1} value={caps[cap] ?? ''} onChange={e => {
            setCaps({ ...caps, [cap]: e.target.value === '' ? null : Number(e.target.value) }); invalidatePreview();
          }} /></label>)}
        {run.authorization.caps && (run.authorization.caps as S['AutonomousCaps']).deadline && <label>{t('autonomy.cap.deadline')}
          <input value={caps.deadline ?? ''} placeholder="YYYY-MM-DDTHH:MM:SSZ" onChange={e => {
            setCaps({ ...caps, deadline: e.target.value || null }); invalidatePreview();
          }} /></label>}
        {caps.valuation && <label>{t('autonomy.cap.valuation', { basis: caps.valuation.basis })}
          <input value={caps.valuation.amount} onChange={e => {
            setCaps({ ...caps, valuation: { basis: caps.valuation!.basis, amount: e.target.value } }); invalidatePreview();
          }} /></label>}
        <button disabled={disabled || !complete} onClick={() => void prepare()}>{t('autonomy.preview_revision')}</button>
      </> : <button disabled={disabled} onClick={() => void check()}>{t('autonomy.check')}</button>}
      {report && <>
        <p><strong>{t('autonomy.verdict')}</strong>: {report.verdict}</p>
        {(report.pending_gates ?? []).length > 0 && <p>{t('autonomy.gates_pending')}: {(report.pending_gates ?? []).join(', ')}</p>}
        <ul>{report.checks.map(c => <li key={c.check}>{c.passed ? '✓' : '✗'} {c.check}</li>)}</ul>
        {report.default_bounds && !complete && <button disabled={disabled} onClick={() => {
          setBounds({ ...report.default_bounds } as Partial<Record<Bound, number>>); setReport(undefined);
        }}>{t('autonomy.use_defaults')}</button>}
        {report.gaps.map(gap => <div className="entry" key={String(gap.gap_sha256)}>
          <p><strong>{String(gap.classification)}</strong>: {String(gap.statement)}</p>
          {gap.classification === 'owner_answer_required' && (report.owner_answer_required ?? []).includes(String(gap.gap_sha256)) && <>
            <label>{t('autonomy.answer')}<input value={gapAnswers[String(gap.gap_sha256)] ?? ''} maxLength={8000}
              onChange={e => setGapAnswers({ ...gapAnswers, [String(gap.gap_sha256)]: e.target.value })} /></label>
            <button disabled={disabled || !(gapAnswers[String(gap.gap_sha256)] ?? '').trim()}
              onClick={() => answerGap(String(gap.gap_sha256))}>{t('autonomy.send_answer')}</button>
          </>}
        </div>)}
        <button disabled={disabled || report.verdict !== 'READY'} onClick={() => void prepare()}>{t('autonomy.preview')}</button>
      </>}
      {preview && <>
        <p className="mono">{preview.preview_sha256}</p>
        <p>{t('autonomy.verdict')} <strong>{String(preview.readiness.verdict)}</strong></p>
        {preview.blocking.length > 0 && <ul>{preview.blocking.map(reason => <li key={reason}>{reason}</li>)}</ul>}
        <p>{t('autonomy.scope')}: {(preview.scope.phases as string[]).join(', ')}</p>
        {acknowledgement ? <blockquote>{acknowledgement[document.documentElement.lang] ?? acknowledgement.en}</blockquote>
          : <p>{t('autonomy.acknowledgement_pending')}</p>}
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> {t('autonomy.confirm')}</label>
        <button disabled={disabled || !confirmed || !reason.trim() || !acknowledgement || preview.readiness.verdict !== 'READY'
          || (revising && preview.run_version !== run.version)} onClick={start}>{t(revising ? 'autonomy.apply_revision' : 'autonomy.start')}</button>
      </>}
    </div>}
  </details>;
}
