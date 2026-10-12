<script lang="ts">
  import { untrack } from 'svelte';
  import Dot from '../components/Dot.svelte';
  import Sections from '../components/Sections.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Status from '../components/Status.svelte';
  import { api } from '../lib/api';
  import { ago } from '../lib/fmt';
  import { haystack, VIEWS, viewByKey, type Item, type View } from '../lib/inventory-views';
  import { go, route } from '../lib/router.svelte';
  import type { InventorySummary } from '../lib/types';

  // Items per view, kept for the life of the page (the graph changes nightly).
  const cache = $state<Record<string, { items?: Item[]; error?: string; at?: number }>>({});
  const TTL = 5 * 60_000;
  async function load(v: View, force = false) {
    const c = cache[v.key];
    if (!force && c?.items && Date.now() - (c.at ?? 0) < TTL) return;
    cache[v.key] = { ...c, error: undefined };
    try {
      const items = await v.load();
      cache[v.key] = { items: items.map((x) => ({ ...x, __h: haystack(x) })), at: Date.now() };
    } catch (e) {
      cache[v.key] = { ...cache[v.key], error: e instanceof Error ? e.message : String(e) };
    }
  }

  let summary = $state<InventorySummary | null>(null);
  api.summary().then((s) => (summary = s)).catch(() => {});
  const SUMMARY_KEY: Record<string, string> = {
    jobs: 'jobs', databases: 'datastores', tables: 'tables', mcp: 'mcp', credentials: 'credentials', endpoints: 'endpoints',
    pipelines: 'pipelines', alerts: 'alert_rules', scripts: 'scripts', apis: 'apis', hosts: 'hosts',
  };
  const count = (v: View) => cache[v.key]?.items?.length ?? (summary?.[SUMMARY_KEY[v.key]] as number | undefined);

  const view = $derived(viewByKey[route.rest[0]] ?? viewByKey.findings);
  // untrack: load() reads and writes the cache, which must not re-trigger this.
  $effect(() => { const v = view; untrack(() => load(v)); });

  let q = $state('');
  const query = $derived(q.trim().toLowerCase());
  $effect(() => { if (query) untrack(() => VIEWS.forEach((v) => load(v))); });
  const matches = (x: Item) => query.split(/\s+/).every((w) => x.__h.includes(w));
  const results = $derived(query
    ? VIEWS.map((v) => ({ v, items: (cache[v.key]?.items ?? []).filter(matches) })).filter((r) => r.items.length)
    : []);
  const searching = $derived(query && VIEWS.some((v) => !cache[v.key]?.items && !cache[v.key]?.error));

  let filter = $state<string | null>(null);
  $effect(() => { void view; filter = null; limit = 150; });
  let limit = $state(150);
  const items = $derived.by(() => {
    const all = cache[view.key]?.items ?? [];
    const f = view.filters?.find((x) => x.label === filter);
    return f ? all.filter(f.test) : all;
  });

  let open = $state(false);
  let picked = $state<{ v: View; x: Item } | null>(null);
  const pick = (v: View, x: Item) => { picked = { v, x }; open = true; };
</script>

<div class="screen">
  <header class="invhead">
    <div class="titleline">
      <h1>Inventory</h1>
      <span class="mono muted small">{summary?.graph_refreshed ? `graph ${ago(summary.graph_refreshed as string)}` : ''}</span>
    </div>
    <label class="search">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      <span class="sr">Search the inventory</span>
      <input type="search" bind:value={q} placeholder="Search jobs, keys, endpoints…" autocomplete="off" autocapitalize="off" spellcheck="false">
    </label>
    {#if !query}
      <div class="chips" role="tablist" aria-label="Inventory views">
        {#each VIEWS as v (v.key)}
          <button class="chip" role="tab" aria-selected={view.key === v.key} onclick={() => go('inventory', v.key)}>
            {v.label}{#if count(v) != null}<span class="n">{count(v)}</span>{/if}
          </button>
        {/each}
      </div>
    {/if}
  </header>

  {#if query}
    {#if searching}<p class="muted small">Searching every view…</p>{/if}
    {#if !searching && !results.length}<p class="muted">Nothing matches “{q}”.</p>{/if}
    {#each results as r (r.v.key)}
      <h2 class="h2">{r.v.label} <span class="mono">{r.items.length}</span></h2>
      <ul class="list">
        {#each r.items.slice(0, 25) as x, i (i)}
          {@const row = r.v.row(x)}
          <li><button class="item" onclick={() => pick(r.v, x)}>
            <span class="top"><Dot tone={row.tone} /><span class="t">{row.title}</span>{#if row.right}<span class="r">{row.right}</span>{/if}</span>
            {#if row.sub}<span class="s">{row.sub}</span>{/if}
          </button></li>
        {/each}
      </ul>
      {#if r.items.length > 25}<button class="linkbtn" onclick={() => { q = ''; go('inventory', r.v.key); }}>See all {r.items.length} in {r.v.label}</button>{/if}
    {/each}
  {:else}
    {#if view.filters?.length && cache[view.key]?.items}
      <div class="chips">
        {#each view.filters as f (f.label)}
          {@const n = cache[view.key]!.items!.filter(f.test).length}
          <button class="chip {n && f.tone ? f.tone : ''}" aria-pressed={filter === f.label}
            onclick={() => (filter = filter === f.label ? null : f.label)}>{f.label}<span class="n">{n}</span></button>
        {/each}
      </div>
    {/if}

    <Status loading={!cache[view.key]?.items && !cache[view.key]?.error} error={cache[view.key]?.error ?? null}
      empty={!!cache[view.key]?.items && !items.length} emptyText={filter ? 'Nothing matches this filter.' : 'Nothing recorded.'} />

    <ul class="list">
      {#each items.slice(0, limit) as x, i (i)}
        {@const row = view.row(x)}
        <li><button class="item" onclick={() => pick(view, x)}>
          <span class="top"><Dot tone={row.tone} /><span class="t">{row.title}</span>{#if row.right}<span class="r">{row.right}</span>{/if}</span>
          {#if row.sub}<span class="s">{row.sub}</span>{/if}
        </button></li>
      {/each}
    </ul>
    {#if items.length > limit}<button class="btn quiet more" onclick={() => (limit += 300)}>Show more ({items.length - limit} left)</button>{/if}
    {#if cache[view.key]?.at}
      <button class="linkbtn refresh" onclick={() => load(view, true)}>Loaded {ago(new Date(cache[view.key].at!).toISOString())} · refresh</button>
    {/if}
  {/if}
</div>

<Sheet title={picked ? picked.v.row(picked.x).title : ''} bind:open>
  {#if picked}<Sections sections={picked.v.detail(picked.x)} />{/if}
</Sheet>

<style>
  .invhead { display: flex; flex-direction: column; gap: 10px; padding: 8px 0 8px; }
  .titleline { display: flex; align-items: baseline; justify-content: space-between; padding: 0 4px; }
  h1 { margin: 0; font-size: 24px; font-weight: 700; }
  .small { font-size: 12px; }
  .more { width: 100%; margin-top: 10px; }
  .refresh { display: block; margin: 14px auto 0; color: var(--muted); font-weight: 500; }
</style>
