/**
 * Phase 3: Agent mapping — scores and recommends agents for projects.
 *
 * Scoring formula from the pipeline spec:
 *   agent_score = (domain_match × 3) + (intent_match × 2) + (tool_match × 1.5)
 *                 + (delegation_potential × 2) + (frequency_bonus × 1)
 */

import type { Agent, AgentRecommendation, ProjectCluster } from '@/constants/types';
import { AGENT_CATALOG, SIGNAL_AGENT_MAP } from '@/constants/agentCatalog';

// ── Domain → agent type mapping ────────────────────────────────

const DOMAIN_AGENT_MAP: Record<string, string[]> = {
  coding: ['code_assistant_agent'],
  devops: ['devops_agent', 'code_assistant_agent'],
  marketing: ['content_strategist_agent', 'writing_partner_agent'],
  sales: ['sales_pipeline_agent'],
  finance: ['finance_tracker_agent'],
  writing: ['writing_partner_agent'],
  research: ['research_agent'],
  data_analysis: ['data_analysis_agent'],
  design: ['content_strategist_agent'],
  personal_productivity: ['schedule_optimizer_agent'],
  health_wellness: ['meal_planning_agent'],
  education: ['study_coach_agent', 'research_agent'],
  cooking: ['meal_planning_agent'],
  business_strategy: ['business_strategy_agent'],
  project_management: ['project_manager_agent'],
  creative: ['content_strategist_agent', 'writing_partner_agent'],
  customer_support: ['email_triage_agent'],
  hiring_hr: ['email_triage_agent', 'meeting_prep_agent'],
  legal: ['research_agent'],
  career: ['business_strategy_agent', 'writing_partner_agent'],
};

// ── Intent → agent type mapping ────────────────────────────────

const INTENT_AGENT_MAP: Record<string, string[]> = {
  build_something: ['code_assistant_agent', 'automation_architect_agent'],
  fix_something: ['code_assistant_agent', 'devops_agent'],
  learn_something: ['research_agent', 'study_coach_agent'],
  write_something: ['writing_partner_agent', 'content_strategist_agent'],
  analyze_something: ['data_analysis_agent', 'research_agent'],
  plan_something: ['project_manager_agent', 'schedule_optimizer_agent', 'meal_planning_agent'],
  decide_something: ['business_strategy_agent', 'research_agent'],
  automate_something: ['automation_architect_agent', 'devops_agent'],
  brainstorm: ['content_strategist_agent', 'writing_partner_agent'],
  get_advice: ['business_strategy_agent', 'research_agent'],
};

// ── Tool → agent type mapping ──────────────────────────────────

const TOOL_AGENT_MAP: Record<string, string[]> = {
  python: ['code_assistant_agent', 'data_analysis_agent'],
  javascript: ['code_assistant_agent'],
  typescript: ['code_assistant_agent'],
  react: ['code_assistant_agent'],
  react_native: ['code_assistant_agent'],
  docker: ['devops_agent'],
  podman: ['devops_agent'],
  kubernetes: ['devops_agent'],
  terraform: ['devops_agent'],
  ansible: ['devops_agent'],
  aws: ['devops_agent'],
  azure: ['devops_agent'],
  gcp: ['devops_agent'],
  linux: ['devops_agent'],
  traefik: ['devops_agent'],
  nginx: ['devops_agent'],
  linkedin: ['content_strategist_agent'],
  shopify: ['code_assistant_agent', 'automation_architect_agent'],
  google_sheets: ['data_analysis_agent', 'automation_architect_agent'],
  excel: ['data_analysis_agent'],
  figma: ['content_strategist_agent'],
  notion: ['project_manager_agent'],
  slack: ['automation_architect_agent'],
  pandas: ['data_analysis_agent', 'code_assistant_agent'],
  sql: ['data_analysis_agent'],
  jupyter: ['data_analysis_agent'],
};

// ── Scoring ────────────────────────────────────────────────────

/**
 * Score how well an agent type fits a project.
 */
