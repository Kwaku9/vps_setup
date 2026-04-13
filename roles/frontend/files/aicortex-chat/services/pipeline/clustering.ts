/**
 * Phase 2: Project clustering.
 *
 * Takes all conversation extractions and clusters them into projects
 * via a single LLM call using the Project Organizer prompt.
 */

import type {
  ConversationExtraction,
  ProjectCluster,
  AgentRecommendation,
} from '@/constants/types';
import { chatCompletion, type ChatMessage } from '@/services/api';

// Higher-quality model for clustering (single call, needs reasoning)
const CLUSTERING_MODEL = 'claude-sonnet-4';

const CLUSTERING_SYSTEM_PROMPT = `You are a project organizer for AiCortex. You have a list of conversation metadata extracted from a user's chat history. Your job is to cluster these conversations into distinct PROJECTS.

A project is an ongoing initiative, goal, or area of work that spans multiple conversations. Projects are not categories — they are specific efforts the user is engaged in.

Return a JSON object with this exact structure:

{
  "projects": [
    {
      "project_id": "string — unique ID (e.g. proj_001)",
      "project_name": "string — clear, specific, action-oriented name",
      "project_description": "string — 1-2 sentence description",
      "status": "active | dormant | archived",
      "conversation_ids": ["array of conversation IDs"],
      "domains": ["unique domains across conversations"],
      "primary_domain": "string — dominant domain",
      "tools_used": ["unique tools mentioned"],
      "skills_involved": ["unique skills across conversations"],
      "complexity_profile": "lightweight | moderate | intensive",
      "delegation_profile": "human_driven | hybrid | automatable",
      "agent_recommendations": [
        {
          "agent_type": "string — e.g. code_assistant_agent, devops_agent",
          "reason": "string — why this agent fits, referencing specific conversations",
          "confidence": "high | medium | low",
          "role_in_project": "string — specific actions the agent would take"
        }
      ],
      "recurring_patterns": "string — frequency, typical tasks, evolution",
      "key_entities": ["important entities across conversations"]
    }
  ],
  "standalone_conversations": [
    {
      "conversation_id": "string",
      "title": "string",
      "reason": "string — why it doesn't belong to any project"
    }
  ],
  "user_profile_synthesis": {
    "primary_roles": ["string array — inferred roles"],
    "top_skills": ["string array — ranked by frequency"],
    "work_style": "deep_focused | rapid_context_switching | exploratory | systematic",
    "tool_ecosystem": "google | microsoft | apple | mixed | developer_stack",
    "recurring_needs": ["things the user keeps coming back for"],
    "growth_areas": ["topics where user is learning vs expert"]
  }
}

CLUSTERING RULES:
1. MERGE conversations with similar project_signal values using semantic similarity.
2. DO NOT create projects with only 1 conversation unless it's high complexity and clearly ongoing.
3. A conversation can only belong to ONE project.
4. Project names must be specific and action-oriented. "Marketing" is bad. "LinkedIn AI Security Content Campaign" is good.
5. For agent_recommendations, think about what agents would make each project more efficient. The role_in_project should describe specific actions.
6. Look for CROSS-PROJECT patterns.
7. Group 3+ standalone conversations in the same domain into a "General [Domain]" project.
8. Status: active = conversations in last 30 days, dormant = 30-90 days, archived = 90+ days.

Use these agent_type values: code_assistant_agent, content_strategist_agent, devops_agent, research_agent, data_analysis_agent, email_triage_agent, finance_tracker_agent, meal_planning_agent, writing_partner_agent, meeting_prep_agent, schedule_optimizer_agent, sales_pipeline_agent, automation_architect_agent, business_strategy_agent, project_manager_agent, security_analyst_agent, study_coach_agent`;

export interface ClusteringResult {
  projects: ProjectCluster[];
  standalone: Array<{ conversation_id: string; title: string; reason: string }>;
  userProfile: {
    primary_roles: string[];
    top_skills: string[];
    work_style: string;
    tool_ecosystem: string;
    recurring_needs: string[];
    growth_areas: string[];
  };
}

/** Parse clustering JSON from LLM response. */
function parseClusteringResponse(text: string): ClusteringResult | null {
  let cleaned = text.trim();
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
  }

  try {
    const parsed = JSON.parse(cleaned);
    return {
      projects: parsed.projects ?? [],
      standalone: parsed.standalone_conversations ?? [],
      userProfile: parsed.user_profile_synthesis ?? {
        primary_roles: [],
        top_skills: [],
        work_style: 'systematic',
        tool_ecosystem: 'mixed',
        recurring_needs: [],
        growth_areas: [],
      },
    };
  } catch {
    // Try to find JSON object in the response
    const match = cleaned.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        const parsed = JSON.parse(match[0]);
        return {
          projects: parsed.projects ?? [],
          standalone: parsed.standalone_conversations ?? [],
          userProfile: parsed.user_profile_synthesis ?? {
            primary_roles: [],
            top_skills: [],
            work_style: 'systematic',
            tool_ecosystem: 'mixed',
            recurring_needs: [],
            growth_areas: [],
          },
        };
      } catch {
        return null;
      }
    }
    return null;
  }
}

