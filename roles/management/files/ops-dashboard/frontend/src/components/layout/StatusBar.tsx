import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';

export function StatusBar() {
  const { services, metrics } = useDashboard();

  const counts = useMemo(() => {
    let running = 0;
    let stopped = 0;
    for (const svc of services) {
      const status = metrics[svc.name]?.status ?? svc.status;
      if (status === 'running') running++;
      else stopped++;
    }
    return { running, stopped, total: services.length };
  }, [services, metrics]);

  return (
    <div className="flex items-center gap-6 px-6 py-1.5 bg-gray-800/50 border-b border-gray-800 text-xs">
      <span>
        <span className="text-green-500 font-bold">{counts.running}</span>
        <span className="text-gray-500"> running</span>
      </span>
      <span>
        <span className="text-red-400 font-bold">{counts.stopped}</span>
        <span className="text-gray-500"> stopped</span>
      </span>
      <span>
        <span className="text-gray-400 font-bold">{counts.total}</span>
        <span className="text-gray-500"> total</span>
      </span>
    </div>
  );
}
