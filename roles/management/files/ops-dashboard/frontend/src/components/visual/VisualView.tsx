import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useDashboard } from '../../contexts/DashboardContext';
import { CookingPan } from './CookingPan';

// Shape components for profiles
const profileShapes: Record<string, { shape: string; color: string }> = {
  minimal:          { shape: 'triangle', color: '#06b6d4' },
  'chat-only':      { shape: 'circle',   color: '#22c55e' },
  'full-stack':     { shape: 'star',     color: '#f59e0b' },
  'inference-heavy': { shape: 'pentagon', color: '#a855f7' },
  'media-production': { shape: 'hexagon', color: '#ec4899' },
};

function ProfileShape({ color, isActive }: { color: string; isActive: boolean }) {
  return (
    <div className={`relative w-14 h-14 flex items-center justify-center ${isActive ? '' : 'opacity-50'}`}>
      <svg viewBox="0 0 50 50" className="w-full h-full">
        <polygon
          points="25,5 45,40 5,40"
          fill={isActive ? color : '#374151'}
          fillOpacity={isActive ? 0.9 : 0.5}
          stroke={color}
          strokeWidth={isActive ? 2.5 : 1}
        />
      </svg>
    </div>
  );
}

// Tier shape colors by stack
const stackColors: Record<string, string> = {
  monitoring: '#f59e0b',
  security: '#ef4444',
  auth: '#a855f7',
  'azure-ai': '#3b82f6',
  speech: '#14b8a6',
  comms: '#22c55e',
  frontend: '#ec4899',
  trading: '#84cc16',
};

// Toast notification
function Toast({ message, type, onDismiss }: { message: string; type: 'success' | 'error' | 'info'; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, type === 'error' ? 6000 : 4000);
    return () => clearTimeout(timer);
  }, [onDismiss, type]);

  const colors = {
    success: 'bg-green-900/90 border-green-500/50 text-green-300',
    error: 'bg-red-900/90 border-red-500/50 text-red-300',
    info: 'bg-blue-900/90 border-blue-500/50 text-blue-300',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.95 }}
      className={`px-4 py-2 rounded-lg border text-sm font-medium shadow-lg ${colors[type]}`}
    >
      {message}
    </motion.div>
  );
}

