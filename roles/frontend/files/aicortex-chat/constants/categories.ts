import { MaterialIcons } from '@expo/vector-icons';

export interface Category {
  id: string;
  label: string;
  icon: keyof typeof MaterialIcons.glyphMap;
  color: string;
  keywords: string[];
  defaultModelId: string;
  description: string;
}

/**
 * Standard categories for auto-classifying chats.
 *
 * Each category defines:
 * - `strongKeywords` — high-confidence terms (3 points each)
 * - `keywords` — general terms (1 point each)
 * - `negativeKeywords` — terms that reduce the score (-2 points)
 *
 * The category with the highest positive score wins. Ties go to
 * the category listed first. Score of 0 falls to UNCATEGORIZED.
 */
export const CATEGORIES: Category[] = [
  {
    id: 'communication',
    label: 'Writing',
    icon: 'edit',
    color: '#0A84FF',
    keywords: [
      'email', 'write', 'writing', 'draft', 'rephrase', 'proofread',
      'edit', 'revision', 'tone', 'grammar', 'letter',
      'copy', 'content', 'blog', 'article', 'summary', 'note',
      'documentation', 'report', 'email editing', 'email editor',
      'email revision', 'email rephrasing',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'Email editing, content writing, and communication',
  },
  {
    id: 'infrastructure',
    label: 'Infrastructure',
    icon: 'cloud',
    color: '#5856D6',
    keywords: [
      'devops', 'docker', 'podman', 'kubernetes', 'k8s',
      'ansible', 'terraform', 'deployment', 'cicd', 'ci/cd', 'pipeline',
      'server', 'vps', 'linux', 'nginx', 'traefik', 'cloudflare tunnel',
      'dns', 'ssl', 'certificate', 'container', 'pod', 'postgres',
      'postgresql', 'database', 'redis', 'openwebui', 'open webui',
      'litellm', 'otel', 'grafana', 'prometheus', 'monitoring',
      'telegram bot', 'gateway', 'webhook', 'bolt.diy', 'datacenter',
      'circuit', 'connection test',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'DevOps, cloud, containers, and system architecture',
  },
  {
    id: 'security',
    label: 'Security',
    icon: 'shield',
    color: '#FF453A',
    keywords: [
      'security', 'firewall', 'xdr', 'cortex xdr', 'exploit', 'malware',
      'vulnerability', 'threat', 'security audit', 'compliance', 'encryption',
      'crowdsec', 'wazuh', 'ids', 'ips', 'siem', 'malware prevention',
      'cloud identity', 'identity engine',
    ],
    defaultModelId: 'claude-opus-4-6',
    description: 'Cybersecurity, threat analysis, and compliance',
  },
  {
    id: 'coding',
    label: 'Code',
    icon: 'code',
    color: '#30D158',
    keywords: [
      'code', 'coding', 'programming', 'debug', 'debugging', 'bug',
      'react', 'flutter', 'python', 'javascript', 'typescript',
      'swift', 'frontend', 'backend', 'algorithm', 'github',
      'repo', 'library', 'sdk', 'framework', 'component',
      'refactor', 'github runners',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'Software development, debugging, and architecture',
  },
  {
    id: 'trading',
    label: 'Trading',
    icon: 'trending-up',
    color: '#FF9F0A',
    keywords: [
      'trading', 'stock', 'options trading', 'options strategy',
      'options lifecycle', 'spy', 'spy options', 'market',
      'investing', 'portfolio', 'interactive brokers', 'ibkr',
      'volatility', 'hedge', 'alpha vantage', 'ticker',
      'dividend', 'earnings',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'Markets, options strategies, and financial analysis',
  },
  {
    id: 'creative',
    label: 'Creative',
    icon: 'palette',
    color: '#BF5AF2',
    keywords: [
      'design', 'creative', 'image generation', 'image creation',
      'art', 'ui design', 'ux', 'figma',
      'illustration', 'logo', 'branding', 'animation', 'video',
      '3d', 'render', 'visual', 'mockup', 'wireframe',
      'whatsapp ui', 'kids art', 'app design',
    ],
    defaultModelId: 'gpt-4o',
    description: 'Design, image generation, and visual creativity',
  },
  {
    id: 'ai_models',
    label: 'AI & Models',
    icon: 'memory',
    color: '#64D2FF',
    keywords: [
      'ai model', 'llm', 'qwen', 'llama',
      'inference', 'vram', 'gpu', 'fine-tune',
      'embedding', 'rag', 'vector', 'machine learning', 'neural',
      'transformer', 'azure ml', 'aws ai', 'sagemaker',
      'large models', 'specialized ai', 'ai infrastructure',
      'ai session', 'model info',
    ],
    defaultModelId: 'claude-opus-4-6',
    description: 'AI infrastructure, model deployment, and ML ops',
  },
  {
    id: 'research',
    label: 'Research',
    icon: 'search',
    color: '#5AC8FA',
    keywords: [
      'research', 'analysis', 'study', 'compare',
      'investigate', 'review', 'learn', 'explain',
      'weather', 'searxng', 'project progress',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'Research, analysis, and knowledge exploration',
  },
  {
    id: 'finance',
    label: 'Finance',
    icon: 'account-balance',
    color: '#34C759',
    keywords: [
      'payroll', 'adp', 'budget', 'expense', 'tax',
      'accounting', 'invoice', 'salary', 'paycheck',
      'financial', 'bank',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'Payroll, budgeting, and personal finance',
  },
  {
    id: 'health',
    label: 'Health',
    icon: 'favorite',
    color: '#FF2D55',
    keywords: [
      'health', 'wellness', 'fitness', 'workout', 'diet', 'nutrition',
      'sleep', 'mental health', 'meditation', 'exercise', 'recipe',
      'cooking', 'meal', 'vitamin', 'supplement',
    ],
    defaultModelId: 'claude-sonnet-4-6',
    description: 'Health, wellness, nutrition, and fitness',
  },
];

/** Fallback category for unclassifiable chats. */
export const UNCATEGORIZED: Category = {
  id: 'general',
  label: 'General',
  icon: 'chat',
  color: '#8E8E93', // systemGray
  keywords: [],
  defaultModelId: 'claude-sonnet-4-6',
  description: 'General conversations and uncategorized chats',
};

/**
 * Find the best matching category for a chat title + content.
 *
 * Scoring: multi-word phrases = 3 pts, single words = 1 pt.
 * Title matches are weighted 2x over content matches.
 * The first category to exceed score 0 with the highest total wins.
 */
export function categorizeChat(
  title: string,
  content?: string,
): Category {
  const titleLower = title.toLowerCase();
  const contentLower = (content ?? '').toLowerCase();

  let bestMatch: Category | null = null;
  let bestScore = 0;

  for (const cat of CATEGORIES) {
    let score = 0;

    for (const kw of cat.keywords) {
      const kwLower = kw.toLowerCase();
      const isPhrase = kwLower.includes(' ');
      const points = isPhrase ? 3 : 1;

      // Title matches are worth double
      if (titleLower.includes(kwLower)) {
        score += points * 2;
      } else if (contentLower.includes(kwLower)) {
        score += points;
      }
    }

    if (score > bestScore) {
      bestScore = score;
      bestMatch = cat;
    }
  }

  return bestMatch && bestScore > 0 ? bestMatch : UNCATEGORIZED;
}

/** Categorize an array of chats and group them by category. */
export function groupChatsByCategory(
  chats: Array<{ id: string; title: string; content?: string }>,
): Map<string, { category: Category; chats: typeof chats }> {
  const groups = new Map<string, { category: Category; chats: typeof chats }>();

  for (const chat of chats) {
    const cat = categorizeChat(chat.title, chat.content);
    const existing = groups.get(cat.id);
    if (existing) {
      existing.chats.push(chat);
    } else {
      groups.set(cat.id, { category: cat, chats: [chat] });
    }
  }

  return groups;
}
