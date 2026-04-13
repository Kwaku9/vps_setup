import { AIModel } from './types';

export const AVAILABLE_MODELS: AIModel[] = [
  {
    id: 'claude-sonnet-4',
    name: 'Claude Sonnet 4',
    provider: 'Anthropic',
    description: 'Fast and highly capable model for most tasks',
    status: 'online',
    tags: ['#CREATIVE', '#CODE'],
    gradientColors: ['#6C63FF', '#B794F4'],
    capabilities: [
      { icon: 'visibility', label: 'Vision', description: 'Advanced image understanding and analysis' },
      { icon: 'code', label: 'Code', description: 'Expert-level programming across languages' },
      { icon: 'memory', label: 'Context', description: '200k token context window' },
    ],
    stats: [
      { label: 'REASONING ACCURACY', value: 92 },
      { label: 'RESPONSE LATENCY', value: 95, descriptor: 'FAST' },
    ],
    version: 'V3.5-STABLE',
  },
  {
    id: 'claude-opus-4',
    name: 'Claude Opus 4',
    provider: 'Anthropic',
    description: 'The most intelligent flagship model, excelling at highly complex tasks with near-human levels of comprehension and creative fluency.',
    status: 'online',
    tags: ['#STRATEGIC', '#CREATIVE'],
    gradientColors: ['#4B0082', '#6C63FF'],
    capabilities: [
      { icon: 'visibility', label: 'Vision', description: 'State-of-the-art visual reasoning and OCR' },
      { icon: 'code', label: 'Code', description: 'Advanced Python, JS & Rust architecture logic' },
      { icon: 'memory', label: 'Context', description: '200k token window with near-perfect recall' },
    ],
    stats: [
      { label: 'REASONING ACCURACY', value: 98.4 },
      { label: 'RESPONSE LATENCY', value: 15, descriptor: 'ULTRA-LOW' },
    ],
    version: 'V1.2.4-STABLE',
  },
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: 'OpenAI',
    description: 'OpenAI\'s most capable multimodal model with advanced reasoning',
    status: 'busy',
    tags: ['#LOGIC', '#RESEARCH'],
    gradientColors: ['#10A37F', '#1A7F64'],
    capabilities: [
      { icon: 'visibility', label: 'Vision', description: 'Multi-image understanding and generation' },
      { icon: 'code', label: 'Code', description: 'Strong coding across all major languages' },
      { icon: 'memory', label: 'Context', description: '128k token context window' },
    ],
    stats: [
      { label: 'REASONING ACCURACY', value: 95 },
      { label: 'RESPONSE LATENCY', value: 70, descriptor: 'MODERATE' },
    ],
    version: 'V4O-LATEST',
  },
  {
    id: 'gemini-pro',
    name: 'Gemini Pro',
    provider: 'Google',
    description: 'Google\'s advanced multimodal AI model with strong reasoning capabilities',
    status: 'offline',
    tags: ['#MULTIMODAL', '#RESEARCH'],
    gradientColors: ['#4285F4', '#34A853'],
    capabilities: [
      { icon: 'visibility', label: 'Vision', description: 'Native multimodal processing' },
      { icon: 'code', label: 'Code', description: 'Competitive coding performance' },
      { icon: 'memory', label: 'Context', description: '1M token context window' },
    ],
    stats: [
      { label: 'REASONING ACCURACY', value: 90 },
      { label: 'RESPONSE LATENCY', value: 60, descriptor: 'MODERATE' },
    ],
    version: 'V1.5-PRO',
  },
  {
    id: 'llama-3',
    name: 'Llama 3',
    provider: 'Meta',
    description: 'Open-source large language model with strong coding and reasoning abilities',
    status: 'online',
    tags: ['#CODING', '#OPEN SOURCE'],
    gradientColors: ['#0668E1', '#00A4FF'],
    capabilities: [
      { icon: 'code', label: 'Code', description: 'Strong open-source coding benchmark scores' },
      { icon: 'memory', label: 'Context', description: '128k token context window' },
    ],
    stats: [
      { label: 'REASONING ACCURACY', value: 85 },
      { label: 'RESPONSE LATENCY', value: 80, descriptor: 'FAST' },
    ],
    version: 'V3-70B',
  },
];

export const DEFAULT_MODEL_ID = 'claude-sonnet-4';
