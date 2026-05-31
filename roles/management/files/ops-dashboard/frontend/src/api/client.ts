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
