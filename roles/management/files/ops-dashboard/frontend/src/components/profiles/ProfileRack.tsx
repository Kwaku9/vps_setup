import { useState } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import type { ProfileDiff } from '../../types';

export function ProfileRack() {
  const { profiles, activeProfile, switchProfile } = useDashboard();
  const [pendingDiff, setPendingDiff] = useState<{ name: string; diff: ProfileDiff } | null>(null);

  const handleClick = async (name: string) => {
    if (name === activeProfile) return;
    const result = await switchProfile(name, false);
    setPendingDiff({ name, diff: result.diff });
  };

  const handleConfirm = async () => {
    if (!pendingDiff) return;
    await switchProfile(pendingDiff.name, true);
    setPendingDiff(null);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[11px] font-semibold text-white/50 tracking-wide uppercase mb-2 px-1">Profiles</div>
      {profiles.map((p) => {
        const active = p.name === activeProfile;
        return (
          <button
            key={p.name}
            onClick={() => handleClick(p.name)}
            className={`glass rounded-full px-3 py-2 text-[13px] text-left transition-colors ${
              active ? 'bg-white/15 border-white/20' : 'hover:bg-white/10'
            }`}
          >
            <div className="font-semibold">{p.name}</div>
            <div className="text-[10px] text-white/50 mt-0.5">{p.description}</div>
            <div className="text-[10px] text-white/60 mt-1">
              <span className="text-[color:var(--status-green)]">{p.enabled_count}</span>
              <span className="text-white/40">/{p.enabled_count + p.disabled_count}</span>
              {p.estimated_cost_per_hour != null && p.estimated_cost_per_hour > 0 && (
                <span className="ml-2 text-yellow-500">${p.estimated_cost_per_hour.toFixed(2)}/hr</span>
              )}
            </div>
          </button>
        );
      })}

      {/* Diff confirmation modal */}
      {pendingDiff && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setPendingDiff(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-white mb-4">
              Switch to <span className="text-cyan-400">{pendingDiff.name}</span>?
            </h3>
            {pendingDiff.diff.starting.length > 0 && (
              <div className="mb-3">
                <div className="text-xs font-bold text-green-400 mb-1">Starting:</div>
                {pendingDiff.diff.starting.map((s) => (
                  <div key={s} className="text-sm text-green-300 ml-2">+ {s}</div>
                ))}
              </div>
            )}
            {pendingDiff.diff.stopping.length > 0 && (
              <div className="mb-3">
                <div className="text-xs font-bold text-red-400 mb-1">Stopping:</div>
                {pendingDiff.diff.stopping.map((s) => (
                  <div key={s} className="text-sm text-red-300 ml-2">- {s}</div>
                ))}
              </div>
            )}
            {pendingDiff.diff.starting.length === 0 && pendingDiff.diff.stopping.length === 0 && (
              <div className="text-sm text-gray-400 mb-3">No changes</div>
            )}
            <div className="flex gap-3 mt-4">
              <button
                onClick={handleConfirm}
                className="flex-1 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg font-semibold text-sm transition-colors"
              >
                Confirm
              </button>
              <button
                onClick={() => setPendingDiff(null)}
                className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg font-semibold text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
