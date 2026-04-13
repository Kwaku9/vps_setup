import { useState } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import type { Service } from '../../types';
import { computeVibration, intensityColors, intensityGlow } from '../../utils/vibration';
import { VibrationWrapper } from '../animations/VibrationWrapper';

const statusConfig: Record<string, { dot: string; label: string; labelColor: string }> = {
  running: { dot: 'bg-green-500 shadow-green-500/50 shadow-sm', label: 'Running', labelColor: 'text-green-400 bg-green-900/40' },
  stopped: { dot: 'bg-red-700', label: 'Stopped', labelColor: 'text-red-400 bg-red-900/30' },
  exited: { dot: 'bg-red-700', label: 'Exited', labelColor: 'text-red-400 bg-red-900/30' },
  warming: { dot: 'bg-yellow-500 animate-pulse', label: 'Warming', labelColor: 'text-yellow-400 bg-yellow-900/30' },
  scaling: { dot: 'bg-yellow-500 animate-pulse', label: 'Scaling', labelColor: 'text-yellow-400 bg-yellow-900/30' },
  starting: { dot: 'bg-green-400 animate-pulse', label: 'Starting...', labelColor: 'text-green-300 bg-green-900/40 animate-pulse' },
  stopping: { dot: 'bg-orange-400 animate-pulse', label: 'Stopping...', labelColor: 'text-orange-300 bg-orange-900/40 animate-pulse' },
  unknown: { dot: 'bg-gray-600', label: 'Unknown', labelColor: 'text-gray-500 bg-gray-800/50' },
  error: { dot: 'bg-red-500 animate-pulse', label: 'Error', labelColor: 'text-red-500 bg-red-900/50' },
};

const platformBadge: Record<string, { bg: string; text: string; label: string }> = {
  vps: { bg: 'bg-cyan-900/60 border border-cyan-700/30', text: 'text-cyan-400', label: 'VPS' },
  azure: { bg: 'bg-blue-900/60 border border-blue-700/30', text: 'text-blue-400', label: 'AZR' },
  host: { bg: 'bg-purple-900/60 border border-purple-700/30', text: 'text-purple-400', label: 'HST' },
};

interface Props {
  service: Service;
}

export function ServiceCard({ service }: Props) {
  const { metrics, pendingActions, startService, stopService } = useDashboard();
  const m = metrics[service.name];
  const cpu = m?.cpu_percent ?? service.cpu_percent ?? 0;
  const mem = m?.memory_percent ?? service.memory_percent ?? 0;
  const baseStatus = m?.status ?? service.status;
  const pending = pendingActions[service.name];
  const displayStatus = pending
    ? (pending.action === 'start' ? 'starting' : 'stopping')
    : baseStatus;
  const isRunning = baseStatus === 'running';

  const vibration = isRunning ? computeVibration(cpu, mem) : computeVibration(0, 0);
  const badge = platformBadge[service.platform] ?? platformBadge.vps;
  const borderColor = intensityColors[vibration.intensity] ?? 'border-gray-700';
  const glow = intensityGlow[vibration.intensity] ?? '';
  const sc = statusConfig[displayStatus] ?? statusConfig.unknown;

  const [actionLoading, setActionLoading] = useState(false);

  const handleToggle = async () => {
    setActionLoading(true);
    try {
      if (isRunning) {
        await stopService(service.name);
      } else {
        await startService(service.name);
      }
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <VibrationWrapper params={vibration}>
      <div
        className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${borderColor} ${glow}
          ${isRunning ? 'bg-gray-800/60' : 'bg-gray-900/40 opacity-50'}
          hover:bg-gray-800/80 transition-all duration-300`}
      >
        {/* Status dot */}
        <div className={`w-3 h-3 rounded-full flex-shrink-0 ${sc.dot}`} />

        {/* Platform badge */}
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${badge.bg} ${badge.text} flex-shrink-0`}>
          {badge.label}
        </span>

        {/* Name + description */}
        <div className="flex-1 min-w-0">
          <span className={`text-sm font-semibold ${isRunning ? 'text-gray-100' : 'text-gray-400'}`}>
            {service.name}
          </span>
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

        {/* Metrics */}
        {isRunning && (cpu > 0 || mem > 0) && (
          <div className="text-[10px] flex-shrink-0 hidden md:flex gap-2">
            <span className="text-cyan-400">CPU {cpu.toFixed(1)}%</span>
            <span className="text-purple-400">MEM {mem.toFixed(1)}%</span>
          </div>
        )}

        {/* Cost */}
        {service.cost_per_hour != null && service.cost_per_hour > 0 && (
          <span className="text-[10px] text-yellow-500 font-semibold flex-shrink-0">
            ${service.cost_per_hour.toFixed(2)}/hr
          </span>
        )}

        {/* Start/Stop button */}
        <button
          onClick={handleToggle}
          disabled={actionLoading}
          className={`px-2.5 py-1 rounded text-[10px] font-bold flex-shrink-0 transition-colors min-w-[52px]
            ${actionLoading
              ? 'bg-gray-800/60 text-gray-500 border border-gray-700/30 cursor-wait'
              : isRunning
                ? 'bg-red-900/60 text-red-400 hover:bg-red-700/70 border border-red-700/30'
                : 'bg-green-900/60 text-green-400 hover:bg-green-700/70 border border-green-700/30'
            }`}
        >
          {actionLoading ? (
            <svg className="animate-spin h-3 w-3 mx-auto" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : isRunning ? 'STOP' : 'START'}
        </button>
      </div>
    </VibrationWrapper>
  );
}
