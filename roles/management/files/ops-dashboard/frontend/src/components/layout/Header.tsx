import { useDashboard } from '../../contexts/DashboardContext';

export function Header() {
  const { wsConnected } = useDashboard();
  return (
    <header className="safe-top sticky top-0 z-30 backdrop-blur-xl border-b border-white/5 bg-[var(--bg-base)]/80">
      <div className="mx-auto max-w-7xl px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-400/80 to-blue-600/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]" />
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight">Ops Dashboard</div>
            <div className="hidden sm:block text-[11px] text-white/50">ops.aicortex.cloud</div>
          </div>
        </div>
        <div
          className={`glass px-3 py-1.5 rounded-full text-[11px] font-medium flex items-center gap-2 ${
            wsConnected ? 'text-emerald-300' : 'text-rose-300'
          }`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-400' : 'bg-rose-400'}`} />
          {wsConnected ? 'Live' : 'Disconnected'}
        </div>
      </div>
    </header>
  );
}
