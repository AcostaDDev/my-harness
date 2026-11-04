import { useEffect, useState } from 'react';
import { useI18n } from './Language';
import { managed, ManagedError } from './managed-api';
import type { S } from './managed-api';
import { useWorkspace } from './workspace';
import { message } from './ui';

// P002-T016: minimal visible start/status/question/stop controls before T017's inbox. Accepted G11 defaults only
// prefill the inputs on request; the owner still confirms every bound in the preview hash.
const BOUNDS = ['task_attempts', 'judge_reconsiderations', 'replacement_plans', 'remediation_per_cause', 'no_progress'] as const;
type Bound = typeof BOUNDS[number];
const DELEGATION: S['AutonomousDelegation'] = {
  duties: [], duration_ceiling: { kind: 'operation' },
  tiers: { active: ['files.write.task_contract'], delegable: ['files.write.task_contract'],
           owner_only: ['secrets', 'global_configuration', 'outside_root_writes', 'destructive_git', 'push', 'publication', 'deployment'] },
};

export function AutonomousRun() {
  const { t } = useI18n();
  const { project, refresh, operate, busy } = useWorkspace();
  const [run, setRun] = useState<S['AutonomousRunRead'] | null>();
  const [bounds, setBounds] = useState<Partial<Record<Bound, number>>>({});
  const [report, setReport] = useState<S['AutonomousReadinessRead']>();
  const [preview, setPreview] = useState<S['AutonomousPreviewRead']>();
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [gapAnswers, setGapAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const base = `/projects/${project}/autonomous`;
  useEffect(() => {
    let active = true;
    managed<S['AutonomousRunRead']>(base).then(value => { if (active) setRun(value); })
      .catch(e => { if (active) setRun(e instanceof ManagedError && e.status === 404 ? null : undefined); });
    return () => { active = false; };
  }, [base, refresh]);
  const complete = BOUNDS.every(name => Number.isInteger(bounds[name]) && (bounds[name] ?? 0) >= 1);
  const request = (): S['AutonomousRequest'] => ({ bounds: complete ? bounds as S['AutonomousBounds'] : null, caps: {}, delegation: DELEGATION });
  async function check() {
    setError(''); setPreview(undefined); setConfirmed(false);
    try { setReport(await managed<S['AutonomousReadinessRead']>(`${base}/readiness`, request())); }
    catch (e) { setError(message(e)); }
  }
  async function prepare() {
    setError(''); setConfirmed(false);
    try { setPreview(await managed<S['AutonomousPreviewRead']>(`${base}/preview`, request())); }
    catch (e) { setError(message(e)); }
  }
  function start() {
    if (!preview || !confirmed) return;
    const saved = preview;
    void operate(async () => {
      try {
        await managed(`${base}/confirm`, { request: request(), preview_sha256: saved.preview_sha256, reason, confirmed: true,
          acknowledgement_version: (saved.acknowledgement.version as string | null) ?? null } satisfies S['AutonomousConfirmCreate'],
          crypto.randomUUID());
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
    if (!run) return;
    const body = action === 'resume' ? { expected_version: run.version }
      : action === 'recover' ? { expected_version: run.version, reason, writer_stopped: true } : { expected_version: run.version, reason };
    void operate(async () => {
      try { await managed(`${base}/runs/${run.id}/${action}`, body); } catch (e) { setError(message(e)); }
    });
  }
  function answer(question: S['AutonomousQuestionRead']) {
    if (!run) return;
    void operate(async () => {
      try {
        await managed(`${base}/runs/${run.id}/questions/${question.id}/answer`,
          { expected_version: question.version, text: answers[question.id] ?? '' } satisfies S['AutonomousAnswerCreate'], crypto.randomUUID());
      } catch (e) { setError(message(e)); }
    });
  }
  if (run === undefined) return null;
  const active = run && !['COMPLETED', 'REVOKED'].includes(run.status);
  const acknowledgement = preview?.acknowledgement.text as Record<string, string> | null | undefined;
  return <details className="panel"><summary>{t('autonomy.title')}</summary>
    <p>{t('autonomy.hint')}</p>
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
        <button disabled={busy || !(answers[q.id] ?? '').trim()} onClick={() => answer(q)}>{t('autonomy.send_answer')}</button>
      </div>)}
      {active && <>
        {run.status === 'RUNNING' && <button disabled={busy || !reason.trim()} onClick={() => control('pause')}>{t('autonomy.pause')}</button>}
        {['WAITING_FOR_OWNER', 'PAUSED', 'FAILED'].includes(run.status) && <button disabled={busy} onClick={() => control('resume')}>{t('autonomy.resume')}</button>}
        {run.status === 'RECOVERY_REQUIRED' && <button disabled={busy || !reason.trim()} onClick={() => control('recover')}>{t('autonomy.recover')}</button>}
        <button disabled={busy || !reason.trim()} onClick={() => control('revoke')}>{t('autonomy.revoke')}</button>
      </>}
    </div>}
    {!active && <div className="entry">
      {BOUNDS.map(name => <label key={name}>{t(`autonomy.bound.${name}` as 'autonomy.bound.task_attempts')}
        <input type="number" min={1} max={1000} value={bounds[name] ?? ''} onChange={e => {
          setBounds({ ...bounds, [name]: e.target.value === '' ? undefined : Number(e.target.value) });
          setReport(undefined); setPreview(undefined); setConfirmed(false);
        }} /></label>)}
      <button disabled={busy} onClick={() => void check()}>{t('autonomy.check')}</button>
      {report && <>
        <p><strong>{t('autonomy.verdict')}</strong>: {report.verdict}</p>
        {(report.pending_gates ?? []).length > 0 && <p>{t('autonomy.gates_pending')}: {(report.pending_gates ?? []).join(', ')}</p>}
        <ul>{report.checks.map(c => <li key={c.check}>{c.passed ? '✓' : '✗'} {c.check}</li>)}</ul>
        {report.default_bounds && !complete && <button disabled={busy} onClick={() => {
          setBounds({ ...report.default_bounds } as Partial<Record<Bound, number>>); setReport(undefined);
        }}>{t('autonomy.use_defaults')}</button>}
        {report.gaps.map(gap => <div className="entry" key={String(gap.gap_sha256)}>
          <p><strong>{String(gap.classification)}</strong>: {String(gap.statement)}</p>
          {gap.classification === 'owner_answer_required' && (report.owner_answer_required ?? []).includes(String(gap.gap_sha256)) && <>
            <label>{t('autonomy.answer')}<input value={gapAnswers[String(gap.gap_sha256)] ?? ''} maxLength={8000}
              onChange={e => setGapAnswers({ ...gapAnswers, [String(gap.gap_sha256)]: e.target.value })} /></label>
            <button disabled={busy || !(gapAnswers[String(gap.gap_sha256)] ?? '').trim()}
              onClick={() => answerGap(String(gap.gap_sha256))}>{t('autonomy.send_answer')}</button>
          </>}
        </div>)}
        <button disabled={busy || report.verdict !== 'READY'} onClick={() => void prepare()}>{t('autonomy.preview')}</button>
      </>}
      {preview && <>
        <p className="mono">{preview.preview_sha256}</p>
        <p>{t('autonomy.scope')}: {(preview.scope.phases as string[]).join(', ')}</p>
        {acknowledgement ? <blockquote>{acknowledgement[document.documentElement.lang] ?? acknowledgement.en}</blockquote>
          : <p>{t('autonomy.acknowledgement_pending')}</p>}
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> {t('autonomy.confirm')}</label>
        <button disabled={busy || !confirmed || !reason.trim() || !acknowledgement} onClick={start}>{t('autonomy.start')}</button>
      </>}
    </div>}
  </details>;
}
