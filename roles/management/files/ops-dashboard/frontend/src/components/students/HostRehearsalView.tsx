import { useCallback, useEffect, useState } from 'react';
import { fetchHostRehearsal, type HostRehearsal, type HostRehearsalPerson } from '../../api/client';

const PERIODS = [7, 30, 90] as const;
const ROOM_URL = 'https://buildfol.io/command-center?mode=host';

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'never';
const ago = (iso: string | null, now: number) => {
  if (!iso) return 'no practice yet';
  const d = Math.floor((now - new Date(iso).getTime()) / 86400000);
  return d <= 0 ? 'practised today' : d === 1 ? 'practised yesterday' : `last practised ${d} days ago`;
};
const mmss = (s: number | null) => (s == null ? '' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`);
const hm = (minutes: number) => (minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`);

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl bg-white/5 px-3 py-2 min-w-[92px]" title={hint}>
      <div className="text-[18px] font-semibold tabular-nums leading-tight">{value}</div>
      <div className="text-[11px] text-white/50">{label}</div>
    </div>
  );
}

/** Minutes practised per day over the period, as a strip of small squares. */
function DayStrip({ daily, days, now }: { daily: HostRehearsalPerson['daily']; days: number; now: number }) {
  const span = Math.min(days, 30);
  const byDay = new Map(daily.map((d) => [d.day, d]));
  const cells = Array.from({ length: span }, (_, i) => {
    const d = new Date(now - (span - 1 - i) * 86400000).toISOString().slice(0, 10);
    return { d, m: byDay.get(d)?.minutes ?? 0, t: byDay.get(d)?.takes ?? 0 };
  });
  return (
    <span className="flex gap-[3px]" role="img" aria-label={`Practised on ${cells.filter((c) => c.m).length} of the last ${span} days`}>
      {cells.map((c) => (
        <span key={c.d} title={`${c.d}: ${c.m} min, ${c.t} takes`}
          className={`h-3 w-2 rounded-[2px] ${c.m === 0 ? 'bg-white/8' : c.m < 5 ? 'bg-cyan-400/40' : c.m < 20 ? 'bg-cyan-400/70' : 'bg-cyan-300'}`} />
      ))}
    </span>
  );
}

