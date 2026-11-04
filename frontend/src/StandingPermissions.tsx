import { useEffect, useState } from 'react';
import { useI18n } from './Language';
import { confirmOnce, managed } from './managed-api';
import type { S } from './managed-api';
import { useWorkspace } from './workspace';
import { message } from './ui';

type Item = { id: string; kind: string; active: boolean; effective: boolean | null; payload: Record<string, unknown> };
export function StandingPermissions() {
  return <StandingPermissionPanel {...useWorkspace()} />;
}

type PanelProps = {
  project: string; refresh: number; busy: boolean;
  operate: (effect: () => Promise<unknown>) => Promise<void>;
  focused?: S['InboxStandingPermissionRead'] & { requestId: string };
};

export function StandingPermissionPanel({ project, refresh, operate, busy, focused }: PanelProps) {
  const { t } = useI18n();
  const [ledger, setLedger] = useState<S['StandingPermissionsRead']>();
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<S['StandingPermissionPreviewRead']>();
  const [confirmed, setConfirmed] = useState(false);
  const [durationKind, setDurationKind] = useState('');
  const [seconds, setSeconds] = useState(3600);
  const [error, setError] = useState('');
  const base = `/projects/${encodeURIComponent(project)}/permissions`;
  const requestId = focused?.requestId;
  const data = focused ? { revision: focused.revision, items: [{ id: focused.requestId, kind: 'request',
    active: true, effective: null, payload: { duration: focused.duration, targets: focused.targets } }] } : ledger;
  useEffect(() => {
    setPreview(undefined); setConfirmed(false);
    if (requestId) return;
    let active = true;
    managed<S['StandingPermissionsRead']>(base).then(value => {
      if (active) { setLedger(value); setError(''); }
    }).catch(() => { if (active) setLedger(undefined); });
    return () => { active = false; };
  }, [base, refresh, requestId, focused?.revision]);
  if (!data) return null;
  const items = data.items as Item[];
  async function prepare(item: Item, action: S['StandingPermissionPreviewCreate']['action']) {
    setConfirmed(false); setError('');
    const response = action === 'revoke' ? { record_id: item.id, reason } : {
      request_id: item.id, reason, duration: action === 'grant' ? {kind: durationKind, seconds: durationKind === 'time_limited' ? seconds : null} : item.payload.duration,
    };
    try {
      setPreview(await managed<S['StandingPermissionPreviewRead']>(`${base}/preview`, {
        action, response, expected_revision: data!.revision,
      }));
    } catch (e) { setError(message(e)); }
  }
  function apply() {
    if (!preview || !confirmed || preview.revision !== data?.revision) return;
    const saved = preview;
    void operate(async () => {
      await confirmOnce(`${base}/responses`, {
        action: saved.action, response: saved.response, expected_revision: saved.revision,
        preview_sha256: saved.preview_sha256, confirmed: true,
      } satisfies S['StandingPermissionResponseCreate']);
      setPreview(undefined); setConfirmed(false);
    });
  }
  return <details className="panel" open={requestId ? true : undefined}><summary>{t('standing.title')}</summary>
    <p>{t('standing.hint')}</p>
    <label>{t('permissions.reason')}<input value={reason} onChange={e => {
      setReason(e.target.value); setPreview(undefined); setConfirmed(false);
    }} maxLength={2000} /></label>
    <label>{t('permissions.scope')}<select value={durationKind} onChange={e => {setDurationKind(e.target.value); setPreview(undefined); setConfirmed(false);}}>
      <option value="">{t('standing.choose_duration')}</option>
      <option value="operation">{t('standing.operation')}</option>
      <option value="time_limited">{t('standing.temporary')}</option>
      <option value="permanent">{t('standing.permanent')}</option>
    </select></label>
    {durationKind === 'time_limited' && <label>{t('permissions.ttl')}<input type="number" min={1} value={seconds} onChange={e => {setSeconds(Number(e.target.value));setPreview(undefined);setConfirmed(false);}} /></label>}
    {error && <p role="alert">{error}</p>}
    {items.filter(i => requestId ? i.kind === 'request' && i.id === requestId : ['request', 'grant', 'deny', 'escalate', 'authorization'].includes(i.kind)).map(item => {
      const answered = items.some(i => ['grant', 'deny'].includes(i.kind) && i.payload.request_id === item.id);
      const duration = item.payload.duration as { kind?: string } | undefined;
      return <div className="entry" key={item.id}>
        <p><strong>{t(`standing.kind.${item.kind}` as 'standing.kind.request')}</strong> · {t(item.active ? 'standing.active' : 'standing.inactive')}</p>
        {item.kind === 'grant' && item.active && item.effective === false && <p>{t('standing.restricted')}</p>}
        {item.kind === 'grant' && item.effective === null && <p>{t('standing.unknown')}</p>}
        <p>{String(item.payload.grantee ?? '')} · {String(item.payload.purpose ?? '')}</p>
        <p>{t('standing.origin')}: {String(item.payload.origin ?? '')} · {t('standing.parent')}: {String(item.payload.parent ?? '—')}</p>
        <p>{duration?.kind === 'permanent' ? t('standing.permanent') : String(item.payload.expires_at ?? duration?.kind ?? '')}</p>
        <pre>{focused ? focused.targets.join('\n') : JSON.stringify(item.payload.targets, null, 2)}</pre>
        {item.kind === 'request' && !answered && item.active && <>
          <button disabled={busy || !reason.trim() || !durationKind} onClick={() => void prepare(item, 'grant')}>{t('permissions.grant')}</button>
          <button disabled={busy || !reason.trim()} onClick={() => void prepare(item, 'deny')}>{t('permissions.deny')}</button>
          {!requestId && <button disabled={busy || !reason.trim()} onClick={() => void prepare(item, 'escalate')}>{t('standing.escalate')}</button>}
        </>}
        {['grant', 'authorization'].includes(item.kind) && item.active && <button disabled={busy || !reason.trim()} onClick={() => void prepare(item, 'revoke')}>{t('standing.revoke')}</button>}
      </div>;
    })}
    {preview && <div className="decision">
      <p>{t('standing.preview')}</p><pre>{JSON.stringify(preview.response, null, 2)}</pre>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t('standing.confirm')}</label>
      <button disabled={busy || !confirmed || preview.revision !== data.revision} onClick={apply}>{t('standing.apply')}</button>
    </div>}
  </details>;
}
