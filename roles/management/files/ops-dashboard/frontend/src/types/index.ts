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
