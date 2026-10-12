<script lang="ts">
  import { tick } from 'svelte';
  import ApprovalCard from '../components/ApprovalCard.svelte';
  import Dot from '../components/Dot.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Status from '../components/Status.svelte';
  import TranscriptEntry from '../components/TranscriptEntry.svelte';
  import { api } from '../lib/api';
  import { ago, num } from '../lib/fmt';
  import type { Tone } from '../lib/inventory-views';
  import { Poll } from '../lib/poll.svelte';
  import { go, route } from '../lib/router.svelte';
  import { fresh } from '../lib/triage';
  import { mergeMessages, transcriptEntries } from '../lib/transcript';
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
  let following = $state(true);
  let newMessages = $state(0);
  const entries = $derived(transcriptEntries(msgs));

  function onTranscriptScroll(event: Event & { currentTarget: EventTarget & HTMLDivElement }) {
    const body = event.currentTarget;
    following = body.scrollHeight - body.scrollTop - body.clientHeight < 72;
    if (following) newMessages = 0;
  }
  function latest() {
    following = true; newMessages = 0;
    end?.scrollIntoView({ block: 'end' });
  }

  $effect(() => {
    const uuid = openUuid;
    if (!uuid) { open = false; return; }
    open = true; msgs = []; tError = null; tLoading = true; following = true; newMessages = 0;
    let since = 0, stop = false, busy = false;
    const pull = async () => {
      if (busy || stop) return;
      busy = true;
      try {
        // Drain paginated history immediately, rather than hiding 100 rows per
        // page and making a long session take minutes to catch up to the CLI.
        let more = true;
        while (more && !stop) {
          const batch = await api.transcript(uuid, since);
          if (stop) return;
          if (batch.length) {
            const shouldFollow = following;
            const merged = mergeMessages(msgs, batch);
            if (!following) newMessages += merged.length - msgs.length;
            msgs = merged;
            const next = Math.max(...batch.map((message) => message.cursor ?? message.sequence_num));
            more = batch.length === 500 && next > since;
            since = Math.max(since, next);
            await tick();
            if (stop) return;
            if (shouldFollow) latest();
          } else more = false;
        }
        tError = null;
      } catch (e) {
        if (!stop) tError = e instanceof Error ? e.message : String(e);
      } finally {
        busy = false;
        if (!stop) tLoading = false;
      }
    };
    pull();
    const t = setInterval(() => { if (document.visibilityState === 'visible') pull(); }, 5000);
    const onVisible = () => { if (document.visibilityState === 'visible') pull(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { stop = true; clearInterval(t); document.removeEventListener('visibilitychange', onVisible); };
  });
  $effect(() => { if (!open && openUuid) go('sessions'); });

  const current = $derived((sessions.data ?? []).find((s) => s.session_uuid === openUuid));
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
    empty={!!sessions.data && !live.length && !loose.length} emptyText="No live CLI sessions." />

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

<Sheet title={current?.project ?? 'Transcript'} bind:open onbodyscroll={onTranscriptScroll}>
  {#if current}
    <div class="session-info">
      <span class="session-status"><Dot tone={tone(current)} />{label(current)}</span>
      <span class="muted mono small">{[current.host, current.git_branch, current.model].filter(Boolean).join(' · ')}</span>
      {#if current.current_stage}<span class="sub small">{current.current_stage}</span>{/if}
    </div>
  {/if}
  {#if tError}<p class="banner">{tError}</p>{/if}
  {#if tLoading}<p class="muted small">Loading transcript…</p>{:else if !entries.length}<p class="muted">No messages yet.</p>{/if}
  <ol class="tx" aria-label="Session transcript">
    {#each entries as entry (entry.id)}
      <li><TranscriptEntry {entry} /></li>
    {/each}
  </ol>
  <span class="end" bind:this={end}></span>
  {#snippet footer()}
    <div class="transcript-footer">
      <span class="muted small">{following ? 'Following latest' : 'Reading earlier'} · {entries.length} entries</span>
      {#if !following}
        <button class="btn small quiet" onclick={latest}>{newMessages ? `${newMessages} new · ` : ''}Latest ↓</button>
      {/if}
    </div>
  {/snippet}
</Sheet>

<style>
  .small { font-size: 12px; }
  .stale { display: block; margin: 14px auto 0; color: var(--muted); font-weight: 500; }
  .list > li { gap: 6px; }
  a.item { text-decoration: none; color: inherit; }
  .session-info { display: flex; flex-direction: column; gap: 6px; padding-bottom: 10px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
  .session-status { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; }
  .tx { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .tx li { min-width: 0; }
  .end { height: 1px; flex-shrink: 0; }
  .transcript-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 40px; }
</style>
