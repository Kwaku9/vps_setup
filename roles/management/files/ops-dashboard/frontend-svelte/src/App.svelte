<script lang="ts">
  import TabBar from './components/TabBar.svelte';
  import Toasts from './components/Toasts.svelte';
  import { api } from './lib/api';
  import { loadMe } from './lib/me.svelte';
  import { Poll } from './lib/poll.svelte';
  import { route } from './lib/router.svelte';
  import Audit from './routes/Audit.svelte';
  import Inventory from './routes/Inventory.svelte';
  import Services from './routes/Services.svelte';
  import Sessions from './routes/Sessions.svelte';
  import Triage from './routes/Triage.svelte';

  loadMe();
  // Shared so the tab badge and both screens agree on what is waiting.
  const approvals = new Poll(() => api.approvals(), 10000);
  $effect(() => approvals.start());
  $effect(() => { scrollTo(0, 0); void route.tab; });
</script>

{#if route.tab === 'triage'}<Triage {approvals} />
{:else if route.tab === 'services'}<Services />
{:else if route.tab === 'sessions'}<Sessions {approvals} />
{:else if route.tab === 'inventory'}<Inventory />
{:else}<Audit />{/if}

<TabBar badges={{ triage: approvals.data?.length ?? 0 }} />
<Toasts />
