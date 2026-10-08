import type { ActionResult, AuditRow, ContainerDetails, Finding, InventorySummary, LiveSession, Me, PendingApproval, Service,
  InputReceipt, TranscriptMessage, Triage } from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (res.status === 401) {
    // Signed out or expired: sign in and come back to the same screen.
    const here = location.pathname + location.search + location.hash;
    location.assign(`/auth/login?next=${encodeURIComponent(here)}`);
    throw new ApiError(401, 'Signing in again…');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`);
  }
  return res.json();
}

const get = <T>(p: string) => request<T>(p);
const post = <T>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
const enc = encodeURIComponent;

export const api = {
  me: () => get<Me>('/api/me'),
  logout: async () => {
    const r = await post<{ end_session_url: string | null }>('/auth/logout');
    location.assign(r.end_session_url || '/auth/login?next=/m/');
  },
  triage: () => get<Triage>('/api/triage'),
  services: () => get<Service[]>('/api/services'),
  details: (name: string) => get<ContainerDetails>(`/api/services/${enc(name)}/details`),
  start: (name: string) => post<ActionResult>(`/api/actions/start/${enc(name)}`),
  stop: (name: string) => post<ActionResult>(`/api/actions/stop/${enc(name)}`),
  approvals: () => get<PendingApproval[]>('/api/approvals/pending'),
  decide: (id: number, decision: 'approve' | 'deny') => post<{ ok: boolean }>(`/api/approvals/${id}/decide`, { decision }),
  sessions: () => get<LiveSession[]>('/api/sessions/active'),
  transcript: (uuid: string, afterId = 0) => get<TranscriptMessage[]>(`/api/sessions/${enc(uuid)}/transcript?after_id=${afterId}`),
  reply: (uuid: string, id: string, text: string) => post<{ id: string; status: string }>(`/api/sessions/${enc(uuid)}/input`, { id, text }),
  inputStatus: (uuid: string) => get<InputReceipt[]>(`/api/sessions/${enc(uuid)}/input`),
  audit: (limit = 200) => get<AuditRow[]>(`/api/audit?limit=${limit}`),
  summary: () => get<InventorySummary>('/api/inventory/summary'),
  findings: () => get<Finding[]>('/api/inventory/findings'),
  inventory: <T = unknown>(view: string) => get<T>(`/api/inventory/${enc(view)}`),
  tables: (database?: string) => get<Record<string, unknown>[]>(
    `/api/inventory/tables?limit=2000${database ? `&database=${enc(database)}` : ''}`),
  pipelines: (own = true) => get<Record<string, unknown>[]>(`/api/inventory/pipelines?own=${own}`),
};
