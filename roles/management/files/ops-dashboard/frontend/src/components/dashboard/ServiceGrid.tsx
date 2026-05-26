import { useCallback, useMemo, useState } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import { groupServices } from '../../lib/stackGroups';
import { StackGroup } from './StackGroup';
import { DetailsModal } from '../details/DetailsModal';

export function ServiceGrid() {
  const { services, metrics } = useDashboard();
  const [openName, setOpenName] = useState<string | null>(null);

  const closeDetails = useCallback(() => setOpenName(null), []);

  // Merge metrics status into services
  const enriched = useMemo(() => {
    return services.map((svc) => {
      const m = metrics[svc.name];
      return m ? { ...svc, status: m.status, cpu_percent: m.cpu_percent, memory_percent: m.memory_percent } : svc;
    });
  }, [services, metrics]);

  // Group services
  const groups = useMemo(() => groupServices(enriched), [enriched]);

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group) => (
        <StackGroup key={group.key} title={group.title} subtitle={group.subtitle} services={group.services} onOpenDetails={setOpenName} />
      ))}
      <DetailsModal name={openName} onClose={closeDetails} />
    </div>
  );
}
