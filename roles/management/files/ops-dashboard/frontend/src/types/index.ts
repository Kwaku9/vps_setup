export interface Service {
  name: string;
  platform: 'vps' | 'azure' | 'host';
  endpoint_type: string;
  pod: string | null;
  description: string;
  status: string;
  managed: boolean;
  cpu_shares: number | null;
  memory_mb: number | null;
  cost_per_hour: number | null;
  ansible_tag: string | null;
  azure_endpoint: string | null;
  dependencies: string[];
  cpu_percent: number | null;
  memory_percent: number | null;
  stack_group: string | null;
}

export interface StackTier {
  name: string;
  description: string;
  services: string[];
}

export interface Stack {
  name: string;
  description: string;
  tiers: StackTier[];
  tier_names: string[];
  current_tier: string | null;
}

export interface Profile {
  name: string;
  description: string;
  services: Record<string, boolean>;
  stacks: Record<string, string>;
  estimated_cost_per_hour: number | null;
  enabled_count: number;
  disabled_count: number;
}

export interface ProfileDiff {
  starting: string[];
  stopping: string[];
  unchanged: string[];
}

export interface SwitchResult {
  diff: ProfileDiff;
  executed: boolean;
  message: string;
}

export interface MetricsSnapshot {
  service_name: string;
  timestamp: number;
  cpu_percent: number;
  memory_percent: number;
  memory_usage_mb: number;
  status: string;
}

export interface MetricsUpdate {
  type: 'metrics_update' | 'initial';
  timestamp?: number;
  services: Record<string, MetricsSnapshot>;
}

export interface ActionResult {
  service: string;
  action: string;
  success: boolean;
  message: string;
}

export type VibrationIntensity = 'calm' | 'moderate' | 'active' | 'stressed' | 'critical';

export interface VibrationParams {
  x: number[];
  y: number[];
  duration: number;
  intensity: VibrationIntensity;
}

export type TimeseriesPoint = [number, number]; // [unix_ts, value]

export interface TimeseriesResponse {
  service_name: string;
  metric: 'cpu' | 'mem';
  minutes: number;
  points: TimeseriesPoint[];
}

export interface ContainerDetails {
  name: string;
  image: string;
  command: string[];
  created: string;
  started_at: string;
  status: string;
  exit_code: number | null;
  restart_policy: string;
  restart_count: number;
  ip_address: string;
  ports: Record<string, unknown>;
  port_bindings: Record<string, unknown>;
  mounts: { source: string; destination: string; mode: string }[];
  env: [string, string][];
  labels: Record<string, string>;
  pod: string | null;
}

export interface LiveSession {
  session_uuid: string;
  live_status: 'running' | 'waiting_input' | 'idle' | 'ended';
  needs_input: boolean;
  current_stage: string | null;
  host: string | null;
  git_branch: string | null;
  model: string | null;
  project: string | null;
  last_event_at: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  needs_approval?: boolean;
  approval_id?: number | null;
  approval_tool?: string | null;
  approval_prompt?: string | null;
}

export interface PendingApproval {
  id: number;
  prompt_text: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  expires_at: string;
}

export interface TranscriptMessage {
  uuid: string;
  role: string;
  type: string;
  content_text: string | null;
  sequence_num: number;
  timestamp: string | null;
}

export interface SessionUpdate {
  type: 'session_update';
  session_uuid: string;
  live_status?: string;
  needs_input?: boolean;
  current_stage?: string | null;
}

// ── Repo Radar ─────────────────────────────────────────────────────────
export interface RadarBranch {
  name: string;
  upstream: string | null;
  gone: boolean;
  ahead: number;
  behind: number;
  when: number;
  subject: string;
  author: string;
}

export interface RadarRepo {
  name: string;
  error: string | null;
  head: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  staged: number;
  modified: number;
  untracked: number;
  conflicted: number;
  branches?: RadarBranch[];
  stashes?: number;
  slug?: string | null;
  detached?: boolean;
  unborn?: boolean;
  last?: { hash: string; rel: string; subject: string } | null;
  dirty: number;
}

export interface RadarPR {
  number: number;
  title: string;
  url: string;
  draft: boolean;
  updated: string;
  author: string;
}

export interface RadarSnapshot {
  host: string;
  root: string | null;
  scannedAt: string | null;
  scanMs: number | null;
  receivedAt?: string;
  repos: RadarRepo[];
  prs: Record<string, RadarPR[]>;
  prError: string | null;
  fatal?: string | null;
}

export interface RadarState {
  hosts: Record<string, RadarSnapshot>;
  now: string;
}

// ── Session search (timeline) ──────────────────────────────────────────
export interface SearchHit {
  session_uuid: string;
  title: string;
  project: string | null;
  date: string | null;
  snippet: string;
  score: number;
  source: string | null;
  messages: number | null;
  pillar_id: string | null;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
  timing_ms: { embed: number; search: number };
}

export interface SessionGraph {
  session_uuid: string;
  title: string;
  project: string | null;
  branch: string | null;
  source: string | null;
  started_at: string | null;
  messages: number | null;
  tool_calls: number | null;
  models: string[];
  commits: { sha: string; message: string; date: string | null; branch: string | null; files_changed: number | null }[];
  subagents: number;
  files: { path: string; touches: number }[];
  shared_file_sessions: { session_uuid: string; title: string; date: string | null; source: string | null; project: string | null; shared: number; sample: string[] }[];
  tools: { name: string; n: number }[];
}

export interface SessionTranscript {
  session_uuid: string;
  title: string;
  one_liner: string;
  paragraph: string;
  project: string | null;
  source: string | null;
  pillar_id: string | null;
  date: string | null;
  turns: { role: string; text: string; truncated?: boolean }[];
  chars: number;
}

export interface TimelineHealth {
  status: string;
  postgres: boolean;
  neo4j: boolean;
  embedder: boolean;
  recall_chunks?: number;
  sessions_in_graph?: number;
}
