// Response shapes of the dashboard API (ops_dashboard/api/routers/*).

export type Role = 'viewer' | 'operator' | 'admin';
export interface Me { username: string; email: string | null; role: Role; via: string; iat: number }

export interface Alert {
  name: string; state: 'firing' | 'pending' | string; severity: string; since: string | null;
  summary: string | null; description: string | null; target: string | null;
}
export interface Triage {
  alerts: Alert[]; alerts_error: string | null;
  host: { load1: number | null; cpus: number | null; mem_used: number | null; swap_used: number | null; disk_used: number | null };
  backup_age_s: number | null; failing_jobs: string[];
}

export interface Service {
  name: string; platform: string; pod: string | null; description: string; status: string; managed: boolean;
  memory_mb: number | null; cpu_percent: number | null; memory_percent: number | null; dependencies: string[];
}
export interface ActionResult { service: string; action: string; success: boolean; message: string }

export interface PendingApproval {
  id: number; prompt_text: string; metadata: Record<string, unknown> | null; created_at: string; expires_at: string;
}
export interface LiveSession {
  session_uuid: string; live_status: string; needs_input: boolean; current_stage: string | null;
  host: string | null; git_branch: string | null; model: string | null; project: string | null;
  last_event_at: string | null; input_tokens: number | null; output_tokens: number | null;
  needs_approval?: boolean; approval_id?: number | null; approval_tool?: string | null; approval_prompt?: string | null;
}
export interface TranscriptMessage {
  uuid: string; role: string; type: string; content_text: string | null; sequence_num: number; timestamp: string | null;
}

export interface Finding { severity: 'bad' | 'warn' | 'info'; kind: string; title: string; detail: string }
export interface InventorySummary { [k: string]: number | string | string[] | null }

export interface AuditRow {
  id: number; ts: string; username: string | null; role: string | null; action: string; target: string | null;
  via: string | null; outcome: string; method: string | null; route: string | null; status: number | null;
  client_ip: string | null; detail: Record<string, unknown> | string | null;
}

export interface ContainerDetails {
  name: string; image: string; command: string[] | null; created: string; started_at: string; status: string;
  exit_code: number | null; restart_policy: string; restart_count: number; ip_address: string;
  mounts: { source: string; destination: string; mode: string }[] | null;
  env: [string, string][] | null; labels: Record<string, string>; pod: string | null;
}
