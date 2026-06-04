import { useDashboard } from '../../contexts/DashboardContext';
import type { Service } from '../../types';
import { computeVibration } from '../../utils/vibration';
import { VibrationWrapper } from '../animations/VibrationWrapper';
import { Sparkline } from '../charts/Sparkline';
import { useTimeseries } from '../../hooks/useTimeseries';

const statusConfig: Record<string, { dot: string; label: string; labelColor: string }> = {
  running:  { dot: 'bg-[var(--status-green)] shadow-[0_0_0_2px_rgba(48,209,88,0.15)]', label: 'Running',   labelColor: 'text-emerald-300 bg-emerald-500/10' },
  stopped:  { dot: 'bg-[var(--status-red)]',                                             label: 'Stopped',   labelColor: 'text-rose-300 bg-rose-500/10' },
  exited:   { dot: 'bg-[var(--status-red)]',                                             label: 'Exited',    labelColor: 'text-rose-300 bg-rose-500/10' },
  warming:  { dot: 'bg-[var(--status-yellow)] animate-pulse',                            label: 'Warming',   labelColor: 'text-amber-300 bg-amber-500/10' },
  scaling:  { dot: 'bg-[var(--status-yellow)] animate-pulse',                            label: 'Scaling',   labelColor: 'text-amber-300 bg-amber-500/10' },
  starting: { dot: 'bg-[var(--status-green)] animate-pulse',                             label: 'Starting…', labelColor: 'text-emerald-200 bg-emerald-500/10' },
  stopping: { dot: 'bg-[var(--status-orange)] animate-pulse',                            label: 'Stopping…', labelColor: 'text-orange-200 bg-orange-500/10' },
  unknown:  { dot: 'bg-white/30',                                                        label: 'Unknown',   labelColor: 'text-white/50 bg-white/5' },
  error:    { dot: 'bg-[var(--status-red)] animate-pulse',                               label: 'Error',     labelColor: 'text-rose-300 bg-rose-500/15' },
};

const platformBadge: Record<string, { cls: string; label: string }> = {
  vps:   { cls: 'text-[color:var(--vps-cyan)]    bg-cyan-400/10 border border-cyan-400/20',    label: 'VPS' },
  azure: { cls: 'text-[color:var(--azure-blue)]  bg-blue-500/10 border border-blue-500/20',    label: 'AZR' },
  host:  { cls: 'text-[color:var(--host-purple)] bg-purple-500/10 border border-purple-500/20', label: 'HST' },
};

interface Props {
  service: Service;
  onOpenDetails?: (name: string) => void;
}

