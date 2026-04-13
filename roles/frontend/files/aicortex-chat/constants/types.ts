export type ModelStatus = 'online' | 'busy' | 'offline';

// ── Open WebUI Server Types ──────────────────────────────────

export interface ModelMeta {
  profile_image_url?: string;
  description?: string;
  capabilities?: Record<string, boolean>;
  tags?: Array<{ name: string }>;
  suggestion_prompts?: Array<{ title: string; content: string }>;
  categories?: string[];
}

export interface ModelParams {
  system?: string;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  repeat_penalty?: number;
  num_predict?: number;
  seed?: number;
  stop?: string[];
}

export interface ModelForm {
  id: string;
  base_model_id: string;
  name: string;
  meta: ModelMeta;
  params: ModelParams;
  is_active?: boolean;
}

export interface AgentModel {
  id: string;
  user_id: string;
  base_model_id: string | null;
  name: string;
  params: ModelParams;
  meta: ModelMeta;
  is_active: boolean;
  updated_at: number;
  created_at: number;
}

// ── Folder / Project Types ───────────────────────────────────

export interface FolderForm {
  name: string;
  parent_id?: string;
  meta?: Record<string, any>;
}

export interface FolderModel {
  id: string;
  name: string;
  parent_id?: string;
  user_id: string;
  meta?: Record<string, any>;
  is_expanded: boolean;
  created_at: number;
  updated_at: number;
}

// ── Agent (UI display type) ──────────────────────────────────

export interface Agent {
  id: string;
  name: string;
  baseModelId: string;
  baseModelName: string;
  description: string;
  systemPrompt: string;
  profileImageUrl?: string;
  params: ModelParams;
  capabilities: Record<string, boolean>;
  tags: string[];
  isActive: boolean;
  status: 'online' | 'offline';
  gradientColors: [string, string];
  initials: string;
}

// ── Chat History Pipeline Types ──────────────────────────────

export interface ConversationExtraction {
  conversation_id: string;
  title: string;
  domain: string;
  subdomain: string;
  project_signal: string;
  intent: string;
  complexity: 'low' | 'medium' | 'high';
  tools_mentioned: string[];
  skills_demonstrated: string[];
  recurring_theme: boolean;
  delegation_potential: 'none' | 'partial' | 'high';
  agent_signals: string[];
  key_entities: string[];
  user_role_signals: string[];
  emotional_valence: string;
}

export interface AgentRecommendation {
  agent_type: string;
  reason: string;
  confidence: 'high' | 'medium' | 'low';
  role_in_project?: string;
}

export interface ProjectCluster {
  project_id: string;
  project_name: string;
  project_description: string;
  status: 'active' | 'dormant' | 'archived';
  conversation_ids: string[];
  domains: string[];
  primary_domain: string;
  tools_used: string[];
  skills_involved: string[];
  complexity_profile: 'lightweight' | 'moderate' | 'intensive';
  delegation_profile: 'human_driven' | 'hybrid' | 'automatable';
  agent_recommendations: AgentRecommendation[];
}

// ── Concierge Output ─────────────────────────────────────────

export interface ConciergeOutput {
  user_profile: {
    name: string;
    role: string;
    ai_comfort: string;
    identity: Record<string, any>;
    pain_points: Record<string, any>;
    workflow: Record<string, any>;
    tools: Record<string, any>;
    priority: Record<string, any>;
    agent_recommendations: {
      primary_agent: string;
      primary_reason: string;
      secondary_agents: AgentRecommendation[];
      deferred_agents: Array<{ agent_type: string; trigger: string }>;
    };
    conversation_metadata: {
      questions_asked: number;
      questions_skipped: string[];
      user_engagement_level: 'high' | 'medium' | 'low';
      raw_transcript: string;
    };
  };
}

// ── Agent Factory Context ────────────────────────────────────

export interface AgentContext {
  userName?: string;
  userRole?: string;
  aiComfort?: string;
  tone?: string;
  detailLevel?: string;
  projectName?: string;
  projectDescription?: string;
  toolsUsed?: string[];
  skillsInvolved?: string[];
  painPoints?: Record<string, any>;
  magicWandAnswer?: string;
  chatExamples?: string[];
}

export interface ModelCapability {
  icon: string;
  label: string;
  description: string;
}

export interface ModelStats {
  label: string;
  value: number;
  descriptor?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  expertId?: string; // which model authored this (for group chats)
}

export interface Conversation {
  id: string;
  expertId: string;
  /** Preferred field — falls back to expertId during migration */
  agentId?: string;
  title: string;
  messages: Message[];
  lastMessageAt: number;
  createdAt: number;
}

export interface GroupConversation extends Conversation {
  isGroup: true;
  expertIds: string[];
  groupName: string;
}

export interface Expert {
  id: string;
  name: string;
  initials: string;
  specialty: string;
  description: string;
  systemPrompt: string;
  gradientColors: [string, string];
  suggestedTopics: string[];
  modelId: string;
  isAssistantManager: boolean;
  isEditable: boolean;
  createdAt: number;
  updatedAt: number;
  // New optional fields for Figma redesign
  status?: ModelStatus;
  tags?: string[];
  provider?: string;
  capabilities?: ModelCapability[];
  stats?: ModelStats[];
  version?: string;
}

export interface OnboardingAnswers {
  role: string;
  goals: string[];
  painPoints: string[];
  tone: 'direct' | 'balanced' | 'casual';
  detailLevel: 'concise' | 'brief' | 'detailed';
  proactive: boolean;
  displayName: string;
  aiComfort: 'beginner' | 'experienced' | 'power_user';
}

export interface OnboardingState {
  isComplete: boolean;
  answers: OnboardingAnswers | null;
  completedAt: number | null;
}

export interface AIModel {
  id: string;
  name: string;
  provider: string;
  description: string;
  status?: ModelStatus;
  tags?: string[];
  capabilities?: ModelCapability[];
  stats?: ModelStats[];
  version?: string;
  gradientColors?: [string, string];
}

export interface RoleOption {
  id: string;
  label: string;
  icon: string;
}

export interface GoalChip {
  id: string;
  label: string;
  icon?: string;
  agentCategories: string[];
}

export interface PainPointOption {
  id: string;
  label: string;
  icon: string;
  description?: string;
  promptModifier: string;
}

export interface HistoryEntry {
  id: string;
  type: 'chat' | 'model' | 'group' | 'system';
  title: string;
  subtitle?: string;
  timestamp: number;
  icon?: string;
  modelTag?: string;
  relatedId?: string;
}

export function isGroupConversation(conv: Conversation): conv is GroupConversation {
  return 'isGroup' in conv && (conv as GroupConversation).isGroup === true;
}

// ── Voice Session Types ─────────────────────────────────────

export type VoiceSessionState =
  | 'idle'
  | 'connecting'
  | 'setup'
  | 'ready'
  | 'listening'
  | 'responding'
  | 'error'
  | 'closed';

export interface VoiceConfig {
  voiceName: string;
  model: string;
}

export const DEFAULT_VOICE_CONFIG: VoiceConfig = {
  voiceName: 'Kore',
  model: 'projects/aicortexi-web-search/locations/us-central1/publishers/google/models/gemini-live-2.5-flash-native-audio',
};
