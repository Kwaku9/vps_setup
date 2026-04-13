import { useState } from 'react';
import { DashboardProvider, useDashboard } from './contexts/DashboardContext';
import { Header } from './components/layout/Header';
import { StatusBar } from './components/layout/StatusBar';
import { ServiceGrid } from './components/dashboard/ServiceGrid';
import { StatusView } from './components/dashboard/StatusView';
import { ProfileRack } from './components/profiles/ProfileRack';
import { TierRack } from './components/profiles/TierRack';
import { VisualView } from './components/visual/VisualView';

function TabNav({ activeTab, onTabChange }: { activeTab: string; onTabChange: (tab: string) => void }) {
  return (
    <div className="flex border-b border-gray-800 bg-gray-900/50">
      <button
        onClick={() => onTabChange('dashboard')}
        className={`px-6 py-2 text-sm font-semibold transition-colors border-b-2 ${
          activeTab === 'dashboard'
            ? 'text-blue-400 border-blue-400'
            : 'text-gray-500 border-transparent hover:text-gray-300'
        }`}
      >
        Ops Dashboard
      </button>
      <button
        onClick={() => onTabChange('manager')}
        className={`px-6 py-2 text-sm font-semibold transition-colors border-b-2 ${
          activeTab === 'manager'
            ? 'text-cyan-400 border-cyan-400'
            : 'text-gray-500 border-transparent hover:text-gray-300'
        }`}
      >
        Ops Manager
      </button>
      <button
        onClick={() => onTabChange('visual')}
        className={`px-6 py-2 text-sm font-semibold transition-colors border-b-2 ${
          activeTab === 'visual'
            ? 'text-orange-400 border-orange-400'
            : 'text-gray-500 border-transparent hover:text-gray-300'
        }`}
      >
        Visual
      </button>
    </div>
  );
}

function DashboardLayout() {
  const { loading } = useDashboard();
  const [activeTab, setActiveTab] = useState('dashboard');

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-400 text-lg">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-200 flex flex-col">
      <Header />
      <TabNav activeTab={activeTab} onTabChange={setActiveTab} />
      <StatusBar />

      {activeTab === 'dashboard' ? (
        <main className="flex-1 p-4 overflow-y-auto">
          <StatusView />
        </main>
      ) : activeTab === 'visual' ? (
        <VisualView />
      ) : (
        <div className="flex flex-1 overflow-hidden">
          <aside className="w-52 flex-shrink-0 p-3 border-r border-gray-800 overflow-y-auto">
            <ProfileRack />
          </aside>
          <main className="flex-1 p-4 overflow-y-auto">
            <ServiceGrid />
          </main>
          <aside className="w-56 flex-shrink-0 p-3 border-l border-gray-800 overflow-y-auto">
            <TierRack />
          </aside>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <DashboardProvider>
      <DashboardLayout />
    </DashboardProvider>
  );
}
