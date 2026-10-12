<script lang="ts">
  import { api } from '../lib/api';
  import { clock } from '../lib/fmt';
  import { user } from '../lib/me.svelte';
  import Sheet from './Sheet.svelte';
  let open = $state(false);
  const initials = $derived((user.me?.username ?? '?').split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase());
</script>

<button class="av" onclick={() => (open = true)} aria-label="Account: {user.me?.username ?? 'loading'}, {user.me?.role ?? ''}">{initials}</button>

<Sheet title="Account" bind:open>
  {#if user.me}
    <p class="m0"><b>{user.me.username}</b><br><span class="sub">{user.me.role} · signed in via {user.me.via} · {clock(new Date(user.me.iat * 1000).toISOString())}</span></p>
  {/if}
  <a class="btn quiet" href="/">Open the classic dashboard</a>
  <button class="btn" onclick={() => api.logout()}>Sign out</button>
</Sheet>

<style>
  .av { width: 44px; height: 44px; border-radius: 22px; border: 1px solid var(--line); background: var(--surface); font: 600 14px var(--sans); flex-shrink: 0; }
  .m0 { margin: 0; }
  a.btn { text-decoration: none; color: var(--text); }
</style>
