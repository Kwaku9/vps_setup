import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import { groupServices } from '../../lib/stackGroups';
import { GlassPanel } from '../ui/GlassPanel';

const statusConfig: Record<string, { dot: string; label: string; bg: string }> = {
  running: { dot: 'bg-[var(--status-green)]', label: 'Running', bg: 'text-emerald-300 bg-emerald-500/10' },
  stopped: { dot: 'bg-[var(--status-red)]',   label: 'Stopped', bg: 'text-rose-300 bg-rose-500/10' },
  exited:  { dot: 'bg-[var(--status-red)]',   label: 'Exited',  bg: 'text-rose-300 bg-rose-500/10' },
  unknown: { dot: 'bg-white/30',              label: 'Unknown', bg: 'text-white/50 bg-white/5' },
};

const platformBadge: Record<string, { cls: string; label: string }> = {
  vps:   { cls: 'text-[color:var(--vps-cyan)]    bg-cyan-400/10 border border-cyan-400/20',    label: 'VPS' },
  azure: { cls: 'text-[color:var(--azure-blue)]  bg-blue-500/10 border border-blue-500/20',    label: 'AZR' },
  host:  { cls: 'text-[color:var(--host-purple)] bg-purple-500/10 border border-purple-500/20', label: 'HST' },
};

export function StatusView() {
  const { services, metrics } = useDashboard();

  const enriched = useMemo(() => {
    return services.map((svc) => {
      const m = metrics[svc.name];
      return m ? { ...svc, status: m.status, cpu_percent: m.cpu_percent, memory_percent: m.memory_percent } : svc;
    });
  }, [services, metrics]);

  const groups = useMemo(() => groupServices(enriched), [enriched]);

  const totalRunning = enriched.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;
  const totalStopped = enriched.length - totalRunning;

  return (
    <div>
      <div className="flex items-center gap-6 mb-6 text-sm">
        <span><span className="text-green-500 font-bold text-lg">{totalRunning}</span> <span className="text-gray-500">running</span></span>
        <span><span className="text-red-400 font-bold text-lg">{totalStopped}</span> <span className="text-gray-500">stopped</span></span>
        <span><span className="text-gray-300 font-bold text-lg">{enriched.length}</span> <span className="text-gray-500">total services</span></span>
      </div>

      {groups.map((group) => {
        const running = group.services.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;
        return (
          <GlassPanel key={group.key} as="section" className="mb-3 overflow-hidden">
            <div className="flex items-baseline justify-between px-4 pt-3 pb-2">
              <div>
                <div className="text-[13px] font-semibold tracking-wide">{group.title}</div>
                <div className="text-[11px] text-white/50 mt-0.5">{group.subtitle}</div>
              </div>
              <span className="glass rounded-full px-2 py-0.5 text-[11px] text-white/70">{running}/{group.services.length}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-[11px] text-white/40 bg-white/[0.02]">
                    <th className="text-left px-3 py-1.5 w-8"></th>
                    <th className="text-left px-2 py-1.5 w-12">Type</th>
                    <th className="text-left px-2 py-1.5">Service</th>
                    <th className="text-left px-2 py-1.5 hidden md:table-cell">Location</th>
                    <th className="text-left px-2 py-1.5 w-24">Status</th>
                    <th className="text-right px-2 py-1.5 w-16 hidden sm:table-cell">CPU</th>
                    <th className="text-right px-3 py-1.5 w-16 hidden sm:table-cell">MEM</th>
                  </tr>
                </thead>
                <tbody>
                  {group.services.map((svc) => {
                    const m = metrics[svc.name];
                    const status = m?.status ?? svc.status;
                    const sc = statusConfig[status] ?? statusConfig.unknown;
                    const badge = platformBadge[svc.platform] ?? platformBadge.vps;
                    const cpu = m?.cpu_percent ?? svc.cpu_percent ?? 0;
                    const mem = m?.memory_percent ?? svc.memory_percent ?? 0;
                    const isRunning = status === 'running';

                    return (
                      <tr key={svc.name} className={`border-t border-white/5 ${isRunning ? 'hover:bg-white/[0.04]' : 'opacity-60'}`}>
                        <td className="px-3 py-1.5">
                          <div className={`w-2.5 h-2.5 rounded-full ${sc.dot}`} />
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={`px-1 py-0.5 rounded text-[9px] font-bold ${badge.cls}`}>{badge.label}</span>
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={`font-medium ${isRunning ? 'text-gray-100' : 'text-gray-500'}`}>{svc.name}</span>
                        </td>
                        <td className="px-2 py-1.5 text-xs text-gray-500 hidden md:table-cell">{svc.pod ?? 'host'}</td>
                        <td className="px-2 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${sc.bg}`}>{sc.label}</span>
                        </td>
                        <td className={`px-2 py-1.5 text-right text-xs hidden sm:table-cell ${isRunning && cpu > 0 ? 'text-[color:var(--vps-cyan)]' : 'text-white/25'}`}>
                          {isRunning ? `${cpu.toFixed(1)}%` : ''}
                        </td>
                        <td className={`px-3 py-1.5 text-right text-xs hidden sm:table-cell ${isRunning && mem > 0 ? 'text-[color:var(--host-purple)]' : 'text-white/25'}`}>
                          {isRunning ? `${mem.toFixed(1)}%` : ''}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </GlassPanel>
        );
      })}
    </div>
  );
}
