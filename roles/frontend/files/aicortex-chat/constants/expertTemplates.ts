import { Expert } from './types';
import { DEFAULT_MODEL_ID } from './models';

type ExpertTemplate = Omit<Expert, 'id' | 'createdAt' | 'updatedAt'>;

export const CATEGORY_KEYWORDS: Record<string, string[]> = {
  software_engineering: ['code', 'coding', 'programming', 'software', 'develop', 'debug', 'api', 'backend', 'frontend', 'app', 'web', 'mobile', 'react', 'python', 'javascript', 'typescript'],
  data_science: ['data', 'analytics', 'machine learning', 'ml', 'ai', 'statistics', 'model', 'dataset', 'visualization', 'pandas', 'tensorflow'],
  business_strategy: ['business', 'strategy', 'growth', 'revenue', 'market', 'startup', 'entrepreneur', 'scaling', 'competition', 'product'],
  productivity: ['productivity', 'time management', 'efficiency', 'workflow', 'organization', 'habits', 'focus', 'procrastination', 'goals', 'planning'],
  communication: ['writing', 'communication', 'presentation', 'public speaking', 'content', 'copywriting', 'email', 'blog', 'social media', 'marketing'],
  health_wellness: ['health', 'fitness', 'wellness', 'stress', 'mental health', 'balance', 'exercise', 'nutrition', 'sleep', 'meditation', 'burnout'],
  finance: ['finance', 'investing', 'budget', 'accounting', 'tax', 'money', 'savings', 'crypto', 'stocks', 'financial'],
  design: ['design', 'ux', 'ui', 'creative', 'visual', 'brand', 'figma', 'prototype', 'layout', 'typography', 'graphic'],
  leadership: ['leadership', 'management', 'team', 'mentor', 'coaching', 'hiring', 'culture', 'delegation', 'conflict', 'people'],
  devops_cloud: ['devops', 'infrastructure', 'cloud', 'deploy', 'docker', 'kubernetes', 'ci/cd', 'aws', 'azure', 'server', 'linux', 'terraform'],
};

