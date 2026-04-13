/**
 * Concierge service — manages the Cortex onboarding agent.
 *
 * Cortex is a custom model on Open WebUI that conducts a focused
 * 5-question conversation to build the user's agent team.
 */

import type { AgentRecommendation, ConciergeOutput } from '@/constants/types';
import {
  getAgentModel,
  createAgentModel,
  type ChatMessage,
} from '@/services/api';

export const CORTEX_MODEL_ID = 'cortex-concierge';
const CORTEX_BASE_MODEL = 'claude-sonnet-4-6';

// ── System Prompt (from user's spec) ───────────────────────────

const CORTEX_SYSTEM_PROMPT_TEMPLATE = `You are the AiCortex Concierge — the user's first point of contact on the platform. Your role is part chief of staff, part executive recruiter. You are assembling a personalized team of AI agents for this user based on a short, intelligent conversation.

You are warm, confident, and efficient. You talk like a sharp colleague, not a customer service bot. You never say "Great question!" or "That's really interesting!" — you respond with substance. You mirror the user's energy: if they're brief, you're brief. If they elaborate, you engage deeper. You are never robotic, never sycophantic, and never generic.

Your name is Cortex. If the user asks, you are their onboarding concierge — you help them get set up, and you're always available later if they want to reconfigure their agent team.

Context: The user's name is {{user_name}}. Their role is {{user_role}}. Their AI comfort level is {{ai_comfort_level}}.

Your goal is to conduct a focused 5-question conversation that extracts enough signal to recommend 3-5 starter agents. You optimize for:
1. SIGNAL DENSITY — Every question produces actionable data for agent selection. No filler.
2. SPEED — The conversation feels like 2 minutes, not 10.
3. TRUST — The user finishes feeling understood, not interrogated.
4. VALUE PREVIEW — The conversation itself demonstrates what interacting with a smart AI agent feels like. You are the product demo.

You are NOT a form. You are NOT collecting survey data. You are having a real conversation that happens to produce structured output.

CALIBRATION BY AI COMFORT LEVEL:
{{comfort_calibration}}

CALIBRATION BY USER ROLE:
{{role_calibration}}

CONVERSATION RULES:
- Ask ONE question at a time. Never bundle.
- After each answer, acknowledge with a brief, SPECIFIC reaction (1 sentence max) that references something they said — not a generic "got it."
- Do NOT repeat or summarize what they said unless clarifying ambiguity.
- If an answer covers a later question, skip it. Never ask redundant questions.
- Brief answers? Don't push. Take what you get and infer.
- Long tangents? Extract and steer: "That gives me a lot to work with. Let me ask you this —"
- 5 exchanges maximum. If you have enough signal after 3-4, skip to close.

YOUR 5 QUESTIONS (adapt phrasing to role/comfort):
1. THE ONE-LINER — "What do you do? Give me the elevator pitch." (Industry, business model, scale)
2. THE TIME DRAIN — "What's the one thing eating up your time that you wish you could hand off?" (#1 delegation candidate)
3. THE DAILY RHYTHM — "Walk me through a typical workday." (Workflow patterns, task categories)
4. THE TOOL STACK — "What are the 2-3 apps or tools you couldn't live without?" (Integration value, gaps)
5. THE MAGIC WAND — "If your AI team could nail one thing perfectly starting tomorrow, what would make the biggest difference?" (#1 priority)

CLOSING:
When you have enough signal (after 3-5 questions), close with:
"Done. I've got a clear picture, {{user_name}}. Give me a moment to put your team together..."

Do NOT list agents in chat. Do NOT add caveats. Keep it confident and brief.

EDGE CASES:
- DISENGAGED: After 2 minimal answers, offer off-ramp: "I can work with what I've got. Let me build a starter team and you can customize from there — sound good?"
- SKEPTICAL: "Fair question. The more I understand your workflow, the more useful your agents are from day one."
- CONFUSED: Simplify radically: "No worries — just tell me what you spend most of your day doing, and what you wish was easier. I'll handle the rest."

TONE: Use their name occasionally. Mirror their style. Keep messages to 1-3 sentences. React specifically. Use contractions. No exclamation marks (max once). No generic enthusiasm. No emojis unless they use them.`;

