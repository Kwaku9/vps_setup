<script lang="ts">
  // Bottom sheet on phones, centred panel on wide screens. A real <dialog>, so
  // focus is trapped and Escape closes it.
  import type { Snippet } from 'svelte';
  let { title, open = $bindable(false), children, footer, onbodyscroll, onbodyresize, fitVisualViewport = false }: {
    title: string; open?: boolean; children: Snippet; footer?: Snippet;
    onbodyscroll?: (event: Event & { currentTarget: EventTarget & HTMLDivElement }) => void;
    onbodyresize?: () => void;
    fitVisualViewport?: boolean;
  } = $props();
  let dlg: HTMLDialogElement | undefined = $state();
  let body: HTMLDivElement | undefined = $state();
  let visibleHeight = $state<number | undefined>();
  let keyboardInset = $state(0);
  $effect(() => {
    if (!fitVisualViewport) return;
    const viewport = window.visualViewport;
    const measure = () => {
      visibleHeight = Math.floor((viewport?.height ?? window.innerHeight) * .88);
      keyboardInset = Math.max(0, window.innerHeight - (viewport?.height ?? window.innerHeight) - (viewport?.offsetTop ?? 0));
    };
    measure(); viewport?.addEventListener('resize', measure); viewport?.addEventListener('scroll', measure);
    return () => { viewport?.removeEventListener('resize', measure); viewport?.removeEventListener('scroll', measure); };
  });
  $effect(() => {
    if (!body || !onbodyresize) return;
    const observer = new ResizeObserver(onbodyresize);
    observer.observe(body);
    return () => observer.disconnect();
  });

  $effect(() => {
    if (!dlg) return;
    if (open && !dlg.open) dlg.showModal();
    if (!open && dlg.open) dlg.close();
  });
</script>

<dialog bind:this={dlg} onclose={() => (open = false)} onclick={(e) => { if (e.target === dlg) open = false; }} aria-label={title}
  style:--sheet-height={visibleHeight ? `${visibleHeight}px` : undefined} style:--keyboard-inset={`${keyboardInset}px`}>
  {#if open}
    <div class="sheet">
      <header>
        <h2>{title}</h2>
        <button class="close" onclick={() => (open = false)} aria-label="Close">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </header>
      <div class="body" bind:this={body} class:transcript={!!onbodyscroll} onscroll={onbodyscroll}>{@render children()}</div>
      {#if footer}<footer>{@render footer()}</footer>{/if}
    </div>
  {/if}
</dialog>

<style>
  dialog { padding: 0; border: 0; background: transparent; color: var(--text); max-width: 640px; width: 100%;
    margin: auto auto var(--keyboard-inset, 0px); max-height: var(--sheet-height, 88dvh); }
  dialog::backdrop { background: rgba(0, 0, 0, .6); }
  .sheet { background: var(--surface); border-radius: 20px 20px 0 0; border-top: 1px solid var(--line);
    display: flex; flex-direction: column; max-height: var(--sheet-height, 88dvh); padding-bottom: env(safe-area-inset-bottom); }
  header { display: flex; align-items: center; gap: 12px; padding: 14px 8px 8px 18px; }
  h2 { margin: 0; font-size: 17px; font-weight: 700; flex: 1; min-width: 0; word-break: break-word; }
  .close { width: 44px; height: 44px; border-radius: 22px; border: 0; background: var(--raise); display: grid; place-items: center; flex-shrink: 0; }
  .body { overflow: auto; padding: 4px 18px 20px; display: flex; flex-direction: column; gap: 14px; }
  .body.transcript { min-height: 0; overscroll-behavior: contain; overflow-anchor: none; }
  footer { flex-shrink: 0; border-top: 1px solid var(--line); padding: 8px 18px; }
  @media (min-width: 700px) { dialog { margin: auto; } .sheet { border-radius: 20px; border: 1px solid var(--line); } }
</style>
