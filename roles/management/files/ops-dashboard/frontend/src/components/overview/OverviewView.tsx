import { useCallback, useMemo, useState } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import { StatTile } from './StatTile';
import { TopNContainers } from './TopNContainers';
import { DetailsModal } from '../details/DetailsModal';

export function OverviewView() {
  const { services, metrics, profiles, activeProfile } = useDashboard();
  const [openName, setOpenName] = useState<string | null>(null);

  const closeDetails = useCallback(() => setOpenName(null), []);

  const stats = useMemo(() => {
    const running = services.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;
    const total = services.length;
    const stopped = total - running;
    const managed = services.filter((s) => s.managed).length;
    const unmanaged = total - managed;
    const active = profiles.find((p) => p.name === activeProfile);
    const cost = active?.estimated_cost_per_hour ?? 0;
    return { running, stopped, total, unmanaged, cost, active: active?.name ?? 'none' };
  }, [services, metrics, profiles, activeProfile]);

  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pt-4 pb-28 lg:pb-6 flex flex-col gap-4">
      {/* Top tiles — 2-up on phone, 3-up on tablet, 4-up on desktop */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
        <StatTile label="Running"   value={stats.running}   accent="var(--status-green)"  sub={`of ${stats.total} services`} />
        <StatTile label="Stopped"   value={stats.stopped}   accent="var(--status-red)"    sub="containers" />
        <StatTile label="Unmanaged" value={stats.unmanaged} accent="var(--status-yellow)" sub="auto-discovered" />
        <StatTile label="Profile"   value={stats.active}    sub={stats.cost != null && stats.cost > 0 ? `$${stats.cost.toFixed(2)}/hr` : 'free'} />
      </div>

      {/* Top-N tables */}
      <TopNContainers n={5} onOpen={setOpenName} />

      <DetailsModal name={openName} onClose={closeDetails} />
    </div>
  );
}
