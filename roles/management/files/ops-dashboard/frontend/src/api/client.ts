import type { TimeseriesResponse, ContainerDetails } from '../types';
import type { LiveSession, TranscriptMessage } from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (res.status === 401) {
    // Session missing or expired: sign in again and come back to this page.
    const here = window.location.pathname + window.location.search;
    window.location.assign(`/auth/login?next=${encodeURIComponent(here)}`);
    throw new Error('Signing in again…');
  }
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
};

export const fetchTimeseries = (
  name: string,
  metric: 'cpu' | 'mem' = 'cpu',
  minutes = 15,
) => api.get<TimeseriesResponse>(
  `/api/metrics/${encodeURIComponent(name)}/timeseries?metric=${metric}&minutes=${minutes}`,
);

export const fetchDetails = (name: string) =>
  api.get<ContainerDetails>(`/api/services/${encodeURIComponent(name)}/details`);

export const fetchActiveSessions = () => api.get<LiveSession[]>('/api/sessions/active');

export const fetchTranscript = (uuid: string, since = 0) =>
  api.get<TranscriptMessage[]>(`/api/sessions/${encodeURIComponent(uuid)}/transcript?since=${since}`);

// Approvals
export const fetchPendingApprovals = () =>
  api.get<import('../types').PendingApproval[]>('/api/approvals/pending');

export const decideApproval = (id: number, decision: 'approve' | 'deny') =>
  api.post<{ ok: boolean; id: number; status: string }>(
    `/api/approvals/${id}/decide`,
    { decision },
  );

// Repo Radar
export const fetchRadarState = () => api.get<import('../types').RadarState>('/api/repo-radar/state');
export const rescanRadarVps = () => api.post<{ ok: boolean; host: string }>('/api/repo-radar/rescan');

// Session search (semantic + graph, same backends as timeline.aicortex.cloud)
export const timelineHealth = () => api.get<import('../types').TimelineHealth>('/api/timeline/health');
export const searchSessions = (q: string, k = 15) =>
  api.get<import('../types').SearchResponse>(`/api/timeline/search?q=${encodeURIComponent(q)}&k=${k}`);
export const similarSessions = (uuid: string, k = 6) =>
  api.get<{ session_uuid: string; hits: import('../types').SearchHit[]; reason?: string }>(
    `/api/timeline/similar/${encodeURIComponent(uuid)}?k=${k}`);
export const sessionGraph = (uuid: string) =>
  api.get<import('../types').SessionGraph>(`/api/timeline/session/${encodeURIComponent(uuid)}/graph`);
export const sessionTranscriptExcerpt = (uuid: string, maxChars = 8000) =>
  api.get<import('../types').SessionTranscript>(`/api/timeline/session/${encodeURIComponent(uuid)}/transcript?max_chars=${maxChars}`);
export const fileSessions = (path: string, k = 25) =>
  api.get<{ path: string; sessions: { session_uuid: string; title: string; date: string | null; project: string | null; touches: number }[] }>(
    `/api/timeline/file?path=${encodeURIComponent(path)}&k=${k}`);

// Signed-in user
export interface Me { username: string; email: string | null; role: 'viewer' | 'operator' | 'admin'; via: string }
export const fetchMe = () => api.get<Me>('/api/me');
export const logout = async () => {
  const r = await api.post<{ ok: boolean; end_session_url: string | null }>('/auth/logout');
  window.location.assign(r.end_session_url || '/auth/login');
};
