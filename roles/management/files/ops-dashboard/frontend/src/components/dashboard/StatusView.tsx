import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import type { Service } from '../../types';

const statusConfig: Record<string, { dot: string; label: string; bg: string }> = {
  running: { dot: 'bg-green-500', label: 'Running', bg: 'text-green-400 bg-green-900/40' },
  stopped: { dot: 'bg-red-700', label: 'Stopped', bg: 'text-red-400 bg-red-900/30' },
  exited: { dot: 'bg-red-700', label: 'Exited', bg: 'text-red-400 bg-red-900/30' },
  unknown: { dot: 'bg-gray-600', label: 'Unknown', bg: 'text-gray-500 bg-gray-800/50' },
};

const platformBadge: Record<string, { cls: string; label: string }> = {
  vps: { cls: 'bg-cyan-900/60 text-cyan-400 border-cyan-700/30', label: 'VPS' },
  azure: { cls: 'bg-blue-900/60 text-blue-400 border-blue-700/30', label: 'AZR' },
  host: { cls: 'bg-purple-900/60 text-purple-400 border-purple-700/30', label: 'HST' },
};

const GROUPS = [
  { key: 'core', title: 'CORE', match: (s: Service) => ['traefik', 'cloudflared', 'shared-db', 'victoria-metrics', 'fail2ban', 'node-exporter', 'iptables', 'crond', 'squid'].includes(s.name) },
  { key: 'security', title: 'SECURITY', match: (s: Service) => ['crowdsec', 'tetragon'].includes(s.name) },
  { key: 'auth', title: 'AUTH', match: (s: Service) => ['authentik-server', 'authentik-worker', 'authentik-postgres', 'redis'].includes(s.name) },
  { key: 'azure-ai', title: 'AZURE AI', match: (s: Service) => ['litellm', 'open-webui', 'whisper-stt', 'kokoro-tts'].includes(s.name) || s.platform === 'azure' },
  { key: 'monitoring', title: 'MONITORING', match: (s: Service) => ['alloy', 'loki', 'grafana', 'renderer', 'tempo'].includes(s.name) },
  { key: 'comms', title: 'COMMS', match: (s: Service) => s.name === 'telegram-gateway' },
  { key: 'frontend', title: 'FRONTEND', match: (s: Service) => ['journey-tracker', 'worldview-dev', 'ais-relay'].includes(s.name) },
  { key: 'mgmt', title: 'MANAGEMENT', match: (s: Service) => ['portainer', 'ansible-deployment'].includes(s.name) },
];

export function StatusView() {
  const { services, metrics } = useDashboard();

  const enriched = useMemo(() => {
    return services.map((svc) => {
      const m = metrics[svc.name];
      return m ? { ...svc, status: m.status, cpu_percent: m.cpu_percent, memory_percent: m.memory_percent } : svc;
    });
  }, [services, metrics]);

  const groups = useMemo(() => {
    const assigned = new Set<string>();
    return GROUPS.map((g) => {
      const matched = enriched.filter((s) => {
        if (assigned.has(s.name)) return false;
        if (g.match(s)) { assigned.add(s.name); return true; }
        return false;
      });
      return { ...g, services: matched };
    }).filter((g) => g.services.length > 0);
  }, [enriched]);

  const totalRunning = enriched.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;
  const totalStopped = enriched.length - totalRunning;

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center gap-6 mb-6 text-sm">
        <span><span className="text-green-500 font-bold text-lg">{totalRunning}</span> <span className="text-gray-500">running</span></span>
        <span><span className="text-red-400 font-bold text-lg">{totalStopped}</span> <span className="text-gray-500">stopped</span></span>
        <span><span className="text-gray-300 font-bold text-lg">{enriched.length}</span> <span className="text-gray-500">total services</span></span>
      </div>

      {groups.map((group) => {
        const running = group.services.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;
        return (
          <div key={group.key} className="mb-4">
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-800/60 rounded-t-lg border border-gray-700">
              <span className="text-sm font-bold text-blue-400">{group.title}</span>
              <span className="text-xs text-gray-500">
                {running}/{group.services.length} running
              </span>
            </div>
            <div className="border border-t-0 border-gray-700 rounded-b-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-900/60 text-xs text-gray-400">
                    <th className="text-left px-3 py-1.5 w-8"></th>
                    <th className="text-left px-2 py-1.5 w-12">Type</th>
                    <th className="text-left px-2 py-1.5">Service</th>
                    <th className="text-left px-2 py-1.5">Location</th>
                    <th className="text-left px-2 py-1.5 w-20">Status</th>
                    <th className="text-right px-2 py-1.5 w-16">CPU</th>
                    <th className="text-right px-3 py-1.5 w-16">MEM</th>
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
                      <tr key={svc.name} className={`border-t border-gray-800 ${isRunning ? 'hover:bg-gray-800/40' : 'opacity-50'}`}>
                        <td className="px-3 py-1.5">
                          <div className={`w-2.5 h-2.5 rounded-full ${sc.dot}`} />
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={`px-1 py-0.5 rounded text-[9px] font-bold border ${badge.cls}`}>{badge.label}</span>
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={`font-medium ${isRunning ? 'text-gray-100' : 'text-gray-500'}`}>{svc.name}</span>
                        </td>
                        <td className="px-2 py-1.5 text-xs text-gray-500">{svc.pod ?? 'host'}</td>
                        <td className="px-2 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${sc.bg}`}>{sc.label}</span>
                        </td>
                        <td className="px-2 py-1.5 text-right text-xs text-cyan-400">{isRunning && cpu > 0 ? `${cpu.toFixed(1)}%` : ''}</td>
                        <td className="px-3 py-1.5 text-right text-xs text-purple-400">{isRunning && mem > 0 ? `${mem.toFixed(1)}%` : ''}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
