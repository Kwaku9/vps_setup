<script lang="ts">
  import Dot from '../components/Dot.svelte';
  import Sections from '../components/Sections.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Status from '../components/Status.svelte';
  import { api } from '../lib/api';
  import { clock, show } from '../lib/fmt';
  import type { Tone } from '../lib/inventory-views';
  import { can, user } from '../lib/me.svelte';
  import { Poll } from '../lib/poll.svelte';
  import type { AuditRow } from '../lib/types';

  const rows = new Poll(() => api.audit(300), 20000);
  $effect(() => { if (can('admin')) return rows.start(); });

  const ACTIONS = new Set(['start', 'stop', 'approve', 'deny', 'profile', 'tier']);
  const FILTERS: { label: string; test: (r: AuditRow) => boolean }[] = [
    { label: 'Actions', test: (r) => ACTIONS.has(r.action) },
    { label: 'Sign-ins', test: (r) => r.action === 'login' || r.action === 'logout' },
    { label: 'Refused', test: (r) => r.outcome !== 'ok' },
  ];
  let filter = $state<string | null>('Actions');
  // Page views and socket connects are most of the log; they hide the rest.
  const noise = (r: AuditRow) => r.action === 'page' || r.action === 'ws-connect';
  const shown = $derived.by(() => {
    const f = FILTERS.find((x) => x.label === filter);
    return (rows.data ?? []).filter((r) => (f ? f.test(r) : !noise(r)));
  });
  const tone = (r: AuditRow): Tone =>
    r.outcome === 'ok' ? (ACTIONS.has(r.action) ? 'warn' : 'ok') : r.outcome === 'failed' || r.outcome === 'error' ? 'bad' : 'off';

  let open = $state(false);
  let picked = $state<AuditRow | null>(null);
</script>

<div class="screen">
  <header class="head"><h1>Audit</h1></header>

  {#if user.me && !can('admin')}
    <p class="muted">The audit log needs the admin role. You're signed in as {user.me.role}.</p>
  {:else}
    <div class="chips">
      <button class="chip" aria-pressed={filter === null} onclick={() => (filter = null)}>Everything</button>
      {#each FILTERS as f (f.label)}
        <button class="chip" aria-pressed={filter === f.label} onclick={() => (filter = f.label)}>{f.label}</button>
      {/each}
    </div>
    <Status loading={rows.loading} error={rows.error && !rows.data ? rows.error : null}
      empty={!!rows.data && !shown.length} emptyText="Nothing in the last 300 entries." />
    <ul class="list">
      {#each shown as r (r.id)}
        <li><button class="item" onclick={() => { picked = r; open = true; }}>
          <span class="top"><Dot tone={tone(r)} /><span class="t">{r.action}{r.target ? ` ${r.target}` : ''}</span><span class="r">{clock(r.ts)}</span></span>
          <span class="s">{r.username ?? 'anonymous'} · {r.outcome}{r.status ? ` ${r.status}` : ''}{r.via ? ` · via ${r.via}` : ''}</span>
        </button></li>
      {/each}
    </ul>
  {/if}
</div>

<Sheet title={picked ? `${picked.action} ${picked.target ?? ''}` : ''} bind:open>
  {#if picked}
    <Sections sections={[
      { rows: [['When', clock(picked.ts)], ['Who', picked.username], ['Role', picked.role], ['Outcome', picked.outcome],
        ['HTTP status', picked.status], ['Via', picked.via], ['Client', picked.client_ip], ['Method', picked.method], ['Route', picked.route]] },
      { title: 'Detail', rows: Object.entries(typeof picked.detail === 'object' && picked.detail ? picked.detail : { detail: picked.detail })
          .map(([k, v]) => [k, show(v)] as [string, unknown]) },
    ]} />
  {/if}
</Sheet>
