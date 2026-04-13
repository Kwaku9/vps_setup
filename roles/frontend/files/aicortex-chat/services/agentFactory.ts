/**
 * Agent Factory — shared service for creating agents on the Open WebUI server.
 *
 * Both the Concierge onboarding and the Chat History Pipeline feed into this
 * service. It converts AgentRecommendation[] → ModelForm[] → server models.
 */

import type {
  Agent,
  AgentContext,
  AgentRecommendation,
  ModelForm,
} from '@/constants/types';
import { AGENT_CATALOG, DOMAIN_MODEL_MAP } from '@/constants/agentCatalog';
import {
  listAgentModels,
  createAgentModel,
} from '@/services/api';
import { agentFromServerModel } from '@/services/agentMapper';

// ── Helpers ────────────────────────────────────────────────────

/** Generate a URL-safe slug from an agent name + random suffix for uniqueness. */
function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  const suffix = Math.random().toString(36).slice(2, 5);
  return `${base}-${suffix}`;
}

/** Replace {{variable}} placeholders in a template string. */
function fillTemplate(
  template: string,
  context?: AgentContext,
): string {
  if (!context) return template.replace(/\{\{user_preferences\}\}/g, '');

  // Build user preferences section from context
  const prefParts: string[] = [];
  if (context.tone) {
    const toneMap: Record<string, string> = {
      direct: 'Use a direct, professional tone. Be concise and straightforward.',
      balanced: 'Use a balanced, friendly-professional tone. Be approachable but focused.',
      casual: 'Use a casual, conversational tone. Contractions are fine. Light humor welcome.',
    };
    prefParts.push(toneMap[context.tone] ?? '');
  }
  if (context.detailLevel) {
    const detailMap: Record<string, string> = {
      concise: 'Keep responses brief. Lead with the answer. Maximum 2-3 short paragraphs.',
      brief: 'Provide brief explanations. Use bullet points for clarity. 3-5 paragraphs max.',
      detailed: 'Provide thorough, in-depth responses with reasoning, examples, and context.',
    };
    prefParts.push(detailMap[context.detailLevel] ?? '');
  }
  if (context.aiComfort) {
    const comfortMap: Record<string, string> = {
      beginner: 'Explain concepts in simple, non-jargon terms. Use analogies and step-by-step guidance.',
      some_experience: 'Use standard terminology. Provide context for advanced topics.',
      power_user: 'Use advanced terminology freely. Skip basics. Focus on nuance and edge cases.',
    };
    prefParts.push(comfortMap[context.aiComfort] ?? '');
  }
  if (context.userName) {
    prefParts.push(`Address the user as ${context.userName}.`);
  }

  const userPreferences = prefParts.filter(Boolean).join('\n');

  let result = template.replace(
    /\{\{user_preferences\}\}/g,
    userPreferences ? `\nUSER PREFERENCES:\n${userPreferences}` : '',
  );

  // Replace any remaining simple variables
  if (context.userName) {
    result = result.replace(/\{\{user_name\}\}/g, context.userName);
  }
  if (context.userRole) {
    result = result.replace(/\{\{user_role\}\}/g, context.userRole);
  }
  if (context.projectName) {
    result = result.replace(/\{\{project_name\}\}/g, context.projectName);
  }

  return result;
}

// ── Public API ─────────────────────────────────────────────────

/**
 * Build a rich system prompt for an agent type, personalized with context.
 */
export function buildRichSystemPrompt(
  agentType: string,
  context?: AgentContext,
): string {
  const template = AGENT_CATALOG[agentType];
  if (!template) {
    return `You are a helpful AI assistant.${context?.userName ? ` Address the user as ${context.userName}.` : ''}`;
  }
  return fillTemplate(template.systemPromptTemplate, context);
}

/**
 * Build a ModelForm for a given agent type, ready for POST to server.
 */
export function buildModelForm(
  agentType: string,
  context?: AgentContext,
): ModelForm {
  const template = AGENT_CATALOG[agentType];

  if (!template) {
    // Fallback for unknown agent types — create a generic agent
    return {
      id: slugify(agentType),
      base_model_id: DOMAIN_MODEL_MAP.general,
      name: agentType
        .replace(/_agent$/, '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase()),
      meta: {
        description: 'AI assistant',
        tags: [{ name: 'general' }],
      },
      params: {
        system: buildRichSystemPrompt(agentType, context),
      },
      is_active: true,
    };
  }

  return {
    id: slugify(template.name),
    base_model_id: template.base_model_id,
    name: template.name,
    meta: { ...template.meta },
    params: {
      system: buildRichSystemPrompt(agentType, context),
    },
    is_active: true,
  };
}

/**
 * Check which agent types already exist on the server.
 * Returns the agent_type strings that already have a matching model.
 */
export async function checkExistingAgents(
  agentTypes: string[],
): Promise<string[]> {
  const { items } = await listAgentModels();
  const existingNames = new Set(
    items.map((m) => m.name.toLowerCase()),
  );

  return agentTypes.filter((type) => {
    const template = AGENT_CATALOG[type];
    if (!template) return false;
    return existingNames.has(template.name.toLowerCase());
  });
}

/**
 * Create agents from a list of recommendations.
 *
 * - Deduplicates against existing server agents
 * - Creates sequentially with progress callback
 * - Returns created agents and any failures
 */
export async function createAgentsFromRecommendations(
  recommendations: AgentRecommendation[],
  context?: AgentContext,
  onProgress?: (current: number, total: number, agentName: string) => void,
): Promise<{ created: Agent[]; failed: string[] }> {
  // Deduplicate: remove agent types that already exist on server
  const allTypes = recommendations.map((r) => r.agent_type);
  const existing = await checkExistingAgents(allTypes);
  const existingSet = new Set(existing);
  const toCreate = recommendations.filter(
    (r) => !existingSet.has(r.agent_type),
  );

  const created: Agent[] = [];
  const failed: string[] = [];
  const total = toCreate.length;

  for (let i = 0; i < toCreate.length; i++) {
    const rec = toCreate[i];
    const form = buildModelForm(rec.agent_type, context);

    onProgress?.(i + 1, total, form.name);

    try {
      const serverModel = await createAgentModel(form);
      created.push(agentFromServerModel(serverModel));
    } catch (err) {
      console.warn(
        `Failed to create agent ${rec.agent_type}:`,
        err instanceof Error ? err.message : err,
      );
      failed.push(rec.agent_type);
    }
  }

  return { created, failed };
}
