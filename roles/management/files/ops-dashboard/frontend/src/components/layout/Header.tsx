import { useDashboard } from '../../contexts/DashboardContext';

export function Header() {
  const { activeProfile, wsConnected } = useDashboard();

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-gray-900 border-b border-gray-800">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-bold text-blue-400">AICORTEX Ops</h1>
        <span className="text-xs text-gray-500">Infrastructure Control Panel</span>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-400">
          Profile: <span className="text-cyan-400 font-semibold">{activeProfile}</span>
        </span>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-[10px] text-gray-500">{wsConnected ? 'LIVE' : 'OFFLINE'}</span>
        </div>
      </div>
    </header>
  );
}
