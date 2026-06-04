import type { Service } from '../types';

export interface StackGroup {
  key: string;
  title: string;
  subtitle: string;
  match: (s: Service) => boolean;
}

export const STACK_GROUPS: StackGroup[] = [
  {
    key: 'core',
    title: 'Core',
    subtitle: 'Always-on infrastructure',
    match: (s) =>
      ['traefik', 'cloudflared', 'shared-db', 'victoria-metrics', 'fail2ban',
       'node-exporter', 'iptables', 'crond', 'squid'].includes(s.name),
  },
  {
    key: 'security',
    title: 'Security',
    subtitle: 'Threat detection & enforcement',
    match: (s) => ['crowdsec', 'tetragon'].includes(s.name),
  },
  {
    key: 'auth',
    title: 'Auth',
    subtitle: 'Identity & SSO',
    match: (s) =>
      ['authentik-server', 'authentik-worker', 'authentik-postgres', 'redis'].includes(s.name),
  },
  {
    key: 'ai',
    title: 'AI',
    subtitle: 'Chat, LLM routing, search',
    match: (s) =>
      ['litellm', 'open-webui', 'ai-stack-postgres', 'searxng'].includes(s.name),
  },
  {
    key: 'azure-ai',
    title: 'Azure AI',
    subtitle: 'Speech, inference, GPU models',
    match: (s) => ['whisper-stt', 'kokoro-tts'].includes(s.name) || s.platform === 'azure',
  },
  {
    key: 'monitoring',
    title: 'Monitoring',
    subtitle: 'Observability — tiered',
    match: (s) => ['alloy', 'loki', 'grafana', 'renderer', 'tempo'].includes(s.name),
  },
  {
    key: 'mgmt',
    title: 'Management',
    subtitle: 'Container & infra tools',
    match: (s) => ['ansible-deployment'].includes(s.name),
  },
  {
    key: 'comms',
    title: 'Communications',
    subtitle: 'Bot & messaging',
    match: (s) => s.name === 'telegram-gateway',
  },
  {
    key: 'mcp',
    title: 'MCP',
    subtitle: 'Claude Code MCP servers',
    match: (s) => s.name.endsWith('-mcp'),
  },
  {
    key: 'frontend',
    title: 'Frontend',
    subtitle: 'Web applications',
    match: (s) => ['journey-tracker', 'worldview-dev', 'ais-relay', 'ops-dashboard'].includes(s.name),
  },
  {
    key: 'fintech',
    title: 'Fintech',
    subtitle: 'Market data & brokerage',
    match: (s) => ['atlas-charts', 'ib-mcp-server', 'ibeam'].includes(s.name),
  },
  {
    key: 'cicd',
    title: 'CI/CD',
    subtitle: 'Build & deployment runners',
    match: (s) => s.name === 'github-runner',
  },
];

export const UNCLASSIFIED: StackGroup = {
  key: 'unclassified',
  title: 'Unclassified',
  subtitle: 'Containers not in profile config (read-only)',
  match: () => true,
};

export interface GroupedServices {
  key: string;
  title: string;
  subtitle: string;
  services: Service[];
}

/** Partition services into groups; unmatched items fall into UNCLASSIFIED. */
export function groupServices(services: Service[]): GroupedServices[] {
  const assigned = new Set<string>();
  const groups: GroupedServices[] = [];

  for (const g of STACK_GROUPS) {
    const matched: Service[] = [];
    for (const svc of services) {
      if (assigned.has(svc.name)) continue;
      if (g.match(svc)) {
        matched.push(svc);
        assigned.add(svc.name);
      }
    }
    if (matched.length > 0) {
      groups.push({ key: g.key, title: g.title, subtitle: g.subtitle, services: matched });
    }
  }

  const leftovers = services.filter((s) => !assigned.has(s.name));
  if (leftovers.length > 0) {
    groups.push({
      key: UNCLASSIFIED.key,
      title: UNCLASSIFIED.title,
      subtitle: UNCLASSIFIED.subtitle,
      services: leftovers,
    });
  }
  return groups;
}
