import { useDashboard } from '../../contexts/DashboardContext';

export function TierRack() {
  const { stacks, setStackTier } = useDashboard();

  if (stacks.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[11px] font-semibold text-white/50 tracking-wide uppercase mb-2 px-1">Stack Tiers</div>
      {stacks.map((stack) => (
        <div key={stack.name} className="flex flex-col gap-1.5">
          <div className="px-1">
            <div className="text-[12px] font-semibold text-white/80 tracking-wide">{stack.name.toUpperCase()}</div>
            <div className="text-[10px] text-white/50 mt-0.5">{stack.description}</div>
          </div>
          <div className="flex flex-col gap-1.5">
            {stack.tier_names.map((tier) => {
              const active = tier === stack.current_tier;
              const svcCount = stack.tiers.find((t) => t.name === tier)?.services.length ?? 0;
              return (
                <button
                  key={tier}
                  onClick={() => setStackTier(stack.name, tier)}
                  className={`glass rounded-2xl px-3.5 py-2.5 text-[13px] text-left transition-colors min-h-[44px] ${
                    active ? 'bg-white/15 border-white/20' : 'hover:bg-white/10 active:bg-white/15'
                  }`}
                >
                  <span className="font-semibold">{tier === 'off' ? 'Off' : tier}</span>
                  {tier !== 'off' && (
                    <span className="ml-1 text-white/40 text-[11px]">({svcCount} svc)</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
