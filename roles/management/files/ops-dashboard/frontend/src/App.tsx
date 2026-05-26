import { useState } from 'react';
import { motion } from 'framer-motion';
import { DashboardProvider, useDashboard } from './contexts/DashboardContext';
import { ToastProvider } from './contexts/ToastContext';
import { ToastHost } from './components/ui/Toast';
import { Header } from './components/layout/Header';
import { StatusBar } from './components/layout/StatusBar';
import { BottomSheet } from './components/layout/BottomSheet';
import { ServiceGrid } from './components/dashboard/ServiceGrid';
import { OverviewView } from './components/overview/OverviewView';
import { ProfileRack } from './components/profiles/ProfileRack';
import { TierRack } from './components/profiles/TierRack';
import { VisualView } from './components/visual/VisualView';
import { pop } from './lib/motion';

const TABS = [
  { key: 'dashboard', label: 'Overview' },
  { key: 'manager',   label: 'Manager' },
  { key: 'visual',    label: 'Visual' },
] as const;

function TabNav({ activeTab, onTabChange }: { activeTab: string; onTabChange: (tab: string) => void }) {
  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pt-2 pb-3">
      <div className="glass rounded-full p-1 inline-flex relative">
        {TABS.map((t) => {
          const active = activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => onTabChange(t.key)}
              className="relative px-4 py-1.5 text-[13px] font-semibold rounded-full"
            >
              {active && (
                <motion.span
                  layoutId="tab-pill"
                  transition={pop}
                  className="absolute inset-0 rounded-full bg-white/10 border border-white/10"
                />
              )}
              <span className={`relative ${active ? 'text-white' : 'text-white/60'}`}>{t.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ManagerTab() {
  const [sheet, setSheet] = useState<null | 'profiles' | 'tiers'>(null);
  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pb-24 lg:pb-6">
      <div className="lg:grid lg:grid-cols-[13rem_1fr_14rem] lg:gap-4">
        <aside className="hidden lg:block"><ProfileRack /></aside>
        <main className="min-w-0"><ServiceGrid /></main>
        <aside className="hidden lg:block"><TierRack /></aside>
      </div>

      {/* Mobile floating buttons */}
      <div className="lg:hidden fixed bottom-4 left-0 right-0 z-30 flex justify-center gap-2 px-4 safe-bottom">
        <button onClick={() => setSheet('profiles')} className="glass rounded-full px-4 py-2 text-[13px] font-semibold">Profiles</button>
        <button onClick={() => setSheet('tiers')}    className="glass rounded-full px-4 py-2 text-[13px] font-semibold">Tiers</button>
      </div>

      <BottomSheet open={sheet === 'profiles'} onClose={() => setSheet(null)} title="Profiles">
        <ProfileRack />
      </BottomSheet>
      <BottomSheet open={sheet === 'tiers'} onClose={() => setSheet(null)} title="Stack Tiers">
        <TierRack />
      </BottomSheet>
    </div>
  );
}

function DashboardLayout() {
  const { loading } = useDashboard();
  const [activeTab, setActiveTab] = useState('dashboard');

  if (loading) {
    return (
      <div className="min-h-[100dvh] bg-gray-950 flex items-center justify-center">
        <div className="text-gray-400 text-lg">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-gray-950 text-gray-200 flex flex-col">
      <Header />
      <TabNav activeTab={activeTab} onTabChange={setActiveTab} />
      <StatusBar />

      {activeTab === 'dashboard' ? (
        <main className="flex-1 overflow-y-auto">
          <OverviewView />
        </main>
      ) : activeTab === 'visual' ? (
        <VisualView />
      ) : (
        <main className="flex-1 overflow-y-auto py-4">
          <ManagerTab />
        </main>
      )}
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <DashboardProvider>
        <DashboardLayout />
        <ToastHost />
      </DashboardProvider>
    </ToastProvider>
  );
}
