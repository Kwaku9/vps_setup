import { useDashboard } from '../../contexts/DashboardContext';

export function StatusBar() {
  const { services, metrics, activeProfile } = useDashboard();
  const running = services.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;
  const stopped = services.length - running;
  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pt-3 pb-1 flex flex-wrap items-center gap-2 text-[12px]">
      <StatChip color="emerald" label="running" value={running} />
      <StatChip color="rose"    label="stopped" value={stopped} />
      <StatChip color="slate"   label="total"   value={services.length} />
      {activeProfile && activeProfile !== 'none' && (
        <span className="glass rounded-full px-3 py-1 inline-flex items-center gap-1.5 text-white/80">
          <span className="text-white/50">profile</span>
          <span className="font-semibold text-[color:var(--vps-cyan)]">{activeProfile}</span>
        </span>
      )}
    </div>
  );
}

function StatChip({ color, label, value }: { color: 'emerald' | 'rose' | 'slate'; label: string; value: number }) {
  const tint = {
    emerald: 'text-emerald-300',
    rose:    'text-rose-300',
    slate:   'text-white/70',
  }[color];
  return (
    <span className="glass rounded-full px-3 py-1 inline-flex items-center gap-1.5">
      <span className={`font-semibold ${tint}`}>{value}</span>
      <span className="text-white/50">{label}</span>
    </span>
  );
}