export function VisualView() {
  const { profiles, stacks, activeProfile, switchProfile, setStackTier, metrics } = useDashboard();
  const [profileLoading, setProfileLoading] = useState<string | null>(null);
  const [tierLoading, setTierLoading] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Array<{ id: number; message: string; type: 'success' | 'error' | 'info' }>>([]);
  let toastId = 0;

  // Touch-mode detection — used to disable any drag/pan handlers on coarse pointers.
  // (No onPan handlers are currently wired up in VisualView, but we expose this
  // for future CookingPan panning and to signal intent.)
  const isCoarse = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;
  void isCoarse;

  const addToast = (message: string, type: 'success' | 'error' | 'info') => {
    const id = Date.now() + (toastId++);
    setToasts((prev) => [...prev.slice(-3), { id, message, type }]);
  };

  const removeToast = (id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const handleProfileClick = async (name: string) => {
    if (profileLoading) return;
    setProfileLoading(name);
    addToast(`Deploying profile: ${name}...`, 'info');
    try {
      const result = await switchProfile(name, true);
      addToast(result.message, 'success');
    } catch (e: unknown) {
      addToast(e instanceof Error ? e.message : 'Failed to switch profile', 'error');
    } finally {
      setProfileLoading(null);
    }
  };

  const handleTierClick = async (stackName: string, tierName: string) => {
    if (tierLoading) return;
    const key = `${stackName}:${tierName}`;
    setTierLoading(key);
    addToast(`Setting ${stackName} to ${tierName}...`, 'info');
    try {
      await setStackTier(stackName, tierName);
      addToast(`${stackName} set to ${tierName}`, 'success');
    } catch (e: unknown) {
      addToast(e instanceof Error ? e.message : `Failed to set ${stackName} tier`, 'error');
    } finally {
      setTierLoading(null);
    }
  };

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-7xl w-full px-4 md:px-6 py-4">
        <div className="flex gap-3 md:gap-4 min-h-[60dvh] relative">
          {/* Toast notifications */}
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 items-center">
            <AnimatePresence>
              {toasts.map((t) => (
                <Toast key={t.id} message={t.message} type={t.type} onDismiss={() => removeToast(t.id)} />
              ))}
            </AnimatePresence>
          </div>

          {/* Full-screen loading overlay for profile switches */}
          <AnimatePresence>
            {profileLoading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="absolute inset-0 z-40 rounded-[var(--r-lg)] bg-black/40 backdrop-blur-sm flex items-center justify-center"
              >
                <div className="flex flex-col items-center gap-3">
                  <svg className="animate-spin h-8 w-8 text-cyan-400" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span className="text-cyan-400 text-sm font-semibold">Deploying {profileLoading}...</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Left: Profile Shapes */}
          <aside className="hidden md:flex glass rounded-[var(--r-lg)] w-48 flex-shrink-0 p-3 overflow-y-auto flex-col gap-2">
            <h3 className="text-xs font-bold text-white/50 uppercase tracking-wider mb-1">Profiles</h3>
            {profiles.map((p) => {
              const conf = profileShapes[p.name] ?? { shape: 'circle', color: '#6b7280' };
              const isActive = activeProfile === p.name;
              const isLoading = profileLoading === p.name;
              return (
                <motion.button
                  key={p.name}
                  onClick={() => handleProfileClick(p.name)}
                  disabled={!!profileLoading}
                  whileHover={profileLoading ? {} : { scale: 1.03 }}
                  whileTap={profileLoading ? {} : { scale: 0.97 }}
                  className={`flex items-center gap-2 p-2 rounded-[var(--r-md)] transition-colors w-full text-left border
                    ${isActive
                      ? 'bg-white/10 border-white/20'
                      : 'bg-white/[0.03] border-white/10 hover:bg-white/[0.07]'
                    }
                    ${profileLoading && !isLoading ? 'opacity-30 cursor-not-allowed' : ''}
                    ${isLoading ? 'animate-pulse' : ''}`}
                >
                  <ProfileShape color={conf.color} isActive={isActive || isLoading} />
                  <div className="min-w-0 flex-1">
                    <div className={`text-xs font-bold truncate ${isActive ? 'text-white' : 'text-white/60'}`}>
                      {p.name}
                    </div>
                    <div className="text-[10px] text-white/40 truncate">{p.enabled_count} services</div>
                    {p.estimated_cost_per_hour != null && p.estimated_cost_per_hour > 0 && (
                      <div className="text-[10px] text-yellow-400/90">${p.estimated_cost_per_hour.toFixed(2)}/hr</div>
                    )}
                  </div>
                </motion.button>
              );
            })}
          </aside>

          {/* Center: The Cooking Pan — glass canvas */}
          <section className="glass rounded-[var(--r-lg)] flex-1 p-4 md:p-6 min-h-[50dvh] relative overflow-hidden flex flex-col items-center justify-center">
            {/* decorative radial backdrop */}
            <div
              className="pointer-events-none absolute inset-0 opacity-60"
              style={{
                background:
                  'radial-gradient(800px 600px at 30% 20%, rgba(100,210,255,0.08), transparent 60%), radial-gradient(600px 400px at 70% 80%, rgba(10,132,255,0.06), transparent 55%)',
              }}
            />
            <div className="relative w-full flex flex-col items-center justify-center">
              <CookingPan />
              {/* Running count */}
              <div className="mt-2 text-center">
                <span className="text-lg font-bold text-white/80">
                  {Object.values(metrics).filter((m) => m.status === 'running').length}
                </span>
                <span className="text-sm text-white/50 ml-1">services cooking</span>
              </div>
            </div>
          </section>

          {/* Right: Stack Tiers (hidden on mobile + tablet) */}
          <aside className="hidden lg:flex glass rounded-[var(--r-lg)] w-52 flex-shrink-0 p-3 overflow-y-auto flex-col gap-3">
            <h3 className="text-xs font-bold text-white/50 uppercase tracking-wider mb-1">Stack Tiers</h3>
            {stacks.map((stack) => {
              const color = stackColors[stack.name] ?? '#6b7280';
              return (
                <div key={stack.name} className="flex flex-col gap-1">
                  <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color }}>
                    {stack.name}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {stack.tier_names.map((tier) => {
                      const isActive = stack.current_tier === tier;
                      const tierKey = `${stack.name}:${tier}`;
                      const isLoading = tierLoading === tierKey;
                      return (
                        <motion.button
                          key={tier}
                          onClick={() => handleTierClick(stack.name, tier)}
                          disabled={!!tierLoading || !!profileLoading}
                          whileHover={tierLoading ? {} : { scale: 1.06 }}
                          whileTap={tierLoading ? {} : { scale: 0.94 }}
                          className={`glass rounded-full px-2 py-1 text-[11px] font-semibold transition-colors
                            ${isLoading ? 'animate-pulse' : ''}
                            ${isActive
                              ? 'bg-white/15 border-white/20 text-white'
                              : 'text-white/70 hover:bg-white/10'
                            }
                            ${(tierLoading || profileLoading) && !isLoading ? 'opacity-30 cursor-not-allowed' : ''}`}
                          style={isActive || isLoading ? { color } : {}}
                        >
                          {isLoading ? '...' : tier === 'off' ? 'Off' : tier}
                        </motion.button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </aside>
        </div>
      </div>
    </main>
  );
}
