import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  addStudent, decideAccessRequest, fetchAccessRequests, fetchMe, fetchStudents, removeStudent,
  type AccessRequest, type Me, type Person,
} from '../../api/client';
import { useToast } from '../../contexts/ToastContext';
import { StudentProgressView } from './StudentProgressView';

const KIND_LABEL: Record<string, string> = { students: 'Student access', paid_users: 'Paid models', other: 'Something else' };
const STATUS_TONE: Record<string, string> = {
  pending: 'text-amber-300 border-amber-300/40',
  approved: 'text-emerald-300 border-emerald-300/40',
  denied: 'text-red-300 border-red-300/40',
  withdrawn: 'text-white/40 border-white/20',
};

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'never';

function RequestCard({ r, onDone }: { r: AccessRequest; onDone: () => void }) {
  const { push } = useToast();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<null | 'approve' | 'deny'>(null);
  const pending = r.status === 'pending';

  const decide = async (decision: 'approve' | 'deny') => {
    setBusy(decision);
    try {
      const res = await decideAccessRequest(r.id, decision, note);
      push({
        kind: 'success',
        title: `Request #${r.id} ${res.status}`,
        body: res.granted_group ? `${r.email} joined ${res.granted_group}. It applies at their next sign-in.` : undefined,
      });
      onDone();
    } catch (e) {
      push({ kind: 'error', title: `Request #${r.id} not changed`, body: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className="glass rounded-2xl p-4 grid gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[13px] font-semibold">#{r.id} {KIND_LABEL[r.kind] ?? r.kind}</span>
        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${STATUS_TONE[r.status]}`}>{r.status}</span>
        <span className="ml-auto text-[11px] text-white/45">{when(r.created_at)}</span>
      </div>
      <div className="text-[12px] text-white/70">{r.username ? `${r.username} · ` : ''}{r.email}</div>
      <p className="text-[13px] text-white/80 whitespace-pre-wrap break-words m-0">{r.reason}</p>
      {!pending && (
        <div className="text-[11px] text-white/45">
          {r.status === 'withdrawn' ? 'Withdrawn' : `${r.status === 'approved' ? 'Approved' : 'Denied'} by ${r.decided_by}`} · {when(r.decided_at)}
          {r.note && <span className="block mt-1 text-white/70 whitespace-pre-wrap">Reply: {r.note}</span>}
        </div>
      )}
      {pending && (
        <>
          <label className="sr-only" htmlFor={`note-${r.id}`}>Reply to the requester</label>
          <textarea
            id={`note-${r.id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} rows={2}
            placeholder="Optional reply. They see it on the request page."
            className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
          />
          {r.kind === 'other' && (
            <p className="text-[11px] text-white/45 m-0">Approving "Something else" only records the answer. Grant it by hand.</p>
          )}
          <div className="flex gap-2 justify-end">
            <button onClick={() => decide('deny')} disabled={!!busy}
              className="rounded-full px-4 py-1.5 text-[13px] font-semibold border border-red-300/40 text-red-200 hover:bg-red-400/10 disabled:opacity-50">
              {busy === 'deny' ? 'Denying…' : 'Deny'}
            </button>
            <button onClick={() => decide('approve')} disabled={!!busy}
              className="rounded-full px-4 py-1.5 text-[13px] font-semibold bg-cyan-400 text-gray-950 hover:bg-cyan-300 disabled:opacity-50">
              {busy === 'approve' ? 'Approving…' : r.kind === 'other' ? 'Approve' : `Approve and add to ${r.kind}`}
            </button>
          </div>
        </>
      )}
    </li>
  );
}

function PersonRow({ p, isStudent, onDone }: { p: Person; isStudent: boolean; onDone: () => void }) {
  const { push } = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const name = p.name || p.username;

  const apply = async () => {
    setBusy(true);
    try {
      if (isStudent) { await removeStudent(p.pk); push({ kind: 'success', title: `${name} is no longer a student` }); }
      else { await addStudent(p.pk); push({ kind: 'success', title: `${name} is now a student` }); }
      setOpen(false);
      onDone();
    } catch (e) {
      push({ kind: 'error', title: 'Not changed', body: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="glass rounded-2xl">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="w-full text-left px-4 py-3 grid grid-cols-[10px_minmax(0,1fr)_auto] gap-3 items-center">
        <span className={`h-2 w-2 rounded-full ${!p.active ? 'bg-red-400' : isStudent ? 'bg-emerald-400' : 'bg-white/30'}`} />
        <span className="min-w-0">
          <span className="block text-[13px] font-semibold truncate">{name}</span>
          <span className="block text-[11px] text-white/50 truncate">
            {p.email || p.username}{p.active ? '' : ' · inactive (email not verified)'}
          </span>
        </span>
        <span className="text-[11px] text-white/45">{p.last_login ? when(p.last_login) : 'never signed in'}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 grid gap-2 text-[12px] text-white/70">
          <div>Groups: {p.groups.join(', ') || 'none'}</div>
          <p className="m-0 text-white/55">
            {isStudent
              ? 'Removing them takes away the student apps, the Grafana Students org and the local model. They keep the free models. It applies at their next sign-in.'
              : 'As a student they get the student apps, the Grafana Students org, the free models plus the local model, and must set up an authenticator app at their next sign-in.'}
          </p>
          <div className="flex justify-end">
            <button onClick={apply} disabled={busy || (!p.active && !isStudent)}
              className={`rounded-full px-4 py-1.5 text-[13px] font-semibold disabled:opacity-50 ${
                isStudent ? 'border border-red-300/40 text-red-200 hover:bg-red-400/10' : 'bg-cyan-400 text-gray-950 hover:bg-cyan-300'}`}>
              {busy ? 'Working…' : isStudent ? 'Remove from students' : 'Make a student'}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

export function StudentsView() {
  const [me, setMe] = useState<Me | null>(null);
  const [people, setPeople] = useState<{ students: Person[]; candidates: Person[] } | null>(null);
  const [requests, setRequests] = useState<AccessRequest[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<'students' | 'candidates'>('students');
  const [showDone, setShowDone] = useState(false);
  const [mode, setMode] = useState<'progress' | 'manage'>('progress');
  const [q, setQ] = useState('');

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([fetchStudents(), fetchAccessRequests()]);
      setPeople(p); setRequests(r.requests); setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { fetchMe().then(setMe).catch(() => setMe(null)); }, []);
  useEffect(() => {
    if (me?.role !== 'admin') return;
    const first = setTimeout(load, 0);
    const t = setInterval(load, 60000);
    return () => { clearTimeout(first); clearInterval(t); };
  }, [me, load]);

  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (people?.[view] ?? []).filter((p) => !s || [p.name, p.username, p.email].some((v) => (v ?? '').toLowerCase().includes(s)));
  }, [people, view, q]);
  const pending = (requests ?? []).filter((r) => r.status === 'pending');
  const done = (requests ?? []).filter((r) => r.status !== 'pending');

  if (me && me.role !== 'admin') {
    return (
      <div className="mx-auto max-w-7xl w-full px-4 md:px-6">
        <p className="text-white/60 text-[14px]">Managing students needs the admin role. You are signed in as {me.role}.</p>
      </div>
    );
  }

  const switcher = (
    <div className="glass rounded-full p-1 inline-flex justify-self-start">
      {(['progress', 'manage'] as const).map((m) => (
        <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
          className={`px-4 py-1.5 text-[13px] font-semibold rounded-full ${mode === m ? 'bg-white/10 text-white' : 'text-white/60'}`}>
          {m === 'progress' ? 'Progress' : `Manage${pending.length ? ` (${pending.length} waiting)` : ''}`}
        </button>
      ))}
    </div>
  );

  if (mode === 'progress') {
    return (
      <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pb-28 lg:pb-6 grid gap-4">
        {switcher}
        <StudentProgressView />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pb-28 lg:pb-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="lg:col-span-2">{switcher}</div>
      {err && <div className="lg:col-span-2 glass rounded-2xl p-3 text-[13px] text-red-300">{err}</div>}

      <section className="grid gap-3 content-start" aria-labelledby="req-h">
        <div className="flex items-baseline gap-3">
          <h2 id="req-h" className="text-[15px] font-semibold m-0">Access requests</h2>
          <span className="text-[12px] text-white/45">{requests ? `${pending.length} waiting` : 'Loading…'}</span>
        </div>
        <p className="text-[12px] text-white/45 m-0">
          People ask at portal.aicortex.cloud/request. Approving student access or paid models adds them to that group.
        </p>
        {requests && pending.length === 0 && (
          <div className="glass rounded-2xl p-4 text-[13px] text-white/55">Nothing waiting.</div>
        )}
        <ul className="grid gap-3 list-none p-0 m-0">
          {pending.map((r) => <RequestCard key={r.id} r={r} onDone={load} />)}
        </ul>
        {done.length > 0 && (
          <button onClick={() => setShowDone(!showDone)} className="justify-self-start text-[12px] text-white/55 hover:text-white">
            {showDone ? 'Hide' : 'Show'} decided ({done.length})
          </button>
        )}
        {showDone && (
          <ul className="grid gap-3 list-none p-0 m-0">
            {done.map((r) => <RequestCard key={r.id} r={r} onDone={load} />)}
          </ul>
        )}
      </section>

      <section className="grid gap-3 content-start" aria-labelledby="ppl-h">
        <h2 id="ppl-h" className="text-[15px] font-semibold m-0">People</h2>
        <div className="glass rounded-full p-1 inline-flex justify-self-start">
          {(['students', 'candidates'] as const).map((v) => (
            <button key={v} onClick={() => setView(v)} aria-pressed={view === v}
              className={`px-4 py-1.5 text-[13px] font-semibold rounded-full ${view === v ? 'bg-white/10 text-white' : 'text-white/60'}`}>
              {v === 'students' ? 'Students' : 'Add a student'}
              <span className="ml-1.5 text-white/40 tabular-nums">{people?.[v].length ?? ''}</span>
            </button>
          ))}
        </div>
        <label className="block">
          <span className="sr-only">Search people</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name or email"
            className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-cyan-400/60" />
        </label>
        {people && list.length === 0 && (
          <div className="glass rounded-2xl p-4 text-[13px] text-white/55">
            {view === 'students' ? 'No students yet. Add one from "Add a student".' : 'Nobody else to add. People appear here after they sign up and verify their email.'}
          </div>
        )}
        <ul className="grid gap-2 list-none p-0 m-0">
          {list.map((p) => <PersonRow key={p.pk} p={p} isStudent={view === 'students'} onDone={load} />)}
        </ul>
      </section>
    </div>
  );
}