export function scoreAgent(
  agentType: string,
  project: ProjectCluster,
): number {
  let score = 0;

  // Domain match (×3)
  const domainAgents = DOMAIN_AGENT_MAP[project.primary_domain] ?? [];
  if (domainAgents.includes(agentType)) {
    score += 3;
  } else {
    // Check secondary domains
    for (const domain of project.domains) {
      if ((DOMAIN_AGENT_MAP[domain] ?? []).includes(agentType)) {
        score += 1.5; // half credit for secondary domain
        break;
      }
    }
  }

  // Intent match (×2) — inferred from dominant conversation patterns
  // Use the project's agent_recommendations from clustering as intent signal
  const clusterRecs = project.agent_recommendations ?? [];
  if (clusterRecs.some((r) => r.agent_type === agentType)) {
    score += 2;
  }

  // Tool match (×1.5)
  for (const tool of project.tools_used) {
    const toolNorm = tool.toLowerCase().replace(/[\s-]/g, '_');
    if ((TOOL_AGENT_MAP[toolNorm] ?? []).includes(agentType)) {
      score += 1.5;
      break; // Count once per agent, not per tool
    }
  }

  // Delegation potential (×2)
  if (project.delegation_profile === 'automatable') {
    score += 2;
  } else if (project.delegation_profile === 'hybrid') {
    score += 1;
  }

  // Frequency bonus (×1)
  if (project.conversation_ids.length >= 5) {
    score += 1;
  }

  return score;
}

/**
 * Map projects to agent recommendations, cross-referencing existing agents.
 *
 * Returns deduplicated recommendations — agents that already exist on
 * the server are excluded.
 */
export function mapProjectsToAgents(
  projects: ProjectCluster[],
  existingAgents: Agent[],
): AgentRecommendation[] {
  const existingNames = new Set(
    existingAgents.map((a) => a.name.toLowerCase()),
  );

  // Collect all scored recommendations across projects
  const scores = new Map<string, { score: number; reasons: string[]; projects: string[] }>();

  for (const project of projects) {
    // First, include any recommendations the clustering LLM already made
    for (const rec of project.agent_recommendations ?? []) {
      const existing = scores.get(rec.agent_type);
      if (existing) {
        existing.score += rec.confidence === 'high' ? 3 : rec.confidence === 'medium' ? 2 : 1;
        existing.reasons.push(rec.reason);
        existing.projects.push(project.project_name);
      } else {
        scores.set(rec.agent_type, {
          score: rec.confidence === 'high' ? 3 : rec.confidence === 'medium' ? 2 : 1,
          reasons: [rec.reason],
          projects: [project.project_name],
        });
      }
    }

    // Then score ALL catalog agent types against this project
    for (const agentType of Object.keys(AGENT_CATALOG)) {
      const s = scoreAgent(agentType, project);
      if (s > 0) {
        const existing = scores.get(agentType);
        if (existing) {
          existing.score += s;
          existing.projects.push(project.project_name);
        } else {
          scores.set(agentType, {
            score: s,
            reasons: [`Matches ${project.project_name} (score: ${s.toFixed(1)})`],
            projects: [project.project_name],
          });
        }
      }
    }
  }

  // Sort by score, deduplicate against existing agents, take top results
  const sorted = Array.from(scores.entries())
    .sort(([, a], [, b]) => b.score - a.score)
    .filter(([agentType]) => {
      const template = AGENT_CATALOG[agentType];
      if (!template) return false;
      return !existingNames.has(template.name.toLowerCase());
    });

  // Take top agents (minimum 3, maximum based on score threshold)
  const MIN_AGENTS = 3;
  const SCORE_THRESHOLD = 2;
  const recommendations: AgentRecommendation[] = [];

  for (const [agentType, data] of sorted) {
    if (recommendations.length >= MIN_AGENTS && data.score < SCORE_THRESHOLD) {
      break;
    }
    if (recommendations.length >= 8) break; // Hard cap

    recommendations.push({
      agent_type: agentType,
      reason: data.reasons[0] ?? `Recommended for ${data.projects.join(', ')}`,
      confidence: data.score >= 5 ? 'high' : data.score >= 3 ? 'medium' : 'low',
      role_in_project: `Supports: ${[...new Set(data.projects)].slice(0, 3).join(', ')}`,
    });
  }

  return recommendations;
}
