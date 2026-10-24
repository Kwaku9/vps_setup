<script lang="ts">
  import { tick } from 'svelte';
  import { api } from '../lib/api';
  import { can } from '../lib/me.svelte';
  import type { InputReceipt, LiveSession } from '../lib/types';
  import { cancelVoice, canDictate, startDictation, stopDictation, voice } from '../lib/voice.svelte';

  let { session }: { session: LiveSession } = $props();
  let expanded = $state(false);
  let draft = $state('');
  let sending = $state(false);
  let error = $state('');
  let receipts = $state<InputReceipt[]>([]);
  let textarea: HTMLTextAreaElement | undefined = $state();
  let requestId: string | null = null;
  let requestText = '';
  const writable = $derived(can('operator') && !!session.input_available);
  const dictating = $derived(voice.activeId === `dictate:${session.session_uuid}`);
  const latest = $derived(receipts[0]);
  const status = (value: string) => ({ queued: 'Waiting for workstation', claimed: 'Sending to session',
    delivered: 'Posted to session', failed: 'Not delivered', uncertain: 'Delivery unconfirmed' }[value] ?? value);

  $effect(() => {
    const sid = session.session_uuid;
    let disposed = false;
    const pull = async () => {
      try { const rows = await api.inputStatus(sid); if (!disposed) receipts = rows; } catch { /* keep the last visible receipt */ }
    };
    pull(); const interval = setInterval(pull, 3000);
    return () => { disposed = true; clearInterval(interval); cancelVoice(); };
  });

  async function compose() { expanded = true; await tick(); textarea?.focus(); }
  function collapse() { expanded = false; if (dictating) cancelVoice(); }
  async function send() {
    if (!draft.trim() || !writable || sending || dictating) return;
    if (draft !== requestText || !requestId) { requestId = crypto.randomUUID(); requestText = draft; }
    sending = true; error = '';
    try {
      const result = await api.reply(session.session_uuid, requestId, draft);
      receipts = [{ ...result, detail: null, created_at: new Date().toISOString() }, ...receipts.filter((r) => r.id !== result.id)];
      draft = ''; requestId = null; expanded = false; textarea?.blur();
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { sending = false; }
  }
  function dictate() {
    if (dictating) { if (voice.phase === 'recording') stopDictation(); else cancelVoice(); return; }
    const sid = session.session_uuid;
    startDictation(sid, (text) => { if (session.session_uuid === sid && text) draft += `${draft.trim() ? '\n' : ''}${text}`; });
  }
</script>

<div class="composer">
  {#if latest}
    <div class="receipt" role="status">
      <strong class:failed={latest.status === 'failed' || latest.status === 'uncertain'}>{status(latest.status)}</strong>
      {#if latest.detail}<span>{latest.detail}</span>{/if}
    </div>
  {/if}
  {#if expanded}
    <form onsubmit={(event) => { event.preventDefault(); send(); }}>
      <div class="compose-head"><label for="session-reply">Reply to {session.agent_kind === 'codex' ? 'Codex' : 'Claude Code'}</label>
        <button type="button" class="hide" onclick={collapse} disabled={sending}>Hide ↓</button></div>
      <textarea id="session-reply" bind:this={textarea} bind:value={draft} rows="3" maxlength="16000"
        placeholder="Write a reply to this session…" disabled={sending}></textarea>
      {#if dictating}<p class="voice-status" role="status">{voice.message}</p>{/if}
      {#if voice.error}<p class="error" role="alert">{voice.error}</p>{/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      {#if !writable}<p class="voice-status">The workstation is disconnected. Your draft is kept while this session is open.</p>{/if}
      <div class="actions">
        {#if canDictate()}<button type="button" class="btn quiet" disabled={sending} onclick={dictate}>
          {dictating ? voice.phase === 'recording' ? 'Stop microphone' : 'Cancel dictation' : '🎙 Dictate'}
        </button>{/if}
        <span class="hint">{dictating ? 'Review the draft before sending' : 'Voice runs on this device'}</span>
        <button class="btn" type="submit" disabled={!draft.trim() || !writable || sending || dictating}>{sending ? 'Sending…' : 'Send'}</button>
      </div>
    </form>
  {:else if can('operator') && session.agent_kind}
    <button class="btn quiet reply" onclick={compose} disabled={!session.input_available && !draft}>
      {draft ? 'Continue draft' : session.input_available ? 'Reply to session' : 'Workstation disconnected'}
    </button>
  {/if}
</div>

<style>
  .composer { min-width: 0; }
  .receipt { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--muted); margin-bottom: 6px; overflow-wrap: anywhere; }
  .receipt strong { color: var(--ok); font-weight: 600; } .receipt strong.failed { color: var(--warn); }
  .reply { width: 100%; min-height: 44px; }
  .compose-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
  label { font-size: 12px; font-weight: 700; }
  .hide { padding: 8px; color: var(--muted); font-size: 12px; background: none; border: 0; min-height: 36px; }
  textarea { box-sizing: border-box; width: 100%; resize: none; max-height: 24dvh; min-height: 72px; padding: 10px;
    border: 1px solid var(--line); border-radius: 10px; background: var(--bg); color: var(--text); font: 16px/1.5 var(--sans); }
  textarea:focus { border-color: var(--info); outline: 1px solid var(--info); }
  .actions { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
  .hint { flex: 1; font-size: 10px; color: var(--muted); }
  .voice-status, .error { font-size: 12px; margin: 6px 0; overflow-wrap: anywhere; }
  .voice-status { color: var(--sub); } .error { color: var(--bad-ink); }
</style>
