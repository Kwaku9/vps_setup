import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import { GlassPanel } from '../ui/GlassPanel';
import { Sparkline } from '../charts/Sparkline';
import { useTimeseries } from '../../hooks/useTimeseries';

interface Row {
  name: string;
  cpu: number;
  mem: number;
}

function Entry({ row, metric, onOpen }: {
  row: Row;
  metric: 'cpu' | 'mem';
  onOpen?: (n: string) => void;
}) {
  const { points } = useTimeseries(row.name, metric, 15, true);
  const baselineColor = metric === 'cpu' ? '#64d2ff' : '#bf5af2';
  return (
    <button
      type="button"
      onClick={() => onOpen?.(row.name)}
      className="w-full flex items-center gap-3 px-3 py-2 hover:bg-white/[0.04] transition-colors text-left"
    >
      <span className="font-medium text-gray-100 truncate flex-1">{row.name}</span>
      <Sparkline points={points} width={60} height={16} baselineColor={baselineColor} />
      <span className="text-[color:var(--vps-cyan)] text-xs tabular-nums w-12 text-right">{row.cpu.toFixed(1)}%</span>
      <span className="text-[color:var(--host-purple)] text-xs tabular-nums w-12 text-right">{row.mem.toFixed(1)}%</span>
    </button>
  );
}

export function TopNContainers({ n = 5, onOpen }: { n?: number; onOpen?: (name: string) => void }) {
  const { metrics } = useDashboard();
  const top = useMemo(() => {
    const rows: Row[] = Object.values(metrics)
      .filter((m) => m.status === 'running')
      .map((m) => ({ name: m.service_name, cpu: m.cpu_percent ?? 0, mem: m.memory_percent ?? 0 }));
    const topCpu = [...rows].sort((a, b) => b.cpu - a.cpu).slice(0, n);
    const topMem = [...rows].sort((a, b) => b.mem - a.mem).slice(0, n);
    return { topCpu, topMem };
  }, [metrics, n]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <GlassPanel as="section" className="overflow-hidden">
        <div className="px-4 pt-3 pb-2 text-[13px] font-semibold tracking-wide">Top CPU</div>
        <div className="flex flex-col">
          {top.topCpu.map((r) => <Entry key={r.name} row={r} metric="cpu" onOpen={onOpen} />)}
          {top.topCpu.length === 0 && <div className="px-4 py-3 text-xs text-white/40">No running containers.</div>}
        </div>
      </GlassPanel>
      <GlassPanel as="section" className="overflow-hidden">
        <div className="px-4 pt-3 pb-2 text-[13px] font-semibold tracking-wide">Top Memory</div>
        <div className="flex flex-col">
          {top.topMem.map((r) => <Entry key={r.name} row={r} metric="mem" onOpen={onOpen} />)}
          {top.topMem.length === 0 && <div className="px-4 py-3 text-xs text-white/40">No running containers.</div>}
        </div>
      </GlassPanel>
    </div>
  );
}
