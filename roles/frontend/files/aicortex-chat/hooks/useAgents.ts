/**
 * Server-driven agent state hook.
 *
 * Fetches custom models from Open WebUI and caches in AsyncStorage.
 * On mount: load cache → emit → fetch server → overwrite → emit → persist cache.
 * If server unreachable: keep cache, mark all agents offline.
 */

import { useCallback, useEffect, useSyncExternalStore } from 'react';
import type { Agent, AgentModel, ModelForm } from '@/constants/types';
import { getItem, setItem, STORAGE_KEYS } from '@/services/storage';
import {
  listAgentModels,
  getModels,
  getToken,
  createAgentModel as apiCreateAgent,
  updateAgentModel as apiUpdateAgent,
  deleteAgentModel as apiDeleteAgent,
  ApiError,
} from '@/services/api';
import { agentFromServerModel, agentToModelForm } from '@/services/agentMapper';

// ── Module-level state (singleton store) ───────────────────────

let agents: Agent[] = [];
let isLoaded = false;
let isRefreshing = false;
let connectivity: 'online' | 'offline' | 'unknown' = 'unknown';
let lastError: string | null = null;
let listeners = new Set<() => void>();

interface Snapshot {
  agents: Agent[];
  isLoaded: boolean;
  isRefreshing: boolean;
  connectivity: 'online' | 'offline' | 'unknown';
  error: string | null;
}

// Cached snapshot — only recreated on emit() so useSyncExternalStore
// sees a stable reference and doesn't infinite-loop.
let cachedSnapshot: Snapshot = { agents, isLoaded, isRefreshing, connectivity, error: lastError };

function getSnapshot(): Snapshot {
  return cachedSnapshot;
}

function emit() {
  cachedSnapshot = { agents, isLoaded, isRefreshing, connectivity, error: lastError };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ── Cache operations ───────────────────────────────────────────

async function loadCache(): Promise<Agent[]> {
  const cached = await getItem<Agent[]>(STORAGE_KEYS.agents_cache);
  return cached ?? [];
}

async function persistCache(data: Agent[]): Promise<void> {
  await setItem(STORAGE_KEYS.agents_cache, data);
}

// ── Server fetch ───────────────────────────────────────────────

let fetchInFlight = false;

async function fetchFromServer(): Promise<void> {
  if (fetchInFlight) return;
  if (!getToken()) return;

  fetchInFlight = true;
  isRefreshing = true;
  lastError = null;
  emit();

  try {
    const [agentModels, baseModels] = await Promise.all([
      listAgentModels(),
      getModels(),
    ]);

    agents = agentModels.items.map((m) =>
      agentFromServerModel(m, baseModels),
    );
    connectivity = 'online';
    isLoaded = true;
    emit();

    await persistCache(agents);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 0 || err.message === 'Network error')) {
      connectivity = 'offline';
      // Mark all cached agents as offline
      agents = agents.map((a) => ({ ...a, status: 'offline' as const }));
    } else if (err instanceof ApiError && err.status === 401) {
      lastError = 'Authentication failed';
      connectivity = 'unknown';
    } else {
      lastError = err instanceof Error ? err.message : 'Unknown error';
    }
    emit();
  } finally {
    isRefreshing = false;
    fetchInFlight = false;
    emit();
  }
}

// ── Initial load ───────────────────────────────────────────────

let initStarted = false;

async function init() {
  if (initStarted) return;
  initStarted = true;

  // 1. Load cache for instant UI
  const cached = await loadCache();
  if (cached.length > 0) {
    agents = cached;
    isLoaded = true;
    emit();
  }

  // 2. Fetch from server (overwrites cache)
  await fetchFromServer();

  if (!isLoaded) {
    isLoaded = true;
    emit();
  }
}

if (typeof window !== 'undefined') {
  init();
}

// ── Hook ───────────────────────────────────────────────────────

export function useAgents() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const hasToken = !!getToken();

  useEffect(() => {
    init();
  }, []);

  // Re-fetch when auth token becomes available (e.g. restored from AsyncStorage)
  // or when the hook is first used with a token present
  useEffect(() => {
    if (hasToken && !snap.isRefreshing) {
      fetchFromServer();
    }
  }, [hasToken]);

  const refresh = useCallback(async () => {
    await fetchFromServer();
  }, []);

  const getAgent = useCallback(
    (id: string) => agents.find((a) => a.id === id),
    [snap.agents],
  );

  const createAgent = useCallback(
    async (form: ModelForm): Promise<Agent> => {
      const created = await apiCreateAgent(form);
      // Re-fetch to get fresh list with base model names resolved
      await fetchFromServer();
      return agents.find((a) => a.id === created.id) ?? agentFromServerModel(created);
    },
    [],
  );

  const updateAgent = useCallback(
    async (form: ModelForm): Promise<Agent> => {
      const updated = await apiUpdateAgent(form);
      await fetchFromServer();
      return agents.find((a) => a.id === updated.id) ?? agentFromServerModel(updated);
    },
    [],
  );

  const deleteAgent = useCallback(
    async (id: string): Promise<void> => {
      await apiDeleteAgent(id);
      await fetchFromServer();
    },
    [],
  );

  return {
    agents: snap.agents,
    isLoaded: snap.isLoaded,
    isRefreshing: snap.isRefreshing,
    connectivity: snap.connectivity,
    error: snap.error,
    refresh,
    getAgent,
    createAgent,
    updateAgent,
    deleteAgent,
  };
}
