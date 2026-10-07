<script lang="ts">
  import { toasts } from '../lib/toast.svelte';
</script>

<div class="toasts" aria-live="polite">
  {#each toasts as t (t.id)}<div class="toast" class:bad={t.bad}>{t.text}</div>{/each}
</div>

<style>
  .toasts { position: fixed; left: 0; right: 0; bottom: calc(var(--nav-h) + 12px); display: flex; flex-direction: column;
    align-items: center; gap: 8px; pointer-events: none; z-index: 30; padding: 0 16px; }
  .toast { background: var(--raise); border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; font-size: 14px;
    max-width: 560px; box-shadow: 0 8px 24px rgba(0,0,0,.4); }
  .toast.bad { background: var(--bad-bg); color: var(--bad-ink); border-color: #5C2327; }
</style>
