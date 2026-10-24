<script lang="ts">
  import { onMount } from 'svelte';
  import Dot from '../components/Dot.svelte';
  import PodResources from '../components/PodResources.svelte';
  import Sections from '../components/Sections.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Status from '../components/Status.svelte';
  import { api } from '../lib/api';
  import { ago, pct } from '../lib/fmt';
  import type { Section, Tone } from '../lib/inventory-views';
  import { can } from '../lib/me.svelte';
  import { Poll } from '../lib/poll.svelte';
  import { go, route } from '../lib/router.svelte';
  import { toast } from '../lib/toast.svelte';
  import { memoryLabel, percentLabel, podLabel, podResources, pressureColors } from '../lib/resources';
  import type { Service } from '../lib/types';

  const services = new Poll(() => api.services(), 10000);
  const triage = new Poll(() => api.triage(), 30000);
  $effect(() => services.start());
  $effect(() => triage.start());

  type Filter = 'all' | 'problems' | 'stopped';
  let filter = $state<Filter>('all');
  let busy = $state<string | null>(null);
  let motion = $state(true);
  let clock = $state(Date.now());
  onMount(() => {
    try { motion = localStorage.getItem('ops-service-motion') !== 'off'; } catch { /* Storage may be unavailable. */ }
    const timer = setInterval(() => { clock = Date.now(); }, 10000);
    return () => clearInterval(timer);
  });
  function toggleMotion() {
    motion = !motion;
    try { localStorage.setItem('ops-service-motion', motion ? 'on' : 'off'); } catch { /* Keep the in-memory preference. */ }
  }

  const tone = (s: Service): Tone =>
    s.status === 'running' ? 'ok' : s.status === 'error' ? 'bad' : s.status === 'stopped' ? 'off' : 'warn';

  // Pod-infra containers are plumbing: hidden, and the API refuses to act on them.
  const visible = $derived((services.data ?? []).filter((s) => !s.name.endsWith('-infra')));
  const pods = $derived.by(() => {
    const by = new Map<string, Service[]>();
    for (const s of visible) {
      const k = s.pod ?? (s.platform === 'vps' ? 'standalone' : s.platform);
      by.set(k, [...(by.get(k) ?? []), s]);
    }
    return [...by].map(([name, list]) => {
      const up = list.filter((s) => s.status === 'running').length;
      const resources = podResources(list, clock);
      // Azure endpoints scale to zero and host services aren't containers: show, don't judge.
      if (list.every((s) => s.platform !== 'vps')) return { name, list: list.sort((a, b) => a.name.localeCompare(b.name)), up, tone: 'info' as Tone, resources };
      const t: Tone = list.some((s) => s.status === 'error') ? 'bad' : up === list.length ? 'ok' : up === 0 ? 'off' : 'warn';
      return { name, list: list.sort((a, b) => a.name.localeCompare(b.name)), up, tone: t, resources };
    }).sort((a, b) => Number(a.list.every(s => s.platform !== 'vps')) - Number(b.list.every(s => s.platform !== 'vps')) || a.name.localeCompare(b.name));
  });
  const counts = $derived({
    all: pods.length,
    problems: pods.filter((p) => p.tone === 'bad' || p.tone === 'warn' || p.resources.level === 'hot').length,
    stopped: pods.filter((p) => p.tone === 'off').length,
  });
  const shown = $derived(pods.filter((p) =>
    filter === 'all' || (filter === 'problems' ? p.tone === 'bad' || p.tone === 'warn' || p.resources.level === 'hot' : p.tone === 'off')));
  const selected = $derived(pods.find((p) => p.name === route.rest[0]) ?? null);

  async function act(s: Service, action: 'start' | 'stop') {
    if (action === 'stop' && !confirm(`Stop ${s.name}? This is logged and sent to Telegram.`)) return;
    busy = s.name;
    try {
      const r = await (action === 'start' ? api.start(s.name) : api.stop(s.name));
      toast(r.success ? `${s.name}: ${action === 'start' ? 'started' : 'stopped'}` : `${s.name}: ${r.message}`, !r.success);
      await services.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true);
    } finally {
      busy = null;
    }
  }

  let detailOpen = $state(false);
  let detail = $state<{ name: string; sections: Section[] | null; error?: string }>({ name: '', sections: null });
  async function openDetail(s: Service) {
    detail = { name: s.name, sections: null };
    detailOpen = true;
    try {
      const d = await api.details(s.name);
      detail.sections = [
        { rows: [['Status', d.status], ['Image', d.image], ['Started', ago(d.started_at)], ['Created', ago(d.created)],
          ['Exit code', d.exit_code], ['Restart policy', d.restart_policy], ['Restarts', d.restart_count], ['Pod', d.pod],
          ['IP', d.ip_address], ['Description', s.description], ['Depends on', s.dependencies],
          ['CPU', s.cpu_percent != null ? `${s.cpu_percent.toFixed(1)}%` : null],
          ['Memory', s.memory_percent != null ? pct(s.memory_percent / 100) : null]] },
        { title: 'Command', rows: [['Command', (d.command ?? []).join(' ')]] },
        { title: 'Mounts', rows: (d.mounts ?? []).map((m) => [m.destination, `${m.source} (${m.mode || 'rw'})`] as [string, unknown]) },
        // Names only: values include secrets and never belong on a phone screen.
        { title: 'Environment (names only)', rows: [['Variables', (d.env ?? []).map(([k]) => k)]] },
      ];
    } catch (e) {
      detail.error = e instanceof Error ? e.message : String(e);
    }
  }
