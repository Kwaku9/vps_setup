import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import type { ActionResult, MetricsSnapshot, Profile, Service, Stack, SwitchResult } from '../types';

const ACTION_GRACE_MS = 15_000; // ignore WS overwrites for 15s after an action

interface PendingAction {
  action: 'start' | 'stop';
  timestamp: number;
}

interface DashboardState {
  services: Service[];
  profiles: Profile[];
  stacks: Stack[];
  activeProfile: string;
  metrics: Record<string, MetricsSnapshot>;
  pendingActions: Record<string, PendingAction>;
  wsConnected: boolean;
  loading: boolean;
  switchProfile: (name: string, confirm: boolean) => Promise<SwitchResult>;
  startService: (name: string) => Promise<ActionResult>;
  stopService: (name: string) => Promise<ActionResult>;
  setStackTier: (stack: string, tier: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const DashboardCtx = createContext<DashboardState | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [services, setServices] = useState<Service[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [stacks, setStacks] = useState<Stack[]>([]);
  const [activeProfile, setActiveProfile] = useState('none');
  const [metrics, setMetrics] = useState<Record<string, MetricsSnapshot>>({});
  const [loading, setLoading] = useState(true);

  const { connected: wsConnected, lastMessage } = useWebSocket();
  const actionTimestamps = useRef<Record<string, number>>({});
  const [pendingActions, setPendingActions] = useState<Record<string, PendingAction>>({});

  // Merge WebSocket metrics into state, but skip services with recent actions
  // Clear pending once WS confirms the expected status
  useEffect(() => {
    if (lastMessage?.services) {
      const now = Date.now();
      setMetrics((prev) => {
        const merged = { ...prev };
        for (const [name, snap] of Object.entries(lastMessage.services)) {
          const actionAt = actionTimestamps.current[name];
          if (actionAt && now - actionAt < ACTION_GRACE_MS) {
            // Check if WS now confirms the expected status — if so, clear the pending action
            const pending = actionTimestamps.current[name] ? true : false;
            const expectedStatus = pending ? (prev[name]?.status) : undefined;
            if (expectedStatus && snap.status === expectedStatus) {
              delete actionTimestamps.current[name];
              setPendingActions((p) => { const next = { ...p }; delete next[name]; return next; });
              merged[name] = snap;
            }
            continue;
          }
          // Grace expired — accept WS data and clear pending
          if (actionTimestamps.current[name]) {
            delete actionTimestamps.current[name];
            setPendingActions((p) => { const next = { ...p }; delete next[name]; return next; });
          }
          merged[name] = snap;
        }
        return merged;
      });
    }
  }, [lastMessage]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [svcData, profData, stackData, activeData] = await Promise.all([
        api.get<Service[]>('/api/services'),
        api.get<Profile[]>('/api/profiles'),
        api.get<Stack[]>('/api/stacks'),
        api.get<{ active_profile: string }>('/api/profiles/active'),
      ]);
      setServices(svcData);
      setProfiles(profData);
      setStacks(stackData);
      setActiveProfile(activeData.active_profile);
    } catch (e) {
      console.error('Failed to fetch dashboard data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const switchProfile = useCallback(async (name: string, confirm: boolean) => {
    const result = await api.post<SwitchResult>('/api/profiles/switch', {
      target_profile: name,
      confirm,
    });
    if (result.executed) {
      setActiveProfile(name);
      await fetchAll();
    }
    return result;
  }, [fetchAll]);

  const makeSnapshot = (name: string, status: string, prev?: MetricsSnapshot): MetricsSnapshot => ({
    service_name: name, cpu_percent: 0, memory_percent: 0, memory_usage_mb: 0, timestamp: Date.now() / 1000,
    ...prev,
    status,
  });

  const startService = useCallback(async (name: string) => {
    const result = await api.post<ActionResult>(`/api/actions/start/${name}`);
    if (result.success) {
      const now = Date.now();
      actionTimestamps.current[name] = now;
      setPendingActions((p) => ({ ...p, [name]: { action: 'start', timestamp: now } }));
      setMetrics((prev) => ({ ...prev, [name]: makeSnapshot(name, 'running', prev[name]) }));
    }
    return result;
  }, []);

  const stopService = useCallback(async (name: string) => {
    const result = await api.post<ActionResult>(`/api/actions/stop/${name}`);
    if (result.success) {
      const now = Date.now();
      actionTimestamps.current[name] = now;
      setPendingActions((p) => ({ ...p, [name]: { action: 'stop', timestamp: now } }));
      setMetrics((prev) => ({ ...prev, [name]: makeSnapshot(name, 'stopped', prev[name]) }));
    }
    return result;
  }, []);

  const setStackTier = useCallback(async (stack: string, tier: string) => {
    await api.post(`/api/stacks/${stack}/tier`, { tier });
    await fetchAll();
  }, [fetchAll]);

  return (
    <DashboardCtx.Provider
      value={{
        services,
        profiles,
        stacks,
        activeProfile,
        metrics,
        pendingActions,
        wsConnected,
        loading,
        switchProfile,
        startService,
        stopService,
        setStackTier,
        refresh: fetchAll,
      }}
    >
      {children}
    </DashboardCtx.Provider>
  );
}

export function useDashboard() {
  const ctx = useContext(DashboardCtx);
  if (!ctx) throw new Error('useDashboard must be used within DashboardProvider');
  return ctx;
}