export function ServiceCard({ service, onOpenDetails }: Props) {
  const { metrics, pendingActions, startService, stopService } = useDashboard();
  const m = metrics[service.name];
  const cpu = m?.cpu_percent ?? service.cpu_percent ?? 0;
  const mem = m?.memory_percent ?? service.memory_percent ?? 0;
  const baseStatus = m?.status ?? service.status;
  const pending = pendingActions[service.name];
  const isBusy = !!pending;
  const displayStatus = pending
    ? (pending.action === 'start' ? 'starting' : 'stopping')
    : baseStatus;
  const isRunning = baseStatus === 'running';

  const { points: cpuPoints } = useTimeseries(service.name, 'cpu', 15, isRunning);
  const { points: memPoints } = useTimeseries(service.name, 'mem', 15, isRunning);

  const vibration = isRunning ? computeVibration(cpu, mem) : computeVibration(0, 0);
  const badge = platformBadge[service.platform] ?? platformBadge.vps;
  const sc = statusConfig[displayStatus] ?? statusConfig.unknown;

  const handleToggle = async () => {
    if (isRunning) {
      await stopService(service.name);
    } else {
      await startService(service.name);
    }
  };

  return (
    <VibrationWrapper params={vibration}>
      <div
        className={`relative flex items-center gap-3 px-3 py-2.5 rounded-[var(--r-md)]
          glass hover:bg-white/[0.08] transition-colors
          ${!isRunning ? 'opacity-60' : ''}`}
      >
        {/* Status dot */}
        <div className={`w-3 h-3 rounded-full flex-shrink-0 ${sc.dot}`} />

        {/* Platform badge */}
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${badge.cls} flex-shrink-0`}>
          {badge.label}
        </span>

        {/* Name + description */}
        <div className="flex-1 min-w-0">
          <button
            type="button"
            onClick={() => onOpenDetails?.(service.name)}
            className={`text-sm font-semibold text-left ${isRunning ? 'text-gray-100 hover:text-cyan-300' : 'text-gray-400'} truncate`}
          >
            {service.name}
          </button>
          {service.pod && (
            <span className="ml-2 text-[10px] text-gray-600">{service.pod}</span>
          )}
          {service.description && (
            <div className="text-[11px] text-gray-500 truncate">{service.description}</div>
          )}
        </div>

        {/* Live status badge */}
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold flex-shrink-0 ${sc.labelColor}`}>
          {sc.label}
        </span>

        {/* Metrics — show 0.0% as dim when idle so user knows it's measured */}
        {isRunning && (
          <div className="flex-shrink-0 hidden md:flex items-center gap-2 text-[10px]">
            <span className={cpu > 0 ? 'text-[color:var(--vps-cyan)]' : 'text-white/30'}>
              CPU {cpu.toFixed(1)}%
            </span>
            <Sparkline points={cpuPoints} baselineColor="#64d2ff" />
            <span className={mem > 0 ? 'text-[color:var(--host-purple)]' : 'text-white/30'}>
              MEM {mem.toFixed(1)}%
            </span>
            <Sparkline points={memPoints} baselineColor="#bf5af2" />
          </div>
        )}

        {/* Cost */}
        {service.cost_per_hour != null && service.cost_per_hour > 0 && (
          <span className="text-[10px] text-yellow-500 font-semibold flex-shrink-0">
            ${service.cost_per_hour.toFixed(2)}/hr
          </span>
        )}

        {/* Start/Stop button (hidden for pod-infra containers) */}
        {!service.name.endsWith('-infra') ? (
          <button
            onClick={handleToggle}
            disabled={isBusy}
            className={`px-2.5 py-1 rounded-full text-[10px] font-bold flex-shrink-0 transition-colors min-w-[60px]
              ${isBusy
                ? 'glass text-white/40 cursor-wait'
                : isRunning
                  ? 'glass text-rose-300 hover:bg-rose-500/15'
                  : 'glass text-emerald-300 hover:bg-emerald-500/15'
              }`}
          >
            {isBusy ? (
              <svg className="animate-spin h-3 w-3 mx-auto" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : isRunning ? 'STOP' : 'START'}
          </button>
        ) : (
          <span
            className="glass px-2 py-1 rounded-full text-[10px] font-semibold flex-shrink-0 text-white/40"
            title="Pod infrastructure container — use `podman pod stop <pod>` to control its pod"
          >
            INFRA
          </span>
        )}
        {isRunning && (
          <div className="absolute bottom-0 left-0 right-0 h-[2px] flex pointer-events-none rounded-b-[var(--r-md)] overflow-hidden">
            <div
              className="h-full transition-all duration-500"
              style={{
                width: `${Math.min(cpu, 100)}%`,
                background: cpu > 80 ? 'var(--status-red)' : cpu > 50 ? 'var(--status-yellow)' : 'var(--vps-cyan)',
                opacity: 0.65,
              }}
            />
            <div
              className="h-full transition-all duration-500"
              style={{
                width: `${Math.min(mem, 100)}%`,
                background: mem > 80 ? 'var(--status-red)' : mem > 50 ? 'var(--status-yellow)' : 'var(--host-purple)',
                opacity: 0.55,
              }}
            />
          </div>
        )}
      </div>
    </VibrationWrapper>
  );
}
