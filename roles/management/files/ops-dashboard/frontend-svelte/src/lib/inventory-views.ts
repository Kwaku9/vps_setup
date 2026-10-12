// The Inventory tab: one entry per view of /api/inventory/*. Each says how to
// load its items, how a row reads, which filter chips it offers, and what the
// detail sheet shows. Together they carry every tab and column of the Oct 1
// inventory page (jobs, databases, tables, MCP, findings) plus the newer kinds.

import { api } from './api';
import { ago, bytes, clock, dur, num, show } from './fmt';

export type Tone = 'ok' | 'warn' | 'bad' | 'off' | 'info';
export type Item = Record<string, any>;
export interface Row { title: string; right?: string; sub?: string; tone?: Tone }
export interface Section { title?: string; rows: [string, unknown][] }
export interface Filter { label: string; test: (x: Item) => boolean; tone?: Tone }
export interface View {
  key: string;
  label: string;
  load: () => Promise<Item[]>;
  row: (x: Item) => Row;
  detail: (x: Item) => Section[];
  filters?: Filter[];
}

const sevTone = (s: string): Tone => (s === 'bad' ? 'bad' : s === 'warn' ? 'warn' : 'info');
const list = (xs: unknown[] | null | undefined, n = 3) => {
  const a = (xs ?? []).filter(Boolean) as string[];
  return a.length > n ? `${a.slice(0, n).join(', ')} +${a.length - n}` : a.join(', ');
};
const join = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' · ');

// McpServer.status from the collector: ok, or why it cannot run.
const MCP_TONE: Record<string, Tone> = { ok: 'ok', remote: 'info', 'account-connector': 'info', disabled: 'off' };

const JOB_GROUP: Record<string, string> = {
  'in-ansible': 'In Ansible', unmanaged: 'Not in Ansible', 'missing-live': 'In Ansible, missing live', remote: 'Other hosts',
};

