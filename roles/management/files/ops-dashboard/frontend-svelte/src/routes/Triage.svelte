<script lang="ts">
  import Account from '../components/Account.svelte';
  import ApprovalCard from '../components/ApprovalCard.svelte';
  import Dot from '../components/Dot.svelte';
  import Status from '../components/Status.svelte';
  import { api } from '../lib/api';
  import { ago, dur, pct } from '../lib/fmt';
  import { Poll } from '../lib/poll.svelte';
  import { go } from '../lib/router.svelte';
  import { buildFeed, fresh } from '../lib/triage';
  import type { PendingApproval } from '../lib/types';

  let { approvals }: { approvals: Poll<PendingApproval[]> } = $props();

  const triage = new Poll(() => api.triage(), 15000);
  const sessions = new Poll(() => api.sessions(), 15000);
  const services = new Poll(() => api.services(), 30000);
  // Findings walk the whole graph; the graph itself only changes nightly.
  const findings = new Poll(() => api.findings(), 300000);
  $effect(() => triage.start());
  $effect(() => sessions.start());
  $effect(() => services.start());
  $effect(() => findings.start());

  const feed = $derived(buildFeed({
    approvals: approvals.data ?? [],
    alerts: triage.data?.alerts ?? [],
    sessions: sessions.data ?? [],
    findings: findings.data ?? [],
  }));

  const containers = $derived.by(() => {
    const vps = (services.data ?? []).filter((s) => s.platform === 'vps' && !s.name.endsWith('-infra'));
    return { up: vps.filter((s) => s.status === 'running').length, total: vps.length };
  });
  const host = $derived(triage.data?.host);
  const sentence = (s: string | null) => (!s ? '' : /[.!?]$/.test(s) ? s : `${s}.`);
  const hot = (f: number | null | undefined, warn: number) => (f != null && f >= warn ? 'warn' : '');
  const loading = $derived(triage.loading && approvals.loading);
</script>

<div class="screen">
  <header class="head">
    <div>
      <div class="eyebrow">ops · alpine-vps</div>
      <h1>{feed.length ? 'Needs you' : 'All clear'}</h1>
    </div>
    <Account />
  </header>

  {#if host}
    <p class="hoststrip mono" aria-label="Host">
      <span>load {host.load1?.toFixed(2) ?? '—'}{host.cpus ? `/${host.cpus}` : ''}</span>
      <span class={hot(host.mem_used, 0.85)}>RAM {pct(host.mem_used)}</span>
      <span class={hot(host.swap_used, 0.9)}>swap {pct(host.swap_used)}</span>
      <span class={hot(host.disk_used, 0.85)}>disk {pct(host.disk_used)}</span>
    </p>
  {/if}
  {#if triage.data?.alerts_error}<p class="banner warn">{triage.data.alerts_error}: alerts may be missing.</p>{/if}
  <Status loading={loading} error={triage.error && !triage.data ? triage.error : null} />

  <div class="stack">
    {#each feed as c (c.key)}
      {#if c.kind === 'approval'}
        <ApprovalCard approval={c.approval} session={c.session} ondone={() => { approvals.refresh(); sessions.refresh(); }} />
      {:else if c.kind === 'alert'}
        <section class="card line">
          <Dot tone={c.tone} size={10} />
          <div class="txt">
            <b>{c.alert.name} · {c.alert.state}</b>
            <span class="sub">{sentence(c.alert.summary ?? c.alert.target)}{c.alert.since ? ` Since ${ago(c.alert.since)}.` : ''}</span>
            {#if c.alert.description}<span class="muted small">{c.alert.description}</span>{/if}
          </div>
        </section>
      {:else if c.kind === 'session'}
        <a class="card line link" href="#/sessions/{c.session.session_uuid}">
          <Dot tone="warn" size={10} />
          <div class="txt">
            <b>{c.session.project ?? 'A session'} is waiting for you</b>
            <span class="sub">{c.session.current_stage ?? 'needs input'} · {c.session.host ?? ''} · {ago(c.session.last_event_at)}</span>
          </div>
        </a>
      {:else if c.kind === 'finding'}
        <a class="card line link" href="#/inventory/findings">
          <Dot tone={c.tone} size={10} />
          <div class="txt"><b>{c.finding.title}</b><span class="sub">{c.finding.detail}</span></div>
        </a>
      {:else}
        <a class="card line link" href="#/inventory/findings">
          <Dot tone="warn" size={10} />
          <div class="txt"><b>{c.count} inventory warnings</b><span class="sub">Open Findings to review them.</span></div>
        </a>
      {/if}
    {/each}
  </div>

  <h2 class="h2">At a glance</h2>
  <div class="grid2">
    <button class="stat" class:warn={containers.total > 0 && containers.up < containers.total} onclick={() => go('services')}>
      <b>{services.data ? `${containers.up}/${containers.total}` : '—'}</b><span>containers up</span>
    </button>
    <button class="stat" class:bad={!!triage.data?.failing_jobs.length} onclick={() => go('inventory', 'jobs')}>
      <b>{triage.data?.failing_jobs.length ?? '—'}</b>
      <span>{triage.data?.failing_jobs.length ? triage.data.failing_jobs.join(', ') : 'cron jobs failing'}</span>
    </button>
    <button class="stat" onclick={() => go('sessions')}>
      <b>{sessions.data ? sessions.data.filter(fresh).length : '—'}</b><span>live Claude sessions</span>
    </button>
    <div class="stat" class:warn={(triage.data?.backup_age_s ?? 0) > 36 * 3600}>
      <b>{triage.data?.backup_age_s != null ? dur(triage.data.backup_age_s) : '—'}</b><span>since the last good backup</span>
    </div>
  </div>
</div>

<style>
  .hoststrip { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: -4px 4px 12px; font-size: 12px; color: var(--muted); }
  .hoststrip .warn { color: var(--warn-ink); }
  .line { flex-direction: row; align-items: flex-start; gap: 12px; }
  .line :global(.dot) { margin-top: 6px; }
  .link { text-decoration: none; color: inherit; }
  .txt { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .txt b { font-size: 15px; font-weight: 600; }
  .txt .sub { font-size: 13px; }
  .small { font-size: 12px; }
</style>