</script>

<div class="screen">
  <header class="head">
    <h1>Services</h1>
    {#if triage.data?.host}
      {@const h = triage.data.host}
      <span class="mono muted small">load {h.load1?.toFixed(1) ?? '—'} · RAM {pct(h.mem_used)} · disk {pct(h.disk_used)}</span>
    {/if}
  </header>

  <div class="seg" role="radiogroup" aria-label="Filter pods">
    {#each [['all', 'All'], ['problems', 'Problems'], ['stopped', 'Stopped']] as [k, label] (k)}
      <button role="radio" aria-checked={filter === k} onclick={() => (filter = k as Filter)}>
        {label} <span class="mono">{counts[k as Filter]}</span>
      </button>
    {/each}
  </div>

  <div class="visual-key">
    <span class="key-title">Container activity</span>
    <button class="motion" aria-pressed={motion} aria-label="Animate container activity" onclick={toggleMotion}>{motion ? 'Motion on' : 'Motion off'}</button>
    <div class="legend" aria-label="Resource colors">
      <span><i class="cool"></i>Low</span><span><i class="warm"></i>Busy ≥60%</span><span><i class="hot"></i>High ≥85%</span>
    </div>
    <p>CPU above · RAM below · each shape is a container</p>
  </div>

  <Status loading={services.loading} error={services.error && !services.data ? services.error : null}
    empty={!!services.data && !shown.length} emptyText="No pods match." />

  <div class="tiles">
    {#each shown as p (p.name)}
      {@const r = p.resources}
      {@const loadText = p.tone === 'off' ? 'Stopped' : r.level === 'hot' ? 'High load' : r.level === 'warm' ? 'Busy' : r.partial && r.measured ? 'Partial metrics' : r.measured ? 'Low load' : 'No load data'}
      <button class="tile {p.tone}" class:heated={r.level === 'hot'} aria-pressed={selected?.name === p.name}
        style={`--pressure:${pressureColors[r.level]}`}
        onclick={() => (selected?.name === p.name ? go('services') : go('services', p.name))}>
        <span class="pod-top"><span class="pn">{podLabel(p.name)}</span><span class="status-dot {p.tone}" aria-hidden="true"></span></span>
        <PodResources list={p.list} cpu={r.cpuPeak} memory={r.memoryPeak} {motion} now={clock} />
        <span class="load">{loadText}</span>
        <span class="pod-metrics"><span>CPU <b class="mono">{percentLabel(r.cpu)}</b></span><span>RAM <b class="mono">{memoryLabel(r.mb)}</b></span></span>
        <span class="mono pc">{p.up}/{p.list.length} {p.list.every(s => s.platform !== 'vps') ? 'running' : 'containers up'}</span>
      </button>
    {/each}
  </div>

  {#if selected}
    <h2 class="h2">{selected.name}</h2>
    <ul class="list">
      {#each selected.list as s (s.name)}
        <li class="ctr">
          <button class="container-info" onclick={() => openDetail(s)}>
            <Dot tone={tone(s)} />
            <span class="nm">
              <b>{s.name}</b>
              <span class="mono muted">{s.status}{s.cpu_percent != null ? ` · ${s.cpu_percent.toFixed(1)}% CPU` : ''}{s.memory_percent != null ? ` · ${s.memory_percent.toFixed(0)}% mem` : ''}</span>
            </span>
          </button>
          {#if s.status === 'running'}
            {#if can('admin')}<button class="btn small" disabled={busy === s.name} onclick={() => act(s, 'stop')}>{busy === s.name ? '…' : 'Stop'}</button>{/if}
          {:else if can('operator')}
            <button class="btn small quiet" disabled={busy === s.name} onclick={() => act(s, 'start')}>{busy === s.name ? '…' : 'Start'}</button>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if services.data}
    <p class="muted hint">Tap a pod to see its containers. Rings show the busiest container’s CPU and RAM percentage; values show the pod’s total usage. Missing or old measurements stay gray.</p>
  {/if}
</div>

<Sheet title={detail.name} bind:open={detailOpen}>
  {#if detail.error}<p class="banner">{detail.error}</p>
  {:else if !detail.sections}<p class="muted">Loading…</p>
  {:else}<Sections sections={detail.sections} />{/if}
</Sheet>

<style>
  .small { font-size: 12px; text-align: right; }
  .seg { display: flex; gap: 6px; background: #161A1F; border-radius: 12px; padding: 4px; margin-bottom: 12px; }
  .seg button { flex: 1; min-height: 40px; border-radius: 9px; border: 0; background: transparent; color: var(--sub); font-size: 13px; font-weight: 500; }
  .seg button[aria-checked='true'] { background: var(--line); color: var(--text); font-weight: 600; }
  .visual-key { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; padding: 0 4px; margin: 0 0 14px; }
  .key-title { font-size: 12px; font-weight: 600; color: var(--sub); }
  .motion { margin-left: auto; min-height: 36px; padding: 0 10px; border: 1px solid var(--line); background: var(--surface); border-radius: 18px; color: var(--sub); font-size: 11px; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 10px; color: var(--sub); width: 100%; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 6px; height: 6px; border-radius: 50%; }
  .legend .cool { background: #6FCF97; } .legend .warm { background: #F2BA62; } .legend .hot { background: #FF7B80; }
  .visual-key p { margin: 0; font-size: 10px; color: var(--muted); }
  .tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .tile { background: radial-gradient(ellipse at 50% 35%, #1D272F 0%, var(--surface-2) 75%); border: 1px solid color-mix(in srgb, var(--pressure) 40%, #222830);
    border-radius: 18px; padding: 12px; display: flex; flex-direction: column; gap: 6px; text-align: left; min-width: 0; }
  .tile.heated { background: radial-gradient(ellipse at 50% 35%, #342126 0%, var(--surface-2) 80%); }
  .tile[aria-pressed='true'] { outline: 2px solid var(--amber); outline-offset: 2px; }
  .pod-top { display: flex; align-items: flex-start; gap: 8px; min-height: 36px; }
  .pn { font-size: 13px; line-height: 1.35; font-weight: 600; overflow-wrap: anywhere; flex: 1; }
  .status-dot { flex-shrink: 0; margin-top: 5px; width: 6px; height: 6px; border-radius: 50%; background: var(--off); }
  .status-dot.ok { background: var(--ok); } .status-dot.warn { background: var(--warn); } .status-dot.bad { background: var(--bad); } .status-dot.info { background: var(--info); }
  .load { font-size: 11px; font-weight: 600; text-align: center; color: var(--pressure); margin-top: -2px; margin-bottom: 4px; }
  .pod-metrics { display: flex; flex-direction: column; gap: 4px; font-size: 10px; color: var(--muted); }
  .pod-metrics > span { display: flex; align-items: center; justify-content: space-between; gap: 4px; }
  .pod-metrics b { font-size: 11px; color: var(--text); font-weight: 500; white-space: nowrap; }
  .pc { font-size: 10px; color: var(--ok); border-top: 1px solid var(--line-soft); padding-top: 8px; margin-top: 4px; }
  .tile.info .pc { color: var(--muted); }
  .tile.warn .pc { color: var(--warn-ink); } .tile.off .pc { color: var(--off); }
  .tile.bad .pc { color: #FF8A8E; }
  .ctr { display: flex; align-items: center; gap: 8px; background: var(--surface); border-radius: 12px; padding: 6px 8px 6px 6px; min-height: 56px; }
  .container-info { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; background: none; border: 0; padding: 6px 8px; text-align: left; min-height: 44px; }
  .nm { display: flex; flex-direction: column; min-width: 0; }
  .nm b { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nm span { font-size: 11px; }
  .hint { padding: 12px 4px; font-size: 13px; }
  @media (min-width: 580px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
  @media (max-width: 359px) { .tile { padding: 10px; } .head { flex-wrap: wrap; } .head .small { text-align: left; } }
</style>