export const EXPERT_TEMPLATES: Record<string, ExpertTemplate> = {
  assistant_manager: {
    name: 'Atlas',
    initials: 'AT',
    specialty: 'Team Management',
    description: 'Your AI team manager. I help organize your expert team, suggest new specialists when you need them, and retire those who have served their purpose. Think of me as your executive assistant for AI.',
    systemPrompt: '',
    gradientColors: ['#6C63FF', '#B794F4'],
    suggestedTopics: ['Add a new expert', 'Review my team', 'Suggest changes', 'Retire an expert'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: true,
    isEditable: false,
  },
  software_engineering: {
    name: 'CodePilot',
    initials: 'CP',
    specialty: 'Software Engineering',
    description: 'Expert in software architecture, code review, debugging, and best practices across multiple languages and frameworks. I help you write cleaner, faster, more maintainable code.',
    systemPrompt: '',
    gradientColors: ['#00C853', '#00E676'],
    suggestedTopics: ['Review my code', 'Debug this error', 'Architecture advice', 'Best practices'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  data_science: {
    name: 'DataLens',
    initials: 'DL',
    specialty: 'Data Science & AI',
    description: 'Specialist in data analysis, machine learning, statistical modeling, and data visualization. I help you extract insights and build intelligent systems from your data.',
    systemPrompt: '',
    gradientColors: ['#FF6D00', '#FFA726'],
    suggestedTopics: ['Analyze this data', 'ML model advice', 'Visualization ideas', 'Statistical test'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  business_strategy: {
    name: 'Strategist',
    initials: 'ST',
    specialty: 'Business Strategy',
    description: 'Expert in business planning, market analysis, growth strategy, and competitive positioning. I help you make better business decisions and scale effectively.',
    systemPrompt: '',
    gradientColors: ['#1565C0', '#42A5F5'],
    suggestedTopics: ['Growth strategy', 'Market analysis', 'Business plan review', 'Competitive edge'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  productivity: {
    name: 'FlowState',
    initials: 'FS',
    specialty: 'Productivity & Habits',
    description: 'Specialist in time management, habit building, focus techniques, and workflow optimization. I help you accomplish more with less stress and better systems.',
    systemPrompt: '',
    gradientColors: ['#00BCD4', '#4DD0E1'],
    suggestedTopics: ['Daily planning', 'Break a bad habit', 'Focus techniques', 'Workflow optimization'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  communication: {
    name: 'Scribe',
    initials: 'SC',
    specialty: 'Writing & Communication',
    description: 'Expert in professional writing, content creation, presentations, and effective communication. I help you express ideas clearly and persuasively.',
    systemPrompt: '',
    gradientColors: ['#E91E63', '#F48FB1'],
    suggestedTopics: ['Edit my writing', 'Email draft', 'Presentation outline', 'Content ideas'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  health_wellness: {
    name: 'Vitality',
    initials: 'VT',
    specialty: 'Health & Wellness',
    description: 'Specialist in physical fitness, mental health, stress management, nutrition, and work-life balance. I help you build sustainable health habits.',
    systemPrompt: '',
    gradientColors: ['#4CAF50', '#81C784'],
    suggestedTopics: ['Stress relief', 'Exercise routine', 'Better sleep', 'Work-life balance'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  finance: {
    name: 'Ledger',
    initials: 'LG',
    specialty: 'Finance & Investing',
    description: 'Expert in personal finance, investing strategies, budgeting, and financial planning. I help you make smarter financial decisions and build wealth.',
    systemPrompt: '',
    gradientColors: ['#FFD600', '#FFEE58'],
    suggestedTopics: ['Budget review', 'Investment advice', 'Tax planning', 'Financial goals'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  design: {
    name: 'Pixel',
    initials: 'PX',
    specialty: 'Design & UX',
    description: 'Specialist in user experience, visual design, branding, and prototyping. I help you create intuitive, beautiful interfaces and strong visual identities.',
    systemPrompt: '',
    gradientColors: ['#9C27B0', '#CE93D8'],
    suggestedTopics: ['UX review', 'Design feedback', 'Brand identity', 'Layout ideas'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  leadership: {
    name: 'Commander',
    initials: 'CM',
    specialty: 'Leadership & Management',
    description: 'Expert in team leadership, people management, coaching, and organizational culture. I help you become a more effective leader and build stronger teams.',
    systemPrompt: '',
    gradientColors: ['#795548', '#A1887F'],
    suggestedTopics: ['Team conflict', 'Hiring advice', 'Delegation tips', '1-on-1 prep'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
  devops_cloud: {
    name: 'CloudOps',
    initials: 'CO',
    specialty: 'DevOps & Cloud',
    description: 'Specialist in cloud infrastructure, CI/CD pipelines, containerization, and site reliability. I help you build robust, scalable, and automated infrastructure.',
    systemPrompt: '',
    gradientColors: ['#607D8B', '#90A4AE'],
    suggestedTopics: ['Deploy setup', 'Docker help', 'CI/CD pipeline', 'Cloud architecture'],
    modelId: DEFAULT_MODEL_ID,
    isAssistantManager: false,
    isEditable: true,
  },
};

export function buildSystemPrompt(expert: { name: string; specialty: string; description: string }): string {
  return `You are ${expert.name}, an AI expert specializing in ${expert.specialty}. ${expert.description}`;
}

export function buildFullSystemPrompt(
  expert: { name: string; specialty: string; description: string },
  options: {
    tone?: string;
    detailLevel?: string;
    aiComfort?: string;
    painPointModifiers?: string[];
    displayName?: string;
  }
): string {
  const parts = [buildSystemPrompt(expert)];

  if (options.tone) {
    const { TONE_MODIFIERS } = require('./onboardingData');
    parts.push(TONE_MODIFIERS[options.tone] ?? '');
  }
  if (options.detailLevel) {
    const { DETAIL_MODIFIERS } = require('./onboardingData');
    parts.push(DETAIL_MODIFIERS[options.detailLevel] ?? '');
  }
  if (options.aiComfort) {
    const { COMFORT_MODIFIERS } = require('./onboardingData');
    parts.push(COMFORT_MODIFIERS[options.aiComfort] ?? '');
  }
  if (options.painPointModifiers?.length) {
    parts.push(...options.painPointModifiers);
  }
  if (options.displayName) {
    parts.push(`Address the user as ${options.displayName}.`);
  }

  return parts.filter(Boolean).join(' ');
}
