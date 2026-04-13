import { RoleOption, GoalChip, PainPointOption } from './types';

export const ROLES: RoleOption[] = [
  { id: 'entrepreneur', label: 'Entrepreneur', icon: '🚀' },
  { id: 'professional', label: 'Professional', icon: '💼' },
  { id: 'developer', label: 'Developer', icon: '💻' },
  { id: 'creative', label: 'Creative', icon: '🎨' },
  { id: 'student', label: 'Student', icon: '📚' },
  { id: 'homemaker', label: 'Homemaker', icon: '🏠' },
];

export const GOALS: GoalChip[] = [
  { id: 'coding', label: 'Coding', icon: '💻', agentCategories: ['software_engineering', 'devops_cloud'] },
  { id: 'productivity', label: 'Productivity', icon: '⚡', agentCategories: ['productivity'] },
  { id: 'creative', label: 'Creative Writing', icon: '✍️', agentCategories: ['design', 'communication'] },
  { id: 'research', label: 'Data Analysis', icon: '📊', agentCategories: ['data_science'] },
  { id: 'career', label: 'Marketing Strategy', icon: '📈', agentCategories: ['business_strategy', 'leadership'] },
  { id: 'writing', label: 'Writing & Content', icon: '📝', agentCategories: ['communication'] },
  { id: 'health', label: 'Health & Wellness', icon: '💪', agentCategories: ['health_wellness'] },
  { id: 'finance', label: 'Finance & Investing', icon: '💰', agentCategories: ['finance'] },
  { id: 'learning', label: 'Learning & Skills', icon: '📚', agentCategories: ['productivity', 'leadership'] },
  { id: 'cooking', label: 'Cooking & Nutrition', icon: '🍳', agentCategories: ['health_wellness'] },
];

export const PAIN_POINTS: PainPointOption[] = [
  { id: 'info_overload', label: 'Information Overload', icon: '🌊', description: 'Sifting through endless data noise', promptModifier: 'Summarize first, then expand on request. Use TL;DR format when possible.' },
  { id: 'time_management', label: 'Time Management', icon: '⏰', description: 'Optimizing your daily flow', promptModifier: 'Be time-efficient. Prioritize actionable steps. Use bullet points and numbered lists.' },
  { id: 'writers_block', label: "Writer's Block", icon: '✏️', description: 'Starting from a blank page', promptModifier: 'Offer multiple creative angles. Start with brainstorming options before diving deep.' },
  { id: 'decision_fatigue', label: 'Decision Fatigue', icon: '🤔', description: 'Too many choices, no clarity', promptModifier: 'Present structured options with clear pros/cons. Make a recommendation when possible.' },
  { id: 'meal_planning', label: 'Meal Planning', icon: '🍳', description: 'Deciding what to eat daily', promptModifier: 'Include practical meal prep tips. Consider time constraints and batch cooking.' },
  { id: 'debugging', label: 'Debugging & Tech', icon: '🐛', description: 'Fixing stubborn code errors', promptModifier: 'Start with the most likely cause. Provide step-by-step debugging approaches.' },
  { id: 'financial', label: 'Financial Confusion', icon: '💰', description: 'Tracking expenses and budgets', promptModifier: 'Explain financial concepts in plain language. Use concrete examples with numbers.' },
  { id: 'creative_blocks', label: 'Creative Blocks', icon: '🎭', description: 'Running out of creative ideas', promptModifier: 'Encourage divergent thinking. Offer unexpected inspirations and cross-domain connections.' },
];

// Maps role → expert categories in priority order (higher index = higher priority score)
export const ROLE_PRIORITY_MAP: Record<string, Record<string, number>> = {
  entrepreneur: {
    business_strategy: 1.0, finance: 0.8, communication: 0.7, leadership: 0.6, productivity: 0.5, software_engineering: 0.3,
  },
  professional: {
    productivity: 0.9, communication: 0.8, leadership: 0.7, business_strategy: 0.6, finance: 0.5, data_science: 0.4,
  },
  developer: {
    software_engineering: 1.0, devops_cloud: 0.8, data_science: 0.6, productivity: 0.5, design: 0.3, communication: 0.2,
  },
  creative: {
    design: 1.0, communication: 0.8, productivity: 0.5, business_strategy: 0.3, health_wellness: 0.2,
  },
  student: {
    productivity: 0.9, communication: 0.7, software_engineering: 0.5, data_science: 0.5, finance: 0.4, health_wellness: 0.3,
  },
  homemaker: {
    health_wellness: 0.9, productivity: 0.8, finance: 0.6, communication: 0.5, leadership: 0.3,
  },
};

export const TONE_MODIFIERS: Record<string, string> = {
  direct: 'Use a direct, professional tone. Be concise and straightforward. Avoid filler words.',
  balanced: 'Use a balanced, friendly-professional tone. Be approachable but focused.',
  casual: 'Use a casual, conversational tone. Contractions are fine. Light humor welcome. Emoji acceptable.',
};

export const DETAIL_MODIFIERS: Record<string, string> = {
  concise: 'Keep responses brief and to the point. Maximum 2-3 short paragraphs. Lead with the answer.',
  brief: 'Provide a brief explanation with your answer. Use bullet points for clarity. 3-5 paragraphs max.',
  detailed: 'Provide thorough, in-depth responses with reasoning. Include examples and context. Be comprehensive.',
};

export const COMFORT_MODIFIERS: Record<string, string> = {
  beginner: 'Explain concepts in simple, non-jargon terms. Use analogies and step-by-step guidance. Define technical terms when first used.',
  experienced: 'Use standard terminology. Provide context when introducing advanced topics. Balance depth with accessibility.',
  power_user: 'Use advanced terminology freely. Skip basics. Focus on nuance, edge cases, and expert-level insights.',
};

export const PROGRESS_VALUES = [0.20, 0.36, 0.52, 0.68, 0.84, 1.0];
