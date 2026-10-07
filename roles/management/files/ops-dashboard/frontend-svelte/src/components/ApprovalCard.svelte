<script lang="ts">
  import { api } from '../lib/api';
  import { until } from '../lib/fmt';
  import { can } from '../lib/me.svelte';
  import { toast } from '../lib/toast.svelte';
  import type { LiveSession, PendingApproval } from '../lib/types';

  let { approval, session, ondone }: { approval: PendingApproval; session?: LiveSession; ondone?: () => void } = $props();
  let busy = $state<null | 'approve' | 'deny'>(null);

  const meta = $derived((approval.metadata ?? {}) as Record<string, any>);
  const tool = $derived(meta.tool_name ?? session?.approval_tool ?? 'a tool');
  const where = $derived(session?.project ?? null);
  // The hook writes "Tool: Bash\nCommand: <cmd>" (or "File: …"); the tool name
  // is already in the heading, so show the rest with its label stripped.
  const body = $derived(
    approval.prompt_text.replace(/^Tool: [^\n]*\n/, '').replace(/^(Command|Input): /, '').trim(),
  );

  async function decide(d: 'approve' | 'deny') {
    busy = d;
    try {
      await api.decide(approval.id, d);
      toast(d === 'approve' ? 'Approved' : 'Denied');
      ondone?.();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true);
      ondone?.();
    } finally {
      busy = null;
    }
  }
</script>

<section class="card amber" aria-label="Approval request">
  <div class="top">
    <span class="tag">Approval · {tool}</span>
    <span class="exp mono">{until(approval.expires_at)}</span>
  </div>
  <p class="what">Claude wants to use <b>{tool}</b>{#if where} in <b>{where}</b>{/if}:</p>
  <code class="block">{body}</code>
  {#if can('admin')}
    <div class="row2">
      <button class="btn" disabled={!!busy} onclick={() => decide('deny')}>{busy === 'deny' ? 'Denying…' : 'Deny'}</button>
      <button class="btn primary" disabled={!!busy} onclick={() => decide('approve')}>{busy === 'approve' ? 'Approving…' : 'Approve'}</button>
    </div>
  {:else}
    <p class="muted small">Deciding needs the admin role.</p>
  {/if}
</section>

<style>
  .top { display: flex; align-items: center; gap: 8px; }
  .tag { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--amber); }
  .exp { margin-left: auto; font-size: 12px; color: var(--muted); }
  .what { margin: 0; }
  .small { margin: 0; font-size: 13px; }
  .btn { min-height: 48px; }
</style>
