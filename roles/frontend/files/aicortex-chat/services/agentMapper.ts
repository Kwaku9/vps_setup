/**
 * Converts between Open WebUI server model shapes and the Agent UI type.
 */

import type { Agent, AgentModel, ModelForm, ModelParams } from '@/constants/types';
import type { Model } from '@/services/api';

// ── Gradient palette — deterministic from model ID hash ────────

const GRADIENT_PALETTE: [string, string][] = [
  ['#6C63FF', '#B794F4'],
  ['#00C853', '#00E676'],
  ['#FF6D00', '#FFA726'],
  ['#1565C0', '#42A5F5'],
  ['#E91E63', '#F48FB1'],
  ['#00BCD4', '#4DD0E1'],
  ['#9C27B0', '#CE93D8'],
  ['#4CAF50', '#81C784'],
  ['#FF5252', '#FF8A80'],
  ['#607D8B', '#90A4AE'],
  ['#FFD600', '#FFEE58'],
  ['#795548', '#A1887F'],
  ['#0084FF', '#00C6FF'],
  ['#4B0082', '#6C63FF'],
  ['#10A37F', '#1A7F64'],
];

function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/** Deterministic gradient from model ID. */
export function generateGradient(id: string): [string, string] {
  return GRADIENT_PALETTE[hashString(id) % GRADIENT_PALETTE.length];
}

/** Derive initials from a name (first letter of first two words). */
export function generateInitials(name: string): string {
  const words = name.trim().split(/\s+/);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

/** Look up a human-readable base model name from the models list. */
function resolveBaseModelName(
  baseModelId: string | null,
  baseModels?: Model[],
): string {
  if (!baseModelId) return 'Unknown';
  if (baseModels) {
    const match = baseModels.find((m) => m.id === baseModelId);
    if (match) return match.name;
  }
  // Fallback: clean up the ID into something readable
  const parts = baseModelId.split('/');
  const last = parts[parts.length - 1];
  return last
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Server → UI ────────────────────────────────────────────────

/** Convert an Open WebUI AgentModel to the UI Agent type. */
export function agentFromServerModel(
  model: AgentModel,
  baseModels?: Model[],
): Agent {
  const tags =
    model.meta?.tags?.map((t) => t.name).filter(Boolean) ?? [];

  return {
    id: model.id,
    name: model.name,
    baseModelId: model.base_model_id ?? '',
    baseModelName: resolveBaseModelName(model.base_model_id, baseModels),
    description: model.meta?.description ?? '',
    systemPrompt: model.params?.system ?? '',
    profileImageUrl: model.meta?.profile_image_url ?? undefined,
    params: model.params ?? {},
    capabilities: model.meta?.capabilities ?? {},
    tags,
    isActive: model.is_active,
    status: model.is_active ? 'online' : 'offline',
    gradientColors: generateGradient(model.id),
    initials: generateInitials(model.name),
  };
}

// ── UI → Server ────────────────────────────────────────────────

/** Convert UI Agent fields back to a ModelForm for create/update. */
export function agentToModelForm(
  agent: Partial<Agent> & { id: string; name: string; baseModelId: string },
  existingParams?: ModelParams,
): ModelForm {
  return {
    id: agent.id,
    base_model_id: agent.baseModelId,
    name: agent.name,
    meta: {
      description: agent.description ?? '',
      profile_image_url: agent.profileImageUrl,
      capabilities: agent.capabilities ?? {},
      tags: (agent.tags ?? []).map((t) => ({ name: t })),
    },
    params: {
      ...existingParams,
      system: agent.systemPrompt ?? existingParams?.system,
      ...(agent.params ?? {}),
    },
    is_active: agent.isActive ?? true,
  };
}
