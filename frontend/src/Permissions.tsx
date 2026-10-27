import { useEffect, useState } from 'react';
import { useI18n } from './Language';
import type { MessageKey } from './i18n.ts';
import { managed } from './managed-api';
import type { S } from './managed-api';
import { message } from './ui';

type Props = { run: S['ManagedRunRead']; busy: boolean; refresh: number; operate: (f: () => Promise<unknown>) => Promise<void> };
const operations = { files: 'write', tools: 'use', network: 'connect', product: 'decide', acceptance: 'accept' };
const names: Record<keyof typeof operations, MessageKey> = { files: 'permissions.kind.files', tools: 'permissions.kind.tools',
  network: 'permissions.kind.network', product: 'permissions.kind.product', acceptance: 'permissions.kind.acceptance' };

export function Permissions({ run, busy, refresh, operate }: Props) {
  const { t, rich } = useI18n();
  const [requests, setRequests] = useState<S['PermissionRequestRead'][]>([]);
  const [error, setError] = useState('');
  const [kind, setKind] = useState<S['PermissionCreate']['kind']>('tools');
  const [target, setTarget] = useState('');
  const [source, setSource] = useState('');
  const [requester, setRequester] = useState('');
  const [reason, setReason] = useState('');
  const [ttl, setTtl] = useState(3600);
  const [supersedes, setSupersedes] = useState('');
  const [scope, setScope] = useState<S['PermissionDecisionCreate']['scope']>('once');
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    let active = true;
    managed<S['PermissionRequestRead'][]>(`/runs/${run.id}/permissions`).then(r => { if (active) { setRequests(r); setError(''); } })
      .catch(e => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [run.id, run.version, refresh]);
  useEffect(() => { setConfirmed(false); }, [run.version, kind, target, source, supersedes, ttl, scope, reason]);
  const editable = !busy && !error && run.actions.includes('permissions');
  function decide(r: S['PermissionRequestRead'], decision: 'grant' | 'deny') {
    void operate(async () => {
      await managed(`/runs/${run.id}/permissions/${r.id}/decision`, {
        expected_version: run.version, expected_request_version: r.version, fingerprint: r.fingerprint,
        decision, scope, reason, confirmed: true,
      } satisfies S['PermissionDecisionCreate']);
      setConfirmed(false);
    });
  }
  return <details className="panel panel-collapsible"><summary><h2>{t('permissions.title')}</h2></summary>
    <p>{t('permissions.hint.grant')}</p>
    <p>{t('permissions.hint.audit')}</p>
    <p>{t('permissions.hint.user')}</p>
    {error && <p role="alert" className="state state-error">{error}</p>}
    <label>{t('permissions.reason')}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
    <form onSubmit={e => { e.preventDefault(); void operate(async () => {
      await managed(`/runs/${run.id}/permissions`, { expected_version: run.version, kind, target,
        operation: operations[kind], arguments: [], requested_by: requester, source_attempt_id: source,
        reason, ttl_seconds: ttl, supersedes: supersedes || null } satisfies S['PermissionCreate']);
      setConfirmed(false); setSupersedes('');
    }); }}>
      <label>{t('permissions.kind')}<select value={kind} onChange={e => setKind(e.target.value as typeof kind)}>{Object.entries(names).map(([k, n]) => <option key={k} value={k}>{t(n)}</option>)}</select></label>
      <label>{t('permissions.target')}<input required value={target} maxLength={2000} onChange={e => setTarget(e.target.value)} /></label>
      <label>{t('permissions.source')}<input required value={source} maxLength={36} onChange={e => setSource(e.target.value)} /></label>
      <label>{t('permissions.requester')}<input required value={requester} maxLength={120} onChange={e => setRequester(e.target.value)} /></label>
      <label>{t('permissions.ttl')}<input type="number" required min={1} max={86400} value={ttl} onChange={e => setTtl(Number(e.target.value))} /></label>
      <label>{t('permissions.supersedes')}<select value={supersedes} onChange={e => setSupersedes(e.target.value)}><option value="">{t('permissions.new_request')}</option>{requests.filter(r => ['PENDING', 'GRANTED', 'DENIED'].includes(r.status)).map(r => <option value={r.id} key={r.id}>{r.id} · {String(r.request.target)}</option>)}</select></label>
      <button className="button-quiet" disabled={!editable || !reason.trim()}>{t('permissions.register')}</button>
    </form>
    <label>{t('permissions.scope')}<select value={scope} onChange={e => setScope(e.target.value as typeof scope)}><option value="once">{t('permissions.scope.once')}</option><option value="task">{t('permissions.scope.task')}</option></select></label>
    <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t('permissions.confirm')}</label>
    {requests.map(r => <div className={r.effective_status === 'PENDING' ? "entry entry-open" : "entry"} key={r.id}><p><strong>{names[r.request.kind as keyof typeof names] ? t(names[r.request.kind as keyof typeof names]) : String(r.request.kind)}</strong> {r.effective_status}</p>
      <p>{rich('permissions.request', { operation: <code>{String(r.request.operation)}</code>, target: <code>{String(r.request.target)}</code>, expires: r.expires_at })}</p>
      <details className="evidence"><summary>{t('permissions.evidence')}</summary><pre>{JSON.stringify(r, null, 2)}</pre></details>
      {r.effective_status === 'PENDING' && <><button disabled={!editable || !confirmed || !reason.trim()} onClick={() => decide(r, 'grant')}>{t('permissions.grant')}</button>
        <button className="button-danger" disabled={!editable || !confirmed || !reason.trim()} onClick={() => decide(r, 'deny')}>{t('permissions.deny')}</button></>}
    </div>)}
  </details>;
}