/**
 * Cluster conversation extractions into projects.
 *
 * For large sets (100+), chunks into groups of 50 and merges results.
 */
export async function clusterIntoProjects(
  extractions: ConversationExtraction[],
): Promise<ClusteringResult> {
  if (extractions.length === 0) {
    return {
      projects: [],
      standalone: [],
      userProfile: {
        primary_roles: [],
        top_skills: [],
        work_style: 'systematic',
        tool_ecosystem: 'mixed',
        recurring_needs: [],
        growth_areas: [],
      },
    };
  }

  const CHUNK_SIZE = 50;

  if (extractions.length <= CHUNK_SIZE) {
    return clusterChunk(extractions);
  }

  // Chunk and merge for large sets
  const allProjects: ProjectCluster[] = [];
  const allStandalone: ClusteringResult['standalone'] = [];
  let mergedProfile: ClusteringResult['userProfile'] | null = null;

  for (let i = 0; i < extractions.length; i += CHUNK_SIZE) {
    const chunk = extractions.slice(i, i + CHUNK_SIZE);
    const result = await clusterChunk(chunk);

    allProjects.push(...result.projects);
    allStandalone.push(...result.standalone);

    if (!mergedProfile) {
      mergedProfile = result.userProfile;
    } else {
      // Merge profile arrays (deduplicate)
      mergedProfile.primary_roles = [...new Set([...mergedProfile.primary_roles, ...result.userProfile.primary_roles])];
      mergedProfile.top_skills = [...new Set([...mergedProfile.top_skills, ...result.userProfile.top_skills])];
      mergedProfile.recurring_needs = [...new Set([...mergedProfile.recurring_needs, ...result.userProfile.recurring_needs])];
      mergedProfile.growth_areas = [...new Set([...mergedProfile.growth_areas, ...result.userProfile.growth_areas])];
    }
  }

  // Merge projects with similar names across chunks
  const merged = mergeProjects(allProjects);

  return {
    projects: merged,
    standalone: allStandalone,
    userProfile: mergedProfile!,
  };
}

async function clusterChunk(
  extractions: ConversationExtraction[],
): Promise<ClusteringResult> {
  // Condense extractions to essential fields to fit context
  const condensed = extractions.map((e) => ({
    conversation_id: e.conversation_id,
    title: e.title,
    domain: e.domain,
    subdomain: e.subdomain,
    project_signal: e.project_signal,
    intent: e.intent,
    complexity: e.complexity,
    tools_mentioned: e.tools_mentioned,
    skills_demonstrated: e.skills_demonstrated,
    recurring_theme: e.recurring_theme,
    delegation_potential: e.delegation_potential,
    agent_signals: e.agent_signals,
    key_entities: e.key_entities,
  }));

  const messages: ChatMessage[] = [
    { role: 'system', content: CLUSTERING_SYSTEM_PROMPT },
    {
      role: 'user',
      content: `Cluster these ${condensed.length} conversations into projects:\n\n${JSON.stringify(condensed, null, 2)}`,
    },
  ];

  const response = await chatCompletion(CLUSTERING_MODEL, messages);
  const content = response.choices?.[0]?.message?.content ?? '';
  const result = parseClusteringResponse(content);

  if (!result) {
    console.warn('Failed to parse clustering response');
    return {
      projects: [],
      standalone: extractions.map((e) => ({
        conversation_id: e.conversation_id,
        title: e.title,
        reason: 'Clustering failed',
      })),
      userProfile: {
        primary_roles: [],
        top_skills: [],
        work_style: 'systematic',
        tool_ecosystem: 'mixed',
        recurring_needs: [],
        growth_areas: [],
      },
    };
  }

  return result;
}

/** Merge projects with similar names (from multi-chunk processing). */
function mergeProjects(projects: ProjectCluster[]): ProjectCluster[] {
  const merged = new Map<string, ProjectCluster>();

  for (const project of projects) {
    // Simple dedup: check for existing project with similar name
    const normalizedName = project.project_name.toLowerCase().replace(/[^a-z0-9]/g, '');
    let foundKey: string | null = null;

    for (const [key] of merged) {
      if (key === normalizedName) {
        foundKey = key;
        break;
      }
    }

    if (foundKey) {
      const existing = merged.get(foundKey)!;
      existing.conversation_ids = [
        ...new Set([...existing.conversation_ids, ...project.conversation_ids]),
      ];
      existing.domains = [...new Set([...existing.domains, ...project.domains])];
      existing.tools_used = [...new Set([...existing.tools_used, ...project.tools_used])];
      existing.skills_involved = [...new Set([...existing.skills_involved, ...project.skills_involved])];
    } else {
      merged.set(normalizedName, { ...project });
    }
  }

  return Array.from(merged.values());
}
