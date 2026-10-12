<script lang="ts">
  // Loading / error / empty states for a polled list.
  let { loading = false, error = null, empty = false, emptyText = 'Nothing here.' }:
    { loading?: boolean; error?: string | null; empty?: boolean; emptyText?: string } = $props();
</script>

{#if error}
  <p class="banner" role="alert">Couldn't load: {error}</p>
{:else if loading}
  <p class="muted pad" aria-live="polite">Loading…</p>
{:else if empty}
  <p class="muted pad">{emptyText}</p>
{/if}

<style>.pad { padding: 16px 4px; margin: 0; }</style>
