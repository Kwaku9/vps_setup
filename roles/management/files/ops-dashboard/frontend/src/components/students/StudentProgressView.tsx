import { useCallback, useEffect, useState } from 'react';
import { fetchStudentProgress, type StudentProgress } from '../../api/client';

const PERIODS = [7, 30, 90, 365] as const;

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'never';
const ago = (iso: string | null, now: number) => {
  if (!iso) return 'no activity yet';
  const d = Math.floor((now - new Date(iso).getTime()) / 86400000);
  return d <= 0 ? 'active today' : d === 1 ? 'active yesterday' : `last active ${d} days ago`;
};

function Bar({ percent, done }: { percent: number; done: boolean }) {
  return (
    <span className="block h-1.5 rounded-full bg-white/10 overflow-hidden" aria-hidden="true">
      <span className={`block h-full rounded-full ${done ? 'bg-emerald-400' : 'bg-amber-300'}`} style={{ width: `${Math.max(3, percent)}%` }} />
    </span>
  );
}

/** Days in the period with any activity, as a strip of small squares. */
function DayStrip({ daily, days, now }: { daily: StudentProgress['daily']; days: number; now: number }) {
  const span = Math.min(days, 30);
  const byDay = new Map(daily.map((d) => [d.day, d.hits]));
  const cells = Array.from({ length: span }, (_, i) => {
    const d = new Date(now - (span - 1 - i) * 86400000).toISOString().slice(0, 10);
    return { d, n: byDay.get(d) ?? 0 };
  });
  return (
    <span className="flex gap-[3px]" role="img" aria-label={`Active on ${cells.filter((c) => c.n).length} of the last ${span} days`}>
      {cells.map((c) => (
        <span key={c.d} title={`${c.d}: ${c.n}`} className={`h-3 w-2 rounded-[2px] ${c.n === 0 ? 'bg-white/8' : c.n < 5 ? 'bg-cyan-400/40' : c.n < 20 ? 'bg-cyan-400/70' : 'bg-cyan-300'}`} />
      ))}
    </span>
  );
}

function StudentCard({ s, days, now }: { s: StudentProgress; days: number; now: number }) {
  const [open, setOpen] = useState(false);
  const started = s.decks.filter((d) => d.status === 'started');
  const talking = [
    ...started.map((d) => `Stopped at slide ${d.furthest} of ${d.slides_total} in "${d.deck}"`),
    ...s.refused.map((r) => `Was refused at ${r.domain} (${r.count}x): looking for something they cannot reach?`),
    ...(s.days_active === 0 ? [`No activity in the last ${days} days`] : []),
  ];
  return (
    <li className="glass rounded-2xl p-4 grid gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[14px] font-semibold">{s.name}</span>
        <span className="text-[12px] text-white/50">{s.email}</span>
        <span className="ml-auto text-[12px] text-white/60">{ago(s.last_seen, now)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <DayStrip daily={s.daily} days={days} now={now} />
        <span className="text-[12px] text-white/60">{s.days_active} active day{s.days_active === 1 ? '' : 's'}</span>
        {s.by_resource.map((r) => (
          <span key={r.resource} className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/75">
            {r.label} <span className="text-white/45 tabular-nums">{r.hits}</span>
          </span>
        ))}
        {s.openwebui.chats_active > 0 && (
          <span className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/75">
            Open WebUI <span className="text-white/45 tabular-nums">{s.openwebui.chats_active} chats</span>
          </span>
        )}
      </div>

      {talking.length > 0 && (
        <div className="rounded-xl bg-amber-300/10 border border-amber-300/25 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wider text-amber-200/80 mb-1">Talking points</div>
          <ul className="list-disc pl-5 m-0 text-[12px] text-white/80 grid gap-0.5">
            {talking.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
      )}

      {s.decks.length > 0 && (
        <div className="grid gap-2">
          <div className="text-[11px] uppercase tracking-wider text-white/45">Decks</div>
          {s.decks.map((d) => (
            <div key={d.deck} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 items-center">
              <span className="text-[12px] truncate">{d.deck}</span>
              <span className="text-[11px] text-white/55 tabular-nums">
                {d.status === 'finished' ? 'finished' : `slide ${d.furthest} of ${d.slides_total}`} · {when(d.last_seen)}
              </span>
              <span className="col-span-2"><Bar percent={d.percent} done={d.status === 'finished'} /></span>
            </div>
          ))}
        </div>
      )}

      <button onClick={() => setOpen(!open)} aria-expanded={open} className="justify-self-start text-[12px] text-cyan-300/80 hover:text-cyan-200">
        {open ? 'Hide details' : 'What they opened'}
      </button>
      {open && (
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-white/45 mb-1">Most opened</div>
            {s.items.length === 0 ? <p className="text-[12px] text-white/50 m-0">Nothing in this period.</p> : (
              <ul className="list-none p-0 m-0 grid gap-1">
                {s.items.map((i) => (
                  <li key={`${i.resource}-${i.label}`} className="text-[12px] grid grid-cols-[6rem_minmax(0,1fr)_auto] gap-2">
                    <span className="text-white/45">{i.resource_label}</span>
                    <span className="truncate">{i.label}</span>
                    <span className="text-white/45 tabular-nums">{i.hits}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="grid gap-3 content-start">
            {s.openwebui.models.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider text-white/45 mb-1">Open WebUI models</div>
                <div className="text-[12px] text-white/75">
                  {s.openwebui.chats_started} new chat{s.openwebui.chats_started === 1 ? '' : 's'} ·{' '}
                  {s.openwebui.models.map((m) => `${m.model} (${m.chats})`).join(', ')}
                </div>
              </div>
            )}
            <div className="text-[12px] text-white/50">Last Authentik sign-in: {when(s.last_login)}</div>
          </div>
        </div>
      )}
    </li>
  );
}

export function StudentProgressView() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<StudentProgress[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(0);

  const load = useCallback(async (d: number) => {
    try { const r = await fetchStudentProgress(d); setNow(Date.now()); setData(r.students); setErr(null); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { const t = setTimeout(() => load(days), 0); return () => clearTimeout(t); }, [days, load]);

  return (
    <section className="grid gap-3" aria-labelledby="prog-h">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="prog-h" className="text-[15px] font-semibold m-0">Progress</h2>
        <div className="glass rounded-full p-1 inline-flex">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setDays(p)} aria-pressed={days === p}
              className={`px-3 py-1 text-[12px] font-semibold rounded-full ${days === p ? 'bg-white/10 text-white' : 'text-white/60'}`}>
              {p === 365 ? '1 year' : `${p} days`}
            </button>
          ))}
        </div>
        <span className="text-[12px] text-white/45">
          What each student opened: Grafana, decks (furthest slide), timeline, threat map, charts, portal, Voices, Open WebUI. Updated hourly.
        </span>
      </div>
      {err && <div className="glass rounded-2xl p-3 text-[13px] text-red-300">{err}</div>}
      {data && data.length === 0 && <div className="glass rounded-2xl p-4 text-[13px] text-white/55">No students yet.</div>}
      <ul className="grid gap-3 list-none p-0 m-0 xl:grid-cols-2">
        {(data ?? []).map((s) => <StudentCard key={s.email} s={s} days={days} now={now} />)}
      </ul>
    </section>
  );
}
