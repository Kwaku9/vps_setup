<script lang="ts">
  import { show, type Section } from '../lib/inventory-views';
  let { sections }: { sections: Section[] } = $props();
  const filled = (s: Section) => s.rows.filter(([, v]) => show(v) !== '—');
</script>

{#each sections as s, i (i)}
  {@const rows = filled(s)}
  {#if rows.length}
    <section>
      {#if s.title}<h3>{s.title}</h3>{/if}
      <dl>
        {#each rows as [k, v], j (j)}
          <div><dt>{k}</dt><dd class:mono={typeof v === 'string' && /[/$=]|^\w+\(/.test(v) && v.length > 24}>{show(v)}</dd></div>
        {/each}
      </dl>
    </section>
  {/if}
{/each}

<style>
  h3 { margin: 0 0 6px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
  dl { margin: 0; background: var(--surface-2); border-radius: 12px; overflow: hidden; }
  dl > div { display: grid; grid-template-columns: minmax(96px, 34%) 1fr; gap: 10px; padding: 9px 12px; border-top: 1px solid var(--line-soft); }
  dl > div:first-child { border-top: 0; }
  dt { color: var(--muted); font-size: 13px; }
  dd { margin: 0; font-size: 13px; word-break: break-word; }
  dd.mono { font-size: 12px; color: var(--code); }
</style>
