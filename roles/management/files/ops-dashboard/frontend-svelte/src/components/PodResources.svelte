<script lang="ts">
  import { onMount } from 'svelte';
  import { pressure, pressureColors, serviceResources, percentLabel } from '../lib/resources';
  import type { Service } from '../lib/types';

  let { list, cpu, memory, motion = true, now }: {
    list: Service[]; cpu: number | null; memory: number | null; motion?: boolean; now: number;
  } = $props();
  let element: HTMLDivElement;
  let active = $state(false);
  let foreground = $state(true);
  onMount(() => {
    const observer = new IntersectionObserver(([entry]) => { active = entry.isIntersecting; });
    observer.observe(element);
    const visibility = () => { foreground = document.visibilityState === 'visible'; };
    visibility();
    document.addEventListener('visibilitychange', visibility);
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', visibility); };
  });
  const shapes = $derived.by(() => {
    // Keep failures and busy containers visible if an unusually large pod needs
    // the overflow count. This doesn't change the alphabetical detail list.
    const rank = (s: Service) => s.status !== 'running' ? 1000 : serviceResources(s, now).peak ?? -1;
    return [...list].sort((a, b) => rank(b) - rank(a) || a.name.localeCompare(b.name)).slice(0, 24);
  });
  const columns = $derived(Math.min(5, Math.ceil(Math.sqrt(shapes.length))));
  const rows = $derived(Math.ceil(shapes.length / columns));
  const spacing = $derived(shapes.length > 12 ? 10 : 13);
</script>

<div class="visual" bind:this={element} class:moving={motion && active && foreground} aria-hidden="true">
  <svg viewBox="0 0 96 96">
    <circle class="well" cx="48" cy="48" r="33" />
    <path class="track" d="M 10 48 A 38 38 0 0 1 86 48" />
    <path class="track" d="M 86 48 A 38 38 0 0 1 10 48" />
    {#if cpu != null}
      <path class="arc" d="M 10 48 A 38 38 0 0 1 86 48" pathLength="100"
        stroke={pressureColors[pressure(cpu)]} stroke-dasharray={`${Math.min(100, Math.max(1, cpu))} 100`} />
    {/if}
    {#if memory != null}
      <path class="arc" d="M 86 48 A 38 38 0 0 1 10 48" pathLength="100"
        stroke={pressureColors[pressure(memory)]} stroke-dasharray={`${Math.min(100, Math.max(1, memory))} 100`} />
    {/if}
    {#each shapes as s, i (s.name)}
      {@const r = serviceResources(s, now)}
      {@const row = Math.floor(i / columns)}
      {@const inRow = Math.min(columns, shapes.length - row * columns)}
      {@const x = 48 + (i % columns - (inRow - 1) / 2) * spacing}
      {@const y = 48 + (row - (rows - 1) / 2) * spacing}
      <g transform={`translate(${x} ${y})`}>
        <g class="shape" class:agitated={r.speed > 0}
          style={`--pace:${r.speed || 2}s;--phase:${-i * .37}s;--travel:${r.level === 'hot' ? 1.5 : r.level === 'warm' ? 1 : .5}px`}
          fill={s.status === 'error' ? pressureColors.hot : pressureColors[r.level]}>
          <title>{s.name} · {s.status} · CPU {percentLabel(r.cpu)} · RAM {percentLabel(r.memory)}</title>
          {#if s.platform === 'azure'}<path d="M 0 -5 L 5 0 L 0 5 L -5 0 Z" />
          {:else if s.platform === 'host'}<rect x="-4" y="-4" width="8" height="8" rx="2" />
          {:else}<circle r={shapes.length > 12 ? 3.4 : 4.3} />{/if}
        </g>
      </g>
    {/each}
  </svg>
  {#if list.length > shapes.length}<span class="extra">+{list.length - shapes.length}</span>{/if}
</div>

<style>
  .visual { position: relative; width: 104px; height: 104px; align-self: center; flex-shrink: 0; }
  svg { width: 100%; height: 100%; overflow: visible; }
  .well { fill: #11171C; stroke: #26343D; stroke-width: .5; }
  .track { stroke: #2B353F; stroke-width: 3.5; fill: none; }
  .arc { fill: none; stroke-width: 3.5; stroke-linecap: round; transition: stroke .4s, stroke-dasharray .6s; }
  .shape { stroke: #0E1114; stroke-width: .6; }
  .agitated { animation: simmer var(--pace) linear infinite; animation-delay: var(--phase); animation-play-state: paused; }
  .moving .agitated { animation-play-state: running; }
  .extra { position: absolute; bottom: 4px; right: 0; font: 10px var(--mono); color: var(--sub); background: var(--surface-2); border-radius: 5px; padding: 0 3px; }
  @keyframes simmer {
    0%, 100% { transform: translate(0, 0); }
    20% { transform: translate(var(--travel), calc(var(--travel) * -.7)); }
    40% { transform: translate(calc(var(--travel) * -.7), var(--travel)); }
    60% { transform: translate(calc(var(--travel) * -1), calc(var(--travel) * -.5)); }
    80% { transform: translate(calc(var(--travel) * .5), calc(var(--travel) * .7)); }
  }
  @media (prefers-reduced-motion: reduce) { .agitated { animation: none; } .arc { transition: none; } }
</style>
