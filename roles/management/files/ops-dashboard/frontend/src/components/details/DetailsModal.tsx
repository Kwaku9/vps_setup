import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchDetails } from '../../api/client';
import type { ContainerDetails } from '../../types';
import { Sparkline } from '../charts/Sparkline';
import { useTimeseries } from '../../hooks/useTimeseries';

interface Props {
  name: string | null;
  onClose: () => void;
}

const TABS = ['overview', 'mounts', 'env', 'network', 'charts'] as const;
type Tab = (typeof TABS)[number];

export function DetailsModal({ name, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('overview');
  const [data, setData] = useState<ContainerDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!name) { setData(null); return; }
    setLoading(true); setErr(null); setTab('overview');
    fetchDetails(name)
      .then(setData)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false));
  }, [name]);

  // ESC to close
  useEffect(() => {
    if (!name) return;
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [name, onClose]);

  const cpuTs = useTimeseries(name ?? '', 'cpu', 60, !!name);
  const memTs = useTimeseries(name ?? '', 'mem', 60, !!name);

  return (
    <AnimatePresence>
      {name && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
          />
          <motion.div
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280 }}
            className="fixed inset-x-0 bottom-0 md:inset-0 md:flex md:items-center md:justify-center z-50 safe-bottom"
          >
            <div className="glass rounded-t-2xl md:rounded-2xl w-full md:max-w-2xl md:max-h-[80vh] max-h-[90vh] flex flex-col mx-auto md:mx-4 overflow-hidden">
              {/* Grabber */}
              <div className="md:hidden flex justify-center pt-2 pb-1">
                <div className="w-10 h-1 bg-white/30 rounded-full" />
              </div>

              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
                <div className="min-w-0">
                  <div className="text-base font-semibold truncate">{name}</div>
                  {data && <div className="text-[11px] text-white/40 truncate">{data.image}</div>}
                </div>
                <button
                  onClick={onClose}
                  className="w-10 h-10 rounded-full flex items-center justify-center hover:bg-white/10"
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>

              {/* Tabs */}
              <div className="flex gap-1 px-2 py-2 overflow-x-auto border-b border-white/5">
                {TABS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={`px-3 py-1.5 rounded-full text-[12px] font-semibold capitalize whitespace-nowrap min-h-[36px] ${
                      tab === t ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/5'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-4 text-[13px]">
                {loading && <div className="text-white/50">Loading…</div>}
                {err && <div className="text-rose-300">Error: {err}</div>}
                {data && tab === 'overview' && (
                  <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                    <Field k="Status" v={data.status} />
                    <Field k="Restart Policy" v={`${data.restart_policy} (count ${data.restart_count})`} />
                    <Field k="IP" v={data.ip_address || '—'} />
                    <Field k="Pod" v={data.pod ?? 'standalone'} />
                    <Field k="Started" v={data.started_at} />
                    <Field k="Created" v={data.created} />
                    {data.exit_code !== null && <Field k="Exit Code" v={String(data.exit_code)} />}
                    <Field k="Command" v={(data.command || []).join(' ') || '—'} />
                  </dl>
                )}
                {data && tab === 'mounts' && (
                  data.mounts.length === 0 ? <Empty msg="No mounts." /> : (
                    <ul className="space-y-1 font-mono text-[11px]">
                      {data.mounts.map((m, i) => (
                        <li key={i} className="break-all">
                          <span className="text-white/40">{m.source}</span>
                          <span className="text-white/60"> → </span>
                          <span className="text-cyan-300">{m.destination}</span>
                          <span className="text-white/30"> ({m.mode})</span>
                        </li>
                      ))}
                    </ul>
                  )
                )}
                {data && tab === 'env' && (
                  data.env.length === 0 ? <Empty msg="No env vars." /> : (
                    <ul className="space-y-0.5 font-mono text-[11px]">
                      {data.env.map(([k, v], i) => (
                        <li key={i} className="break-all">
                          <span className="text-cyan-300">{k}</span>
                          <span className="text-white/40">=</span>
                          <span className={v === '***REDACTED***' ? 'text-rose-300' : 'text-white/70'}>{v}</span>
                        </li>
                      ))}
                    </ul>
                  )
                )}
                {data && tab === 'network' && (
                  <dl className="grid grid-cols-1 gap-y-2">
                    <Field k="IP" v={data.ip_address || '—'} />
                    <Field k="Ports (exposed)" v={Object.keys(data.ports).join(', ') || '—'} />
                    <Field k="Bindings" v={JSON.stringify(data.port_bindings) === '{}' ? '—' : JSON.stringify(data.port_bindings, null, 2)} mono />
                  </dl>
                )}
                {tab === 'charts' && (
                  <div className="space-y-4">
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-white/50 mb-1">CPU (60 min)</div>
                      <Sparkline points={cpuTs.points} width={520} height={60} baselineColor="#64d2ff" responsive />
                    </div>
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-white/50 mb-1">Memory (60 min)</div>
                      <Sparkline points={memTs.points} width={520} height={60} baselineColor="#bf5af2" responsive />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function Field({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wider text-white/40">{k}</dt>
      <dd className={`text-white/85 break-all ${mono ? 'font-mono text-[11px]' : ''}`}>{v}</dd>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return <div className="text-white/40 italic">{msg}</div>;
}
