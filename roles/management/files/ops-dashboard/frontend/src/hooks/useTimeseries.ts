import { useEffect, useState } from 'react';
import { fetchTimeseries } from '../api/client';
import type { TimeseriesPoint } from '../types';

interface State {
  points: TimeseriesPoint[];
  loading: boolean;
  error: string | null;
}

const cache = new Map<string, { points: TimeseriesPoint[]; ts: number }>();
const TTL_MS = 30_000;

export function useTimeseries(
  name: string,
  metric: 'cpu' | 'mem',
  minutes = 15,
  enabled = true,
): State {
  const cacheKey = `${name}:${metric}:${minutes}`;
  const cached = cache.get(cacheKey);
  const [state, setState] = useState<State>({
    points: cached?.points ?? [],
    loading: !cached,
    error: null,
  });
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const load = async () => {
      const c = cache.get(cacheKey);
      if (c && Date.now() - c.ts < TTL_MS) {
        if (active) setState({ points: c.points, loading: false, error: null });
        return;
      }
      try {
        const res = await fetchTimeseries(name, metric, minutes);
        cache.set(cacheKey, { points: res.points, ts: Date.now() });
        if (active) setState({ points: res.points, loading: false, error: null });
      } catch (e: unknown) {
        if (active) {
          setState((s) => ({ ...s, loading: false, error: e instanceof Error ? e.message : 'load failed' }));
        }
      }
    };
    load();
    const t = setInterval(load, TTL_MS);
    return () => { active = false; clearInterval(t); };
  }, [cacheKey, enabled, metric, minutes, name]);

  return state;
}
