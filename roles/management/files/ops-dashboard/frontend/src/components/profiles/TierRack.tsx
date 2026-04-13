import { useDashboard } from '../../contexts/DashboardContext';

export function TierRack() {
  const { stacks, setStackTier } = useDashboard();

  if (stacks.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider px-1">Stack Tiers</h3>
      {stacks.map((stack) => (
        <div key={stack.name} className="border border-gray-700 rounded-lg p-3 bg-gray-800/30">
          <div className="text-sm font-bold text-cyan-400 mb-1">{stack.name.toUpperCase()}</div>
          <div className="text-[10px] text-gray-500 mb-2">{stack.description}</div>
          <div className="flex flex-col gap-1">
            {stack.tier_names.map((tier) => (
              <button
                key={tier}
                onClick={() => setStackTier(stack.name, tier)}
                className={`text-left px-2 py-1 rounded text-xs transition-colors
                  ${tier === stack.current_tier
                    ? 'bg-cyan-900/40 text-cyan-300 border border-cyan-600/40'
                    : 'text-gray-400 hover:bg-gray-700/50 hover:text-gray-300 border border-transparent'
                  }`}
              >
                {tier === 'off' ? 'Off' : tier}
                {tier !== 'off' && (
                  <span className="ml-1 text-gray-600">
                    ({stack.tiers.find((t) => t.name === tier)?.services.length ?? 0} svc)
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