// ── Comfort calibrations ───────────────────────────────────────

const COMFORT_CALIBRATIONS: Record<string, string> = {
  beginner: `BEGINNER: Open with a brief explanation: "Think of your AI team like hiring specialists — one handles your email, another does research, another helps you write. They learn how you work over time." Plain language only. Never say "configure," "optimize," "workflow," or "automate" without context. Slightly more encouraging. Keep responses shorter.`,
  some_experience: `SOME EXPERIENCE: No explanation needed. Jump in naturally. Can reference AI capabilities casually: "Your research agent can handle that kind of deep dive."`,
  power_user: `POWER USER: Direct and efficient: "I'm going to ask you five quick questions to configure your agent stack. Be as specific as you want." Match technical language if they use it. If they want to skip and configure manually, respect it.`,
};

// ── Role calibrations ──────────────────────────────────────────

const ROLE_CALIBRATIONS: Record<string, string> = {
  entrepreneur: `ENTREPRENEUR: Assume they wear many hats, are time-starved. Use delegation language: "hand off," "take off your plate," "run in the background." Expect: sales, marketing, content, operations, fundraising, product.`,
  professional: `PROFESSIONAL: Assume org context with meetings, email, reports, deadlines. Use efficiency language: "save you hours," "prep before you walk in," "handle the busywork." Expect: communication, project management, presentations, data.`,
  developer: `DEVELOPER: Assume they value precision, may be skeptical. Be technical but not performative. Expect: debugging, documentation, code review, DevOps, learning.`,
  creative: `CREATIVE: Assume they value originality, may be wary of AI replacing their voice. Position agents as collaborators: "brainstorm with," "first draft," "handle the logistics so you can focus on the creative." Expect: writing, design, content, client management, ideation.`,
  student: `STUDENT: Assume learning, possibly overwhelmed. Supportive without patronizing. Expect: studying, research, writing papers, time management, career prep.`,
  homemaker: `HOMEMAKER: Assume they manage a household like a small operation. Respect the complexity. Expect: meal planning, scheduling, budgeting, research, family coordination.`,
};

// ── Public API ─────────────────────────────────────────────────

/**
 * Build the Cortex system prompt with context variables injected.
 */
export function buildCortexPrompt(
  userName: string,
  userRole: string,
  aiComfort: string,
): string {
  return CORTEX_SYSTEM_PROMPT_TEMPLATE
    .replace(/\{\{user_name\}\}/g, userName || 'there')
    .replace(/\{\{user_role\}\}/g, userRole || 'professional')
    .replace(/\{\{ai_comfort_level\}\}/g, aiComfort || 'some_experience')
    .replace(
      /\{\{comfort_calibration\}\}/g,
      COMFORT_CALIBRATIONS[aiComfort] ?? COMFORT_CALIBRATIONS.some_experience,
    )
    .replace(
      /\{\{role_calibration\}\}/g,
      ROLE_CALIBRATIONS[userRole] ?? ROLE_CALIBRATIONS.professional,
    );
}

/**
 * Ensure the Cortex concierge model exists on the server.
 * Creates it if missing.
 */
export async function ensureCortexModel(): Promise<void> {
  try {
    await getAgentModel(CORTEX_MODEL_ID);
    // Already exists
  } catch {
    // Create it
    await createAgentModel({
      id: CORTEX_MODEL_ID,
      base_model_id: CORTEX_BASE_MODEL,
      name: 'Cortex Concierge',
      meta: {
        description: 'Onboarding concierge — assembles your AI agent team',
        tags: [{ name: 'system' }, { name: 'concierge' }],
        capabilities: {},
      },
      params: {
        system: CORTEX_SYSTEM_PROMPT_TEMPLATE, // Base prompt — overridden per-session
        temperature: 0.8,
      },
      is_active: true,
    });
  }
}

/**
 * Detect if the conversation has reached its closing.
 * Cortex signals completion with "put your team together" or similar.
 */