export const VIEWS: View[] = [
  {
    key: 'findings',
    label: 'Findings',
    load: () => api.findings() as Promise<Item[]>,
    row: (f) => ({ title: f.title, right: f.kind, sub: f.detail, tone: sevTone(f.severity) }),
    detail: (f) => [{ rows: [['Severity', f.severity], ['Kind', f.kind], ['What', f.title], ['Detail', f.detail]] }],
    filters: [
      { label: 'Serious', test: (f) => f.severity === 'bad', tone: 'bad' },
      { label: 'Warnings', test: (f) => f.severity === 'warn', tone: 'warn' },
      { label: 'Info', test: (f) => f.severity === 'info' },
    ],
  },
  {
    key: 'jobs',
    label: 'Jobs',
    load: () => api.inventory<Item[]>('jobs'),
    row: (j) => ({
      title: j.host ? `${j.host}: ${j.name}` : j.name,
      right: j.frequency || j.schedule,
      tone: ({ ok: 'ok', fail: 'bad', drift: 'warn', unwatched: 'info' } as Record<string, Tone>)[j.status] ?? 'info',
      sub: j.status === 'drift'
        ? `In Ansible (${j.role ?? '?'}) but not in the crontab`
        : join(
          j.last_exit_code != null ? `exit ${j.last_exit_code}` : j.last_result ? `last ${j.last_result}` : 'no run recorded yet',
          j.last_duration_s != null && dur(j.last_duration_s),
          j.last_cpu_s != null && `${dur(j.last_cpu_s)} CPU`,
          j.last_max_rss_bytes != null && bytes(j.last_max_rss_bytes),
          j.purpose,
        ),
    }),
    detail: (j) => [
      { rows: [['Purpose', j.purpose], ['Schedule', j.schedule], ['Frequency', j.frequency], ['Status', j.status],
        ['Group', JOB_GROUP[j.group] ?? j.group], ['Role', j.role], ['Where', j.where], ['Host', j.host], ['Kind', j.kind]] },
      { title: 'Last run', rows: [['Exit code', j.last_exit_code], ['Result', j.last_result], ['Ran', clock(j.last_run)],
        ['Last success', clock(j.last_success)], ['Duration', dur(j.last_duration_s)], ['CPU', dur(j.last_cpu_s)],
        ['Peak memory', bytes(j.last_max_rss_bytes)]] },
      { title: 'Wiring', rows: [['Command', j.command], ['Scripts', j.scripts], ['Log', j.log], ['Alert rules', j.alert_rules],
        ['Credentials', j.credentials], ['Outside APIs', j.apis], ['Ansible-managed', j.ansible_managed]] },
    ],
    filters: [
      { label: 'Failing', test: (j) => j.status === 'fail', tone: 'bad' },
      { label: 'Missing live', test: (j) => j.status === 'drift', tone: 'warn' },
      { label: 'In Ansible', test: (j) => j.group === 'in-ansible' },
      { label: 'Not in Ansible', test: (j) => j.group === 'unmanaged' },
      { label: 'Other hosts', test: (j) => j.group === 'remote' },
    ],
  },
  {
    key: 'databases',
    label: 'Databases',
    load: () => api.inventory<Item[]>('databases'),
    row: (d) => ({
      title: d.name,
      right: d.engine,
      tone: d.status === 'warn' ? 'warn' : d.state && d.state !== 'running' ? 'off' : 'ok',
      sub: join(bytes(d.bytes), `${d.databases?.length ?? 0} ${d.databases?.length === 1 ? 'database' : 'databases'}`,
        d.retention && `keeps ${d.retention}`, d.backed_up_by?.length ? `backup ${list(d.backed_up_by, 1)}` : 'no backup job'),
    }),
    detail: (d) => [
      { rows: [['Engine', d.engine], ['Size', bytes(d.bytes)], ['State', d.state], ['Retention', d.retention],
        ['Roles', d.roles], ['Backed up by', d.backed_up_by], ['Dashboards', d.dashboards], ['Access', d.access]] },
      { title: 'Container', rows: [['Name', d.container?.name], ['Pod', d.container?.pod], ['Ports', d.container?.ports],
        ['Memory limit', d.container?.memory_limit], ['State', d.container?.state],
        ['Memory now', d.resources?.memory_usage_mb != null ? `${Math.round(d.resources.memory_usage_mb)} MB` : null],
        ['CPU now', d.resources?.cpu_percent != null ? `${d.resources.cpu_percent.toFixed(1)}%` : null]] },
      ...(d.databases ?? []).map((db: Item) => ({
        title: db.name,
        rows: [['Size', bytes(db.bytes)], ['Tables', db.table_count || db.tables], ['Nodes', db.nodes], ['Keys', db.keys],
          ['Writers', (db.writers ?? []).map((w: Item) => `${w.who}${w.user ? ` as ${w.user}` : ''}`)],
          ['Readers', (db.readers ?? []).map((r: Item) => `${r.who}${r.user ? ` as ${r.user}` : ''}`)],
          ['Declared users', db.declared_users], ['Dashboards', db.dashboards]] as [string, unknown][],
      })),
    ],
    filters: [{ label: 'No backup', test: (d) => d.status === 'warn', tone: 'warn' }],
  },
  {
    key: 'tables',
    label: 'Tables',
    load: () => api.tables(),
    row: (t) => ({ title: `${t.schema ? `${t.schema}.` : ''}${t.table}`, right: bytes(t.bytes), sub: join(t.database, `${num(t.rows)} rows`) }),
    detail: (t) => [{ rows: [['Database', t.database], ['Schema', t.schema], ['Table', t.table], ['Rows', num(t.rows)], ['Size', bytes(t.bytes)]] }],
  },
  {
    key: 'mcp',
    label: 'MCP',
    load: async () => (await api.inventory<Item[]>('mcp')).map((r) => ({ ...r.server, runs_in: r.runs_in })),
    row: (m) => ({
      title: m.name, right: m.transport, tone: MCP_TONE[m.status] ?? 'warn',
      sub: join(m.status, m.scope, m.runs_in || m.where),
    }),
    filters: [
      { label: 'Broken', test: (m) => (MCP_TONE[m.status] ?? 'warn') === 'warn', tone: 'warn' },
      { label: 'OK', test: (m) => m.status === 'ok' },
    ],
    detail: (m) => [{ rows: [['Status', m.status], ['Scope', m.scope], ['Where', m.where], ['Transport', m.transport],
      ['Runs in', m.runs_in], ['URL', m.url], ['Command', m.command]] }],
  },
  {
    key: 'credentials',
    label: 'Keys',
    load: () => api.inventory<Item[]>('credentials'),
    row: (c) => {
      const flags = ['drift', 'conflict', 'duplicate_in_file', 'empty', 'unreferenced', 'unmanaged'].filter((k) => c[k]);
      return {
        title: c.name,
        right: c.containers?.length ? `${c.containers.length} containers` : undefined,
        tone: c.drift ? 'bad' : c.conflict || c.unmanaged || c.empty ? 'warn' : c.unreferenced ? 'off' : 'ok',
        sub: join(flags.map((f) => f.replace(/_/g, ' ')).join(', '), list(c.containers?.map((x: Item) => x.container)),
          c.grants && `grants ${c.grants}`),
      };
    },
    detail: (c) => [
      { rows: [['Vault files', c.vault_files], ['Grants', c.grants], ['Rotated', c.rotated_at ? clock(c.rotated_at) : null],
        ['Tracking since', c.tracking_since ? clock(c.tracking_since) : null], ['Same value as', c.same_value_as], ['Files', c.files]] },
      { title: 'Flags', rows: [['Live differs from vault', c.drift], ['Differs between vault files', c.conflict],
        ['Duplicated in a file', c.duplicate_in_file], ['Empty', c.empty], ['Unreferenced', c.unreferenced], ['In no vault', c.unmanaged]] },
      { title: 'Used by', rows: [
        ...(c.containers ?? []).map((x: Item) => [x.container, `${x.env}${x.matches_vault === false ? ' (differs from vault)' : ''}`] as [string, unknown]),
        ['Scripts', c.scripts]] },
    ],
    filters: [
      { label: 'Drift', test: (c) => !!c.drift, tone: 'bad' },
      { label: 'Conflict', test: (c) => !!c.conflict, tone: 'warn' },
      { label: 'In no vault', test: (c) => !!c.unmanaged, tone: 'warn' },
      { label: 'Unreferenced', test: (c) => !!c.unreferenced },
    ],
  },
  {
    key: 'endpoints',
    label: 'Endpoints',
    load: async () => (await api.inventory<Item[]>('endpoints')).map((r) => ({ ...r.endpoint, served_by: r.served_by })),
    row: (e) => ({
      title: e.name, right: e.kind,
      tone: e.flagged ? ((e.flags ?? []).some((f: string) => /PUBLIC INTERNET|straight at this host|from the internet/.test(f)) ? 'bad' : 'warn') : 'ok',
      sub: join(e.reachable, e.via, e.flags?.length ? e.flags[0] : list(e.served_by)),
    }),
    detail: (e) => [{ rows: [['Kind', e.kind], ['Host', e.host], ['Path', e.path], ['Protocol', e.proto], ['Port', e.port],
      ['Process', e.process], ['Reachable from', e.reachable], ['Via', e.via], ['Access', e.access], ['Middlewares', e.middlewares],
      ['Served by', e.served_by], ['Flags', e.flags]] }],
    filters: [{ label: 'Flagged', test: (e) => !!e.flagged, tone: 'warn' }],
  },
  {
    key: 'pipelines',
    label: 'Pipelines',
    load: async () => (await api.pipelines(true)).map((r) => r.pipeline as Item),
    row: (p) => ({
      title: p.name || p.file, right: p.system,
      tone: p.last_run_status === 'failure' ? 'bad' : p.runnable ? 'ok' : 'off',
      sub: join(p.repo, p.host, p.runnable ? 'runnable' : 'inert', p.last_run_status && `last ${p.last_run_status} ${ago(p.last_run_at)}`),
    }),
    detail: (p) => [{ rows: [['System', p.system], ['File', p.file], ['Repo', p.repo], ['Host', p.host], ['Origin', p.origin],
      ['State', p.state], ['Runnable', p.runnable], ['Triggers', p.triggers], ['Runner', p.runner], ['Deploys', p.deploys],
      ['Secrets used', p.secret_names], ['GitHub', p.github_state], ['Last run', p.last_run_status],
      ['Last run at', p.last_run_at ? clock(p.last_run_at) : null]] }],
    filters: [
      { label: 'Runnable', test: (p) => !!p.runnable },
      { label: 'Last run failed', test: (p) => p.last_run_status === 'failure', tone: 'bad' },
    ],
  },
  {
    key: 'alerts',
    label: 'Alert rules',
    load: async () => {
      const r = await api.inventory<{ rules: Item[]; unwatched: { containers?: string[]; jobs?: string[] } }>('alerts');
      return r.rules.map((x) => ({ ...x.rule, watches: x.watches }));
    },
    row: (r) => ({
      title: r.name, right: r.severity,
      tone: r.state === 'firing' ? 'bad' : r.paused ? 'off' : r.health && r.health !== 'ok' ? 'warn' : 'ok',
      sub: join(r.source, r.group, r.state, r.covers_all_containers ? 'all containers' : list(r.watches)),
    }),
    detail: (r) => [{ rows: [['Source', r.source], ['Group', r.group], ['Severity', r.severity], ['State (nightly)', r.state],
      ['Health', r.health], ['Paused', r.paused], ['Covers every container', r.covers_all_containers], ['Watches', r.watches],
      ['Expression', r.expr]] }],
    filters: [{ label: 'Firing', test: (r) => r.state === 'firing', tone: 'bad' }],
  },
  {
    key: 'scripts',
    label: 'Scripts',
    load: async () => (await api.inventory<Item[]>('scripts')).map((r) => ({ ...r.script, ...r, script: undefined })),
    row: (s) => ({ title: s.name || s.path, right: s.lang, sub: join(s.run_by?.length ? `run by ${list(s.run_by, 2)}` : 'not scheduled', list(s.apis, 2)) }),
    detail: (s) => [{ rows: [['Path', s.path], ['Language', s.lang], ['Source in repo', s.source], ['Run by', s.run_by],
      ['Runs inside', s.execs_in], ['Calls', s.calls], ['Outside APIs', s.apis], ['Credentials', s.credentials]] }],
  },
  {
    key: 'apis',
    label: 'APIs',
    load: async () => {
      const r = await api.inventory<{ outbound: Item[]; internal: Item[] }>('apis');
      return [
        ...r.outbound.map((x) => ({ ...x.api, callers: x.callers, credentials: x.credentials, direction: 'outside' })),
        ...r.internal.map((x) => ({ ...x.api, implemented_in: x.implemented_in, direction: 'internal' })),
      ];
    },
    row: (a) => a.direction === 'outside'
      ? { title: a.name, right: a.category, sub: join(a.requests_7d != null && `${num(a.requests_7d)} req/7d`, list(a.callers, 2)) }
      : {
        title: `${a.method ?? ''} ${a.path ?? ''}`.trim(), right: a.router,
        tone: a.errors_5xx_7d ? 'warn' : undefined,
        sub: join(a.hits_7d != null && `${num(a.hits_7d)} hits/7d`, a.p95_ms != null && `p95 ${Math.round(a.p95_ms)} ms`,
          a.errors_5xx_7d ? `${a.errors_5xx_7d} 5xx` : null),
      },
    detail: (a) => [{ rows: a.direction === 'outside'
      ? [['Category', a.category], ['Hosts', a.hosts], ['Requests (7 days)', num(a.requests_7d)], ['Called by', a.callers], ['Credentials', a.credentials]]
      : [['Router', a.router], ['Method', a.method], ['Path', a.path], ['Hits (7 days)', num(a.hits_7d)],
        ['4xx', a.errors_4xx_7d], ['5xx', a.errors_5xx_7d], ['p95', a.p95_ms != null ? `${Math.round(a.p95_ms)} ms` : null],
        ['Implemented in', a.implemented_in]] }],
    filters: [
      { label: 'Outside', test: (a) => a.direction === 'outside' },
      { label: 'Internal', test: (a) => a.direction === 'internal' },
    ],
  },
  {
    key: 'hosts',
    label: 'Hosts',
    load: async () => (await api.inventory<Item[]>('hosts')).map((r) => r.host as Item),
    row: (h) => ({
      title: h.name, right: h.os, tone: h.stale ? 'warn' : 'ok',
      sub: join(h.remote ? `pushed ${ago(h.snapshot_at)}` : 'this host', h.repos != null && `${h.repos} repos`,
        h.repos_dirty ? `${h.repos_dirty} dirty` : null, h.repos_unpushed ? `${h.repos_unpushed} unpushed` : null),
    }),
    detail: (h) => [{ rows: [['OS', h.os], ['Remote', h.remote], ['Snapshot', h.snapshot_at ? clock(h.snapshot_at) : null],
      ['Stale', h.stale], ['Repos', h.repos], ['Dirty', h.repos_dirty], ['Unpushed', h.repos_unpushed]] }],
  },
];

export const viewByKey = Object.fromEntries(VIEWS.map((v) => [v.key, v]));

/** Lowercased text an item matches a search on. Values only, never keys. */
export function haystack(x: Item): string {
  const out: string[] = [];
  const walk = (v: unknown) => {
    if (v == null) return;
    if (Array.isArray(v)) v.forEach(walk);
    else if (typeof v === 'object') Object.values(v as object).forEach(walk);
    else out.push(String(v));
  };
  walk(x);
  return out.join(' ').toLowerCase();
}

export { show };
