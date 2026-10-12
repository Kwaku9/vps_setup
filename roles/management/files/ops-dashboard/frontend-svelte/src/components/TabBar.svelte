<script lang="ts">
  import { route, type Tab } from '../lib/router.svelte';
  let { badges = {} }: { badges?: Partial<Record<Tab, number>> } = $props();

  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: 'triage', label: 'Triage', icon: '<path d="M12 3l9 16H3z"/><path d="M12 10v4"/><path d="M12 17h.01"/>' },
    { key: 'services', label: 'Services', icon: '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/>' },
    { key: 'sessions', label: 'Sessions', icon: '<path d="M4 6h16M4 12h10M4 18h6"/>' },
    { key: 'inventory', label: 'Inventory', icon: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="9" cy="18" r="2.5"/><path d="M8.2 7.2l7.5.4M7.2 8.3l1.3 7.3M16.7 10l-6 6.3"/>' },
    { key: 'audit', label: 'Audit', icon: '<path d="M12 4v4M12 16v4M4 12h4M16 12h4"/><circle cx="12" cy="12" r="3"/>' },
  ];
</script>

<nav aria-label="Sections">
  {#each tabs as t (t.key)}
    <a href="#/{t.key}" aria-current={route.tab === t.key ? 'page' : undefined}>
      <span class="ic">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html t.icon}</svg>
        {#if badges[t.key]}<span class="badge" aria-label="{badges[t.key]} need you">{badges[t.key]}</span>{/if}
      </span>
      {t.label}
    </a>
  {/each}
</nav>

<style>
  nav { position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
    border-top: 1px solid var(--line-soft); background: rgba(18, 21, 25, .96); backdrop-filter: blur(12px);
    padding: 6px 4px env(safe-area-inset-bottom); height: var(--nav-h); }
  a { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px; min-height: 48px;
    text-decoration: none; color: var(--muted); font-size: 11px; font-weight: 500; }
  a[aria-current='page'] { color: var(--amber); font-weight: 600; }
  .ic { position: relative; display: grid; }
  .badge { position: absolute; top: -5px; right: -10px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px;
    background: var(--amber); color: var(--amber-ink); font: 700 11px/18px var(--mono); text-align: center; }
</style>
