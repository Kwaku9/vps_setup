<script lang="ts">
  import { clock } from '../lib/fmt';
  import { renderMarkdown } from '../lib/markdown';
  import type { TranscriptEntry } from '../lib/transcript';
  import { listen, voice } from '../lib/voice.svelte';
  let { entry }: { entry: TranscriptEntry } = $props();
  const who = $derived(entry.kind === 'output' ? 'CLI output' : entry.role === 'user' ? 'You' : entry.role === 'assistant' ? 'Assistant' : entry.role);
  const formatted = $derived(['message', 'output'].includes(entry.kind) ? renderMarkdown(entry.text) : '');
</script>

{#if entry.kind === 'message' || entry.kind === 'output'}
  <article class="message" class:user={entry.kind === 'message' && entry.role === 'user'} class:output={entry.kind === 'output'} class:error={entry.error}>
    <header><span class="speaker">{who}</span>
      {#if entry.kind === 'message' && entry.role === 'assistant'}
        <button class="listen" onclick={() => listen(entry.id, entry.text)} aria-label={voice.activeId === entry.id ? 'Stop reading message' : 'Listen to assistant message'}>
          {voice.activeId === entry.id ? '■ Stop' : '▷ Listen'}
        </button>
      {/if}
      <time datetime={entry.timestamp ?? undefined}>{clock(entry.timestamp)}</time></header>
    {#if voice.activeId === entry.id}<p class="voice-status" role="status">{voice.message}</p>{/if}
    <div class="prose">{@html formatted}</div>
  </article>
{:else}
  <details class="activity" class:error={entry.error}>
    <summary>
      <span class="activity-head">
        <span class="kind">{entry.kind === 'command' ? 'CLI command' : entry.kind === 'call' ? 'Tool call' : entry.kind === 'result' ? (entry.error ? 'Tool error' : 'Tool output') : entry.kind === 'context' ? 'Session context' : 'Thinking'}</span>
        <time datetime={entry.timestamp ?? undefined}>{clock(entry.timestamp)}</time>
      </span>
      {#if entry.name && entry.kind !== 'command'}<strong>{entry.name}</strong>{/if}
      {#if entry.preview}<span class="preview mono">{entry.preview}</span>{/if}
      <span class="detail-hint">Tap to <span class="closed">expand</span><span class="opened">collapse</span></span>
    </summary>
    <pre aria-label={entry.kind === 'call' ? 'Tool input' : 'Full output'}><code>{entry.text}</code></pre>
  </details>
{/if}

<style>
  .message { background: var(--surface-2); border: 1px solid var(--line-soft); border-radius: 14px; padding: 14px; min-width: 0; }
  .message.user { background: #1B2230; border-color: #2c3a4e; }
  header, .activity-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
  .speaker { color: var(--ok); font-size: 12px; font-weight: 700; }
  .listen { margin-left: auto; min-height: 36px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--sub); font-size: 11px; }
  .voice-status { font-size: 11px; color: var(--muted); margin: 0 0 8px; }
  .user .speaker { color: var(--info); }
  .output .speaker { color: var(--info); }
  .message.error { border-color: var(--bad); } .message.error .speaker { color: var(--bad-ink); }
  time { color: var(--muted); font: 10px var(--mono); flex-shrink: 0; }
  .prose { font-size: 14px; line-height: 1.65; overflow-wrap: anywhere; }
  .prose :global(> :first-child) { margin-top: 0; }
  .prose :global(> :last-child) { margin-bottom: 0; }
  .prose :global(p) { margin: 10px 0; }
  .prose :global(h1), .prose :global(h2), .prose :global(h3), .prose :global(h4), .prose :global(h5), .prose :global(h6) { font-size: 15px; line-height: 1.4; margin: 20px 0 8px; color: var(--text); }
  .prose :global(h1) { font-size: 19px; } .prose :global(h2) { font-size: 17px; }
  .prose :global(ul), .prose :global(ol) { padding-left: 22px; margin: 10px 0; }
  .prose :global(li) { padding-left: 3px; margin: 6px 0; }
  .prose :global(li::marker) { color: var(--sub); }
  .prose :global(li > p) { margin: 4px 0; }
  .prose :global(blockquote) { border-left: 3px solid var(--info); padding: 1px 12px; margin: 12px 0; color: var(--sub); }
  .prose :global(code) { font: .88em/1.6 var(--mono); color: var(--code); background: var(--raise); border-radius: 4px; padding: 2px 4px; }
  .prose :global(.code-frame) { margin: 12px 0; background: var(--bg); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  .prose :global(.code-label) { display: block; padding: 6px 10px; border-bottom: 1px solid var(--line); color: var(--muted); font: 10px var(--mono); }
  .prose :global(pre), pre { margin: 0; padding: 12px; overflow: auto; white-space: pre; font: 12px/1.65 var(--mono); max-height: 360px; tab-size: 2; }
  .prose :global(pre code) { background: none; padding: 0; border-radius: 0; font: inherit; }
  .prose :global(.table-frame) { overflow-x: auto; margin: 12px 0; border: 1px solid var(--line); border-radius: 8px; }
  .prose :global(table) { border-collapse: collapse; min-width: 100%; font-size: 12px; }
  .prose :global(th), .prose :global(td) { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--line); min-width: 100px; }
  .prose :global(th) { background: var(--raise); color: var(--sub); }
  .prose :global(hr) { border: 0; border-top: 1px solid var(--line); margin: 18px 0; }
  .prose :global(a) { text-decoration: underline; text-underline-offset: 3px; }
  .activity { background: var(--bg); border: 1px solid var(--line); border-left: 3px solid var(--info); border-radius: 10px; min-width: 0; }
  .activity.error { border-left-color: var(--bad); }
  summary { padding: 10px 12px; cursor: pointer; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  .activity-head { margin-bottom: 4px; }
  .kind { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--info); }
  .error .kind { color: var(--bad-ink); }
  strong { display: block; font-size: 12px; overflow-wrap: anywhere; }
  .preview { display: block; color: var(--sub); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 4px; }
  .detail-hint { display: block; color: var(--muted); font-size: 11px; margin-top: 5px; }
  .opened, details[open] .closed { display: none; } details[open] .opened { display: inline; }
  .activity pre { border-top: 1px solid var(--line); color: var(--code); }
</style>