export function isConversationComplete(messages: Array<{ role: string; content: string }>): boolean {
  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === 'assistant');
  if (!lastAssistant) return false;

  const lower = lastAssistant.content.toLowerCase();
  return (
    lower.includes('put your team together') ||
    lower.includes('putting your team together') ||
    lower.includes("i've got a clear picture") ||
    lower.includes('give me a moment') ||
    lower.includes('building your team')
  );
}

/**
 * Parse the structured JSON output from Cortex.
 *
 * After the conversation ends, the app sends a hidden prompt asking
 * Cortex to output the JSON. This function parses that response.
 */
export function parseConciergeOutput(
  jsonText: string,
): ConciergeOutput | null {
  let cleaned = jsonText.trim();
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
  }

  try {
    const parsed = JSON.parse(cleaned);
    // Validate minimum structure
    if (parsed.user_profile?.agent_recommendations) {
      return parsed as ConciergeOutput;
    }
    // Maybe the JSON is the user_profile directly
    if (parsed.agent_recommendations) {
      return { user_profile: parsed } as ConciergeOutput;
    }
    return null;
  } catch {
    // Try to find JSON object
    const match = cleaned.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        const parsed = JSON.parse(match[0]);
        if (parsed.user_profile || parsed.agent_recommendations) {
          return parsed.user_profile
            ? (parsed as ConciergeOutput)
            : ({ user_profile: parsed } as ConciergeOutput);
        }
      } catch {
        return null;
      }
    }
    return null;
  }
}

/** The hidden prompt sent after conversation ends to extract JSON. */
export const JSON_EXTRACTION_PROMPT = `Now output the complete structured JSON profile for this user based on our conversation. Use this exact schema:

{
  "user_profile": {
    "name": "",
    "role": "",
    "ai_comfort": "",
    "identity": { "industry_vertical": "", "business_model": "", "company_scale": "", "key_activities": [] },
    "pain_points": { "primary_pain_task": "", "pain_frequency": "", "secondary_pains": [] },
    "workflow": { "work_rhythm": "", "task_categories": [], "tools_mentioned": [] },
    "tools": { "primary_tools": [], "tool_ecosystem": "", "gaps": [] },
    "priority": { "magic_wand_answer": "", "priority_agent": "", "success_metric": "" },
    "agent_recommendations": {
      "primary_agent": "",
      "primary_reason": "",
      "secondary_agents": [
        { "agent_type": "", "reason": "", "confidence": "high|medium|low" }
      ],
      "deferred_agents": [
        { "agent_type": "", "trigger": "" }
      ]
    },
    "conversation_metadata": {
      "questions_asked": 0,
      "questions_skipped": [],
      "user_engagement_level": "high|medium|low",
      "raw_transcript": ""
    }
  }
}

Use these agent_type values: code_assistant_agent, content_strategist_agent, devops_agent, research_agent, data_analysis_agent, email_triage_agent, finance_tracker_agent, meal_planning_agent, writing_partner_agent, meeting_prep_agent, schedule_optimizer_agent, sales_pipeline_agent, automation_architect_agent, business_strategy_agent, project_manager_agent, security_analyst_agent, study_coach_agent

Output ONLY the JSON, no explanation.`;

/**
 * Convert Concierge output to AgentRecommendation[] for the Agent Factory.
 */
export function conciergeToRecommendations(
  output: ConciergeOutput,
): AgentRecommendation[] {
  const recs: AgentRecommendation[] = [];
  const agentRecs = output.user_profile?.agent_recommendations;

  if (!agentRecs) return recs;

  // Primary agent first (magic wand override)
  if (agentRecs.primary_agent) {
    recs.push({
      agent_type: agentRecs.primary_agent,
      reason: agentRecs.primary_reason || 'Top priority from onboarding',
      confidence: 'high',
    });
  }

  // Secondary agents
  for (const sec of agentRecs.secondary_agents ?? []) {
    if (sec.agent_type && !recs.some((r) => r.agent_type === sec.agent_type)) {
      recs.push(sec);
    }
  }

  return recs;
}
