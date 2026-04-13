import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import type { Service } from '../../types';
import { StackGroup } from './StackGroup';

// Stack group definitions — order matters for display
const STACK_GROUPS: { key: string; title: string; match: (s: Service) => boolean }[] = [
  {
    key: 'core',
    title: 'CORE \u2014 Always-on infrastructure',
    match: (s) =>
      ['traefik', 'cloudflared', 'shared-db', 'victoria-metrics', 'fail2ban', 'node-exporter', 'iptables', 'crond', 'squid'].includes(s.name),
  },
  {
    key: 'security',
    title: 'SECURITY \u2014 Threat detection & enforcement',
    match: (s) => ['crowdsec', 'tetragon'].includes(s.name),
  },
  {
    key: 'auth',
    title: 'AUTH \u2014 Identity & SSO',
    match: (s) => ['authentik-server', 'authentik-worker', 'authentik-postgres', 'redis'].includes(s.name),
  },
  {
    key: 'ai',
    title: 'AI \u2014 Chat, LLM routing, speech, search',
    match: (s) => ['litellm', 'open-webui', 'ai-stack-postgres', 'searxng'].includes(s.name),
  },
  {
    key: 'azure-ai',
    title: 'AZURE AI \u2014 Speech, inference, GPU models',
    match: (s) => ['whisper-stt', 'kokoro-tts'].includes(s.name) || s.platform === 'azure',
  },
  {
    key: 'monitoring',
    title: 'MONITORING \u2014 Observability (tiered)',
    match: (s) => ['alloy', 'loki', 'grafana', 'renderer', 'tempo'].includes(s.name),
  },
  {
    key: 'mgmt',
    title: 'MANAGEMENT \u2014 Container & infra management',
    match: (s) => ['portainer', 'ansible-deployment'].includes(s.name),
  },
  {
    key: 'comms',
    title: 'COMMUNICATIONS \u2014 Bot & messaging',
    match: (s) => s.name === 'telegram-gateway',
  },
  {
    key: 'mcp',
    title: 'MCP \u2014 Claude Code MCP servers',
    match: (s) => s.name.endsWith('-mcp'),
  },
  {
    key: 'frontend',
    title: 'FRONTEND \u2014 Web applications',
    match: (s) => ['journey-tracker', 'worldview-dev', 'ais-relay'].includes(s.name),
  },
  {
    key: 'fintech',
    title: 'FINTECH \u2014 Market data & brokerage',
    match: (s) => ['atlas-charts', 'ib-mcp-server', 'ibeam'].includes(s.name),
  },
  {
    key: 'cicd',
    title: 'CI/CD \u2014 Build & deployment runners',
    match: (s) => s.name === 'github-runner',
  },
];

export function ServiceGrid() {
  const { services, metrics } = useDashboard();

  // Merge metrics status into services
  const enriched = useMemo(() => {
    return services.map((svc) => {
      const m = metrics[svc.name];
      return m ? { ...svc, status: m.status, cpu_percent: m.cpu_percent, memory_percent: m.memory_percent } : svc;
    });
  }, [services, metrics]);

  // Group services
  const groups = useMemo(() => {
    const assigned = new Set<string>();
    return STACK_GROUPS.map((group) => {
      const matched = enriched.filter((s) => {
        if (assigned.has(s.name)) return false;
        if (group.match(s)) {
          assigned.add(s.name);
          return true;
        }
        return false;
      });
      return { ...group, services: matched };
    }).filter((g) => g.services.length > 0);
  }, [enriched]);

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group) => (
        <StackGroup key={group.key} title={group.title} services={group.services} />
      ))}
    </div>
  );
}
