<script lang="ts">
  import ApprovalCard from '../components/ApprovalCard.svelte';
  import Dot from '../components/Dot.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Status from '../components/Status.svelte';
  import { api } from '../lib/api';
  import { ago, clock, num } from '../lib/fmt';
  import type { Tone } from '../lib/inventory-views';
  import { Poll } from '../lib/poll.svelte';
  import { go, route } from '../lib/router.svelte';
  import { fresh } from '../lib/triage';
  import type { LiveSession, PendingApproval, TranscriptMessage } from '../lib/types';

  let { approvals }: { approvals: Poll<PendingApproval[]> } = $props();

  const sessions = new Poll(() => api.sessions(), 8000);
  $effect(() => sessions.start());

  const tone = (s: LiveSession): Tone =>
    s.needs_approval || s.needs_input ? 'warn' : s.live_status === 'running' ? 'ok' : 'off';
  const label = (s: LiveSession) =>
    s.needs_approval ? 'waiting for approval' : s.needs_input ? 'waiting for you' : s.live_status;

  // Approvals that belong to no live session (e.g. a Telegram bot's) still need a home.
  const loose = $derived.by(() => {
    const owned = new Set((sessions.data ?? []).map((s) => s.approval_id).filter(Boolean));
    return (approvals.data ?? []).filter((a) => !owned.has(a.id));
  });
  const byId = $derived(new Map((approvals.data ?? []).map((a) => [a.id, a])));
  let showStale = $state(false);
  const live = $derived((sessions.data ?? []).filter(fresh));
  const stale = $derived((sessions.data ?? []).filter((s) => !fresh(s)));
  const listed = $derived(showStale ? [...live, ...stale] : live);
  const refreshBoth = () => { approvals.refresh(); sessions.refresh(); };

  // ── transcript sheet, opened by #/sessions/<uuid> ──
  const openUuid = $derived(route.rest[0] ?? null);
  let open = $state(false);
  let msgs = $state<TranscriptMessage[]>([]);
  let tError = $state<string | null>(null);
  let tLoading = $state(false);
  let end: HTMLElement | undefined = $state();

  $effect(() => {
    const uuid = openUuid;
    if (!uuid) { open = false; return; }
    open = true; msgs = []; tError = null; tLoading = true;
    let since = 0, stop = false;
    const pull = async () => {
      try {
        const batch = await api.transcript(uuid, since);
        if (stop) return;
        if (batch.length) {
          msgs = [...msgs, ...batch].slice(-400);
          since = batch[batch.length - 1].sequence_num;
          queueMicrotask(() => end?.scrollIntoView({ block: 'end' }));
        }
        tError = null;
      } catch (e) {
        tError = e instanceof Error ? e.message : String(e);
      } finally {
        tLoading = false;
      }
    };
    pull();
    const t = setInterval(() => { if (document.visibilityState === 'visible') pull(); }, 5000);
    return () => { stop = true; clearInterval(t); };
  });
  $effect(() => { if (!open && openUuid) go('sessions'); });

  const current = $derived((sessions.data ?? []).find((s) => s.session_uuid === openUuid));
  const text = (m: TranscriptMessage) => (m.content_text ?? '').trim();
</script>

<div class="screen">
  <header class="head">
    <h1>Sessions</h1>
    <span class="mono muted small">{sessions.data ? `${live.length} live` : ''}</span>
  </header>

  {#each loose as a (a.id)}
    <ApprovalCard approval={a} ondone={refreshBoth} />
  {/each}

  <Status loading={sessions.loading} error={sessions.error && !sessions.data ? sessions.error : null}
    empty={!!sessions.data && !live.length && !loose.length} emptyText="No live Claude sessions." />

  <ul class="list">
    {#each listed as s (s.session_uuid)}
      <li class="stack">
        <a class="item" href="#/sessions/{s.session_uuid}">
          <span class="top">
            <Dot tone={tone(s)} />
            <span class="t">{s.project ?? s.session_uuid.slice(0, 8)}</span>
            <span class="r">{ago(s.last_event_at)}</span>
          </span>
          <span class="s">{label(s)}{s.current_stage ? ` · ${s.current_stage}` : ''}</span>
          <span class="s mono">{[s.host, s.git_branch, s.model].filter(Boolean).join(' · ')}{s.output_tokens ? ` · ${num(s.output_tokens)} out` : ''}</span>
        </a>
        {#if s.approval_id && byId.get(s.approval_id)}
          <ApprovalCard approval={byId.get(s.approval_id)!} session={s} ondone={refreshBoth} />
        {/if}
      </li>
    {/each}
  </ul>
  {#if stale.length}
    <button class="linkbtn stale" onclick={() => (showStale = !showStale)}>
      {showStale ? 'Hide' : 'Show'} {stale.length} stale {stale.length === 1 ? 'session' : 'sessions'} (no activity for a day)
    </button>
  {/if}
</div>

<Sheet title={current?.project ?? 'Transcript'} bind:open>
  {#if current}<p class="muted m0 small">{label(current)} · {current.host ?? ''} · {current.git_branch ?? ''}</p>{/if}
  {#if tError}<p class="banner">{tError}</p>{/if}
  {#if tLoading}<p class="muted">Loading…</p>{:else if !msgs.length}<p class="muted">No messages yet.</p>{/if}
  <ol class="tx">
    {#each msgs.filter((m) => text(m)) as m (m.uuid)}
      <li class={m.role}>
        <span class="who mono">{m.role} · {clock(m.timestamp)}</span>
        <p>{text(m).length > 1600 ? text(m).slice(0, 1600) + '…' : text(m)}</p>
      </li>
    {/each}
  </ol>
  <span bind:this={end}></span>
</Sheet>

<style>
  .small { font-size: 12px; }
  .m0 { margin: 0; }
  .stale { display: block; margin: 14px auto 0; color: var(--muted); font-weight: 500; }
  .list > li { gap: 6px; }
  a.item { text-decoration: none; color: inherit; }
  .tx { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .tx li { background: var(--surface-2); border-radius: 12px; padding: 8px 12px; }
  .tx li.user { background: #1B2230; }
  .who { font-size: 11px; color: var(--muted); }
  .tx p { margin: 2px 0 0; font-size: 13px; white-space: pre-wrap; word-break: break-word; }
</style>
