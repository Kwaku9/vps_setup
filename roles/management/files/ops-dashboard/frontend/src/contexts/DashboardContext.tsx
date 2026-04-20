import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { useToast } from './ToastContext';
import type { ActionResult, MetricsSnapshot, Profile, Service, Stack, SwitchResult } from '../types';

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
  const [pendingActions, setPendingActions] = useState<Record<string, PendingAction>>({});
  const [loading, setLoading] = useState(true);

  const { connected: wsConnected, lastMessage } = useWebSocket();
  const { push: pushToast } = useToast();

  // WS frames apply unconditionally — server is the source of truth.
  useEffect(() => {
    if (lastMessage?.services) {
      setMetrics((prev) => ({ ...prev, ...lastMessage.services }));
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

  const runAction = useCallback(
    async (action: 'start' | 'stop', name: string): Promise<ActionResult> => {
      const now = Date.now();
      setPendingActions((p) => ({ ...p, [name]: { action, timestamp: now } }));
      try {
        const result = await api.post<ActionResult>(`/api/actions/${action}/${name}`);
        if (!result.success) {
          pushToast({
            title: `Failed to ${action} ${name}`,
            body: result.message,
            kind: 'error',
          });
        }
        return result;
      } catch (err) {
        pushToast({
          title: `Error calling ${action} on ${name}`,
          body: err instanceof Error ? err.message : String(err),
          kind: 'error',
        });
        throw err;
      } finally {
        setPendingActions((p) => { const next = { ...p }; delete next[name]; return next; });
      }
    },
    [pushToast],
  );

  const startService = useCallback((name: string) => runAction('start', name), [runAction]);
  const stopService  = useCallback((name: string) => runAction('stop',  name), [runAction]);

  const setStackTier = useCallback(async (stack: string, tier: string) => {
    await api.post(`/api/stacks/${stack}/tier`, { tier });
    await fetchAll();
  }, [fetchAll]);

  return (
    <DashboardCtx.Provider
      value={{
        services, profiles, stacks, activeProfile, metrics, pendingActions,
        wsConnected, loading,
        switchProfile, startService, stopService, setStackTier,
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