function PersonCard({ p, days, now }: { p: HostRehearsalPerson; days: number; now: number }) {
  const practiced = p.sections.filter((s) => s.practice);
  const untried = practiced.filter((s) => s.takes === 0).map((s) => s.title);
  const long = practiced.filter((s) => s.target_seconds && s.avg_take_seconds && s.avg_take_seconds > s.target_seconds * 1.15);
  const notes = [
    ...(p.briefings_completed === 0 ? [`Has not finished the briefing yet (${p.slides_reached} of ${p.slides_total} slides seen)`] : []),
    ...(untried.length ? [`No takes yet: ${untried.join(', ')}`] : []),
    ...long.map((s) => `${s.title}: takes average ${mmss(s.avg_take_seconds)} against about ${mmss(s.target_seconds)}`),
  ];
  return (
    <li className="glass rounded-2xl p-4 grid gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[14px] font-semibold">{p.name}</span>
        {p.name !== 'Nalah' && <span className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/55">test login</span>}
        <span className="ml-auto text-[12px] text-white/60">{ago(p.last_seen, now)}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        <Stat label="visits" value={p.visits} />
        <Stat label={`day${p.active_days === 1 ? '' : 's'} active`} value={p.active_days} />
        <Stat label="time on page" value={hm(p.minutes)} hint="Counted per visible minute" />
        <Stat label="takes" value={p.takes} />
        <Stat label="re-records" value={p.rerecords} hint="Takes after the first, per section" />
        <Stat label="briefing" value={`${p.slides_reached}/${p.slides_total}`} hint={`Finished ${p.briefings_completed} time(s)`} />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <DayStrip daily={p.daily} days={days} now={now} />
        {p.places.map((pl) => (
          <span key={pl.id} className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/75">
            {pl.title} <span className="text-white/45 tabular-nums">{hm(pl.minutes)}</span>
          </span>
        ))}
        <span className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/75">
          Listened <span className="text-white/45 tabular-nums">{p.listens}</span>
        </span>
        <span className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/75">
          Played own takes <span className="text-white/45 tabular-nums">{p.playbacks}</span>
        </span>
        {p.script_edits > 0 && (
          <span className="text-[11px] px-2 py-0.5 rounded-full border border-white/15 text-white/75">
            Opened the script <span className="text-white/45 tabular-nums">{p.script_edits}</span>
          </span>
        )}
      </div>

      {notes.length > 0 && (
        <div className="rounded-xl bg-amber-300/10 border border-amber-300/25 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wider text-amber-200/80 mb-1">Talking points</div>
          <ul className="list-disc pl-5 m-0 text-[12px] text-white/80 grid gap-0.5">
            {notes.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-[12px] tabular-nums">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-white/45">
              <th className="font-medium py-1 pr-3">Section</th>
              <th className="font-medium py-1 pr-3">Time</th>
              <th className="font-medium py-1 pr-3">Opened</th>
              <th className="font-medium py-1 pr-3">Takes</th>
              <th className="font-medium py-1 pr-3">Re-records</th>
              <th className="font-medium py-1 pr-3">Avg take</th>
              <th className="font-medium py-1 pr-3">Listens</th>
            </tr>
          </thead>
          <tbody>
            {p.sections.map((s) => {
              const over = s.target_seconds && s.avg_take_seconds && s.avg_take_seconds > s.target_seconds * 1.15;
              return (
                <tr key={s.id} className="border-t border-white/8">
                  <td className="py-1.5 pr-3">
                    {s.title}
                    {!s.practice && <span className="ml-2 text-[10px] text-white/40">read</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-white/75">{s.minutes ? hm(s.minutes) : ''}</td>
                  <td className="py-1.5 pr-3 text-white/75">{s.opens || ''}</td>
                  <td className="py-1.5 pr-3">{s.practice ? s.takes : ''}</td>
                  <td className="py-1.5 pr-3">{s.practice ? s.rerecords : ''}</td>
                  <td className={`py-1.5 pr-3 ${over ? 'text-amber-300' : 'text-white/75'}`}>
                    {s.avg_take_seconds != null ? mmss(s.avg_take_seconds) : ''}
                    {s.target_seconds && s.practice ? <span className="text-white/35"> / {mmss(s.target_seconds)}</span> : ''}
                  </td>
                  <td className="py-1.5 pr-3 text-white/75">{s.listens || ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {p.visits_recent.length > 0 && (
        <details className="text-[12px]">
          <summary className="cursor-pointer text-white/60">Recent visits ({p.visits_recent.length})</summary>
          <ul className="list-none p-0 m-0 mt-2 grid gap-1">
            {p.visits_recent.map((v) => (
              <li key={v.at} className="flex flex-wrap gap-x-3 text-white/70">
                <span className="tabular-nums">{when(v.at)}</span>
                <span>{[v.device, v.os, v.browser].filter(Boolean).join(' · ')}</span>
                {v.city && <span className="text-white/45">{v.city}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="text-[12px] text-white/50">First practice: {when(p.first_seen)}</div>
    </li>
  );
}

export function HostRehearsalView() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<HostRehearsal | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(0);

  const load = useCallback(async (d: number) => {
    try { const r = await fetchHostRehearsal(d); setNow(Date.now()); setData(r); setErr(null); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { const t = setTimeout(() => load(days), 0); return () => clearTimeout(t); }, [days, load]);

  return (
    <section className="grid gap-3" aria-labelledby="rehearsal-h">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="rehearsal-h" className="text-[15px] font-semibold m-0">Host rehearsal</h2>
        <div className="glass rounded-full p-1 inline-flex">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setDays(p)} aria-pressed={days === p}
              className={`px-3 py-1 text-[12px] font-semibold rounded-full ${days === p ? 'bg-white/10 text-white' : 'text-white/60'}`}>
              {p} days
            </button>
          ))}
        </div>
        <span className="text-[12px] text-white/45">
          Practice in the <a className="underline hover:text-white/80" href={ROOM_URL} target="_blank" rel="noreferrer">Command Center rehearsal room</a>.
          Activity only; recordings stay on her device. Counted from the 14 Nov reset. Refreshes each minute.
        </span>
      </div>
      {err && <div className="glass rounded-2xl p-3 text-[13px] text-red-300">{err}</div>}
      {data && !data.configured && (
        <div className="glass rounded-2xl p-4 text-[13px] text-white/55">
          Not connected: the PostHog key (buildfolio_posthog_personal_api_key) is missing from the container.
        </div>
      )}
      {data && data.configured && data.hosts.length === 0 && (
        <div className="glass rounded-2xl p-4 text-[13px] text-white/55">No practice in the last {days} days.</div>
      )}
      <ul className="grid gap-3 list-none p-0 m-0 xl:grid-cols-2">
        {(data?.hosts ?? []).map((p) => <PersonCard key={p.name} p={p} days={days} now={now} />)}
      </ul>
      {data && data.gate_denied > 0 && (
        <div className="text-[12px] text-white/50">Wrong-name attempts at the rehearsal room: {data.gate_denied}</div>
      )}
    </section>
  );
}
