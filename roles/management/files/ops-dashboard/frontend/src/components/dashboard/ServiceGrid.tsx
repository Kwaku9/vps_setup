import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import { groupServices } from '../../lib/stackGroups';
import { StackGroup } from './StackGroup';

export function ServiceGrid() {
  const { services, metrics } = useDashboard();

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
        <StackGroup key={group.key} title={group.title} subtitle={group.subtitle} services={group.services} />
      ))}
    </div>
  );
}
