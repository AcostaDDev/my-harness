import { useEffect, useState } from 'react';
import { useI18n } from './Language';
import type { MessageKey } from './i18n.ts';
import { managed } from './managed-api';
import type { S } from './managed-api';
import { message } from './ui';

const labels: Record<S['ManagedLogRead']['state'], MessageKey> = { retained: 'logs.retained', purged: 'logs.purged',
  pending: 'logs.pending', missing: 'logs.missing', unverified: 'logs.unverified' };

export function Logs({ runId, attemptId }: { runId: string; attemptId: string }) {
  const { t, n } = useI18n();
  const [logs, setLogs] = useState<S['ManagedLogRead'][]>();
  const [error, setError] = useState('');
  const [request, setRequest] = useState(0);
  useEffect(() => {
    if (!request) return;
    let active = true;
    managed<S['ManagedLogRead'][]>(`/runs/${runId}/attempts/${attemptId}/logs`).then(
      data => { if (active) { setLogs(data); setError(''); } },
      e => { if (active) { setLogs(undefined); setError(message(e)); } });
    return () => { active = false; };
  }, [runId, attemptId, request]);
  return <div className="logs">
    <button className="button-quiet" onClick={() => { setLogs(undefined); setRequest(n => n + 1); }}>{t('logs.check')}</button>
    {error && <p role="alert" className="state state-error">{error}</p>}
    {logs?.length === 0 && <p>{t('logs.none')}</p>}
    {logs?.map(log => <div key={log.stream}>
      <p>{log.stream}: {t(labels[log.state])} · {n('logs.bytes', log.size_bytes)}</p>
      {log.diagnostic && <p>{log.diagnostic}</p>}
      <details className="evidence"><summary>{t('logs.provenance')}</summary><pre>{JSON.stringify(log, null, 2)}</pre></details>
    </div>)}
  </div>;
}
