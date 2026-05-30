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
