<script lang="ts">
  import type { Tone } from '../lib/inventory-views';
  let { tone = 'info', size = 8 }: { tone?: Tone | undefined; size?: number } = $props();
</script>

<span class="dot {tone}" style="width:{size}px;height:{size}px" aria-hidden="true"></span>

<style>
  .dot { display: inline-block; border-radius: 50%; flex-shrink: 0; background: var(--info); }
  .ok { background: var(--ok); } .warn { background: var(--warn); } .bad { background: var(--bad); }
  .off { background: var(--off); } .info { background: var(--info); }
</style>
