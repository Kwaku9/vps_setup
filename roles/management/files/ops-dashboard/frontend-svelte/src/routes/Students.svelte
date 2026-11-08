<script lang="ts">
  import Dot from '../components/Dot.svelte';
  import Sections from '../components/Sections.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Status from '../components/Status.svelte';
  import { api } from '../lib/api';
  import { clock } from '../lib/fmt';
  import { can, user } from '../lib/me.svelte';
  import { Poll } from '../lib/poll.svelte';
  import { toast } from '../lib/toast.svelte';
  import type { Person } from '../lib/types';

  const data = new Poll(() => api.students(), 60000);
  $effect(() => { if (can('admin')) return data.start(); });

  let view = $state<'students' | 'candidates'>('students');
  let q = $state('');
  const match = (p: Person) => {
    const s = q.trim().toLowerCase();
    return !s || [p.name, p.username, p.email].some((v) => (v ?? '').toLowerCase().includes(s));
  };
  const list = $derived((data.data?.[view] ?? []).filter(match));

  let open = $state(false);
  let picked = $state<Person | null>(null);
  let busy = $state(false);
  const isStudent = $derived(!!picked && picked.groups.includes('students'));

  async function apply() {
    if (!picked) return;
    busy = true;
    const name = picked.name || picked.username;
    try {
      if (isStudent) { await api.removeStudent(picked.pk); toast(`${name} is no longer a student`); }
      else { await api.addStudent(picked.pk); toast(`${name} is now a student`); }
      open = false;
      await data.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true);
    } finally {
      busy = false;
    }
  }
</script>

<div class="screen">
  <header class="head"><h1>Students</h1></header>

  {#if user.me && !can('admin')}
    <p class="muted">Managing students needs the admin role. You're signed in as {user.me.role}.</p>
  {:else}
    <div class="chips">
      <button class="chip" aria-pressed={view === 'students'} onclick={() => (view = 'students')}>
        Students<span class="n">{data.data?.students.length ?? ''}</span></button>
      <button class="chip" aria-pressed={view === 'candidates'} onclick={() => (view = 'candidates')}>
        Add a student<span class="n">{data.data?.candidates.length ?? ''}</span></button>
    </div>
    <label class="search">
      <span class="sr">Search people</span>
      <input type="search" placeholder="Search by name or email" bind:value={q} />
    </label>
    <Status loading={data.loading} error={data.error && !data.data ? data.error : null}
      empty={!!data.data && !list.length}
      emptyText={view === 'students' ? 'No students yet. Add one from "Add a student".' : 'Nobody else to add. People appear here after they sign up and verify their email.'} />
    <ul class="list">
      {#each list as p (p.pk)}
        <li><button class="item" onclick={() => { picked = p; open = true; }}>
          <span class="top"><Dot tone={p.active ? (view === 'students' ? 'ok' : 'off') : 'bad'} />
            <span class="t">{p.name || p.username}</span>
            <span class="r">{p.last_login ? clock(p.last_login) : 'never signed in'}</span></span>
          <span class="s">{p.email || p.username}{p.active ? '' : ' · inactive (email not verified)'}</span>
        </button></li>
      {/each}
    </ul>
  {/if}
</div>

<Sheet title={picked ? (picked.name || picked.username) : ''} bind:open>
  {#if picked}
    <Sections sections={[
      { rows: [['Username', picked.username], ['Email', picked.email], ['Active', picked.active ? 'yes' : 'no'],
        ['Last sign-in', picked.last_login ? clock(picked.last_login) : 'never'], ['Groups', picked.groups.join(', ') || 'none']] },
    ]} />
    <p class="note">
      {#if isStudent}
        Removing them takes away the student apps, the Grafana Students org and the local model. They keep the free models in Open WebUI. It applies at their next sign-in.
      {:else}
        As a student they get the student apps, the Grafana Students org, the free models plus the local model, and must set up an authenticator app at their next sign-in.
      {/if}
    </p>
    <button class="act" class:danger={isStudent} disabled={busy || (!picked.active && !isStudent)} onclick={apply}>
      {busy ? 'Working…' : isStudent ? 'Remove from students' : 'Make a student'}
    </button>
    {#if !picked.active && !isStudent}<p class="muted small">They have not verified their email yet, so they cannot be added.</p>{/if}
  {/if}
</Sheet>

<style>
  .search { display: block; margin: 4px 0 10px; }
  .search input { width: 100%; min-height: 42px; padding: 0 14px; border-radius: 12px; border: 1px solid var(--line);
    background: var(--surface-2); color: var(--text); font: 15px var(--sans); }
  .search input:focus { outline: 2px solid var(--amber); outline-offset: 1px; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .note { color: var(--sub); font-size: 14px; line-height: 1.5; margin: 14px 2px; }
  .act { width: 100%; min-height: 48px; border: 0; border-radius: 12px; background: var(--amber); color: var(--amber-ink);
    font: 600 16px var(--sans); cursor: pointer; }
  .act.danger { background: var(--bad-bg); color: var(--bad-ink); }
  .act:disabled { opacity: .5; cursor: default; }
  .small { font-size: 13px; margin-top: 8px; }
</style>
