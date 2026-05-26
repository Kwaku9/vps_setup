import type { ReactNode } from 'react';
import { GlassPanel } from '../ui/GlassPanel';

interface Props {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
  icon?: ReactNode;
}

export function StatTile({ label, value, sub, accent, icon }: Props) {
  return (
    <GlassPanel className="px-4 py-3 flex items-center gap-3 min-h-[80px]">
      {icon && <div className="flex-shrink-0 opacity-70">{icon}</div>}
      <div className="min-w-0 flex-1">
        <div className="text-[11px] uppercase tracking-wider text-white/50 truncate">{label}</div>
        <div className="text-2xl font-semibold tabular-nums leading-tight" style={{ color: accent ?? 'inherit' }}>
          {value}
        </div>
        {sub && <div className="text-[11px] text-white/40 truncate">{sub}</div>}
      </div>
    </GlassPanel>
  );
}
