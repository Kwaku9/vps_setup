interface Props {
  activeTab: string;
  onTabChange: (t: string) => void;
}

const ITEMS = [
  { key: 'dashboard', label: 'Overview', icon: '⌂' },
  { key: 'sessions',  label: 'Sessions', icon: '◈' },
  { key: 'manager',   label: 'Manager',  icon: '☷' },
  { key: 'visual',    label: 'Visual',   icon: '◉' },
] as const;

export function MobileNav({ activeTab, onTabChange }: Props) {
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-30 safe-bottom bg-[var(--bg-base)]/85 backdrop-blur-xl border-t border-white/8">
      <div className="grid grid-cols-4">
        {ITEMS.map((it) => {
          const active = activeTab === it.key;
          return (
            <button
              key={it.key}
              onClick={() => onTabChange(it.key)}
              className={`relative flex flex-col items-center justify-center gap-0.5 py-2 min-h-[56px] ${
                active ? 'text-cyan-300' : 'text-white/55'
              }`}
            >
              <span className="text-lg leading-none">{it.icon}</span>
              <span className="text-[10px] font-semibold tracking-wide">{it.label}</span>
              {active && <span className="absolute bottom-1 h-0.5 w-6 rounded-full bg-cyan-400" />}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
