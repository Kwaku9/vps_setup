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

// Students and the request desk (admin only; routers/students.py, routers/access_requests.py)
export interface Person {
  pk: number; username: string; name: string; email: string;
  active: boolean; last_login: string | null; groups: string[];
}
export interface AccessRequest {
  id: number; created_at: string; email: string; username: string | null;
  kind: 'students' | 'paid_users' | 'other'; reason: string;
  status: 'pending' | 'approved' | 'denied' | 'withdrawn';
  decided_at: string | null; decided_by: string | null; note: string | null;
}
export const fetchStudents = () => api.get<{ students: Person[]; candidates: Person[] }>('/api/students');
export const addStudent = (pk: number) => api.post<{ ok: boolean }>(`/api/students/${pk}`);
export const removeStudent = (pk: number) => request<{ ok: boolean }>(`/api/students/${pk}`, { method: 'DELETE' });
export const fetchAccessRequests = () =>
  api.get<{ requests: AccessRequest[]; kinds: Record<string, string> }>('/api/access-requests');
export const decideAccessRequest = (id: number, decision: 'approve' | 'deny', note: string) =>
  api.post<{ ok: boolean; status: string; granted_group: string | null }>(
    `/api/access-requests/${id}/decide`, { decision, note });

// Student progress (admin only; routers/progress.py)
export interface StudentProgress {
  email: string; name: string; username: string; last_login: string | null; last_seen: string | null;
  days_active: number;
  by_resource: { resource: string; label: string; hits: number }[];
  items: { resource: string; resource_label: string; label: string; hits: number; last_seen: string }[];
  decks: { deck: string; slides_total: number; furthest: number; seen: number; percent: number;
           status: 'started' | 'finished'; first_seen: string; last_seen: string }[];
  openwebui: { chats_active: number; chats_started: number; models: { model: string; chats: number }[] };
  refused: { domain: string; count: number }[];
  daily: { day: string; hits: number }[];
  needs_attention: string[];
}
export const fetchStudentProgress = (days: number) =>
  api.get<{ days: number; students: StudentProgress[] }>(`/api/students/progress?days=${days}`);
