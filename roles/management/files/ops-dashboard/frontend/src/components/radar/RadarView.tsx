import { useEffect, useMemo, useState } from 'react';
import type { RadarRepo, RadarSnapshot, RadarState } from '../../types';
import { fetchRadarState, rescanRadarVps } from '../../api/client';
import { StatTile } from '../overview/StatTile';

type Filter = 'attention' | 'all';

function needsAttention(r: RadarRepo, prs: number) {
  return r.dirty > 0 || r.ahead > 0 || r.behind > 0 || !!r.detached || !!r.unborn || !!r.error || prs > 0 || !r.upstream
    || !!r.diverged || (r.unmerged ?? 0) > 0 || (r.unrelated ?? 0) > 0;
}
function defShort(r: RadarRepo) {
  return (r.defaultBranch || '').replace(/^origin\//, '');
}
function stripe(r: RadarRepo) {
  if (r.error || r.dirty > 0) return 'border-l-rose-400';
  if (r.diverged) return 'border-l-fuchsia-400';
  if (r.detached || r.unborn) return 'border-l-violet-400';
  if (r.ahead > 0 || r.behind > 0 || (r.unmerged ?? 0) > 0) return 'border-l-amber-400';
  return 'border-l-white/10';
}
function rank(r: RadarRepo) {
  if (r.error) return 0;
  if (r.dirty) return 1;
  if (r.diverged) return 2;
  if (r.detached || r.unborn) return 3;
  if (r.ahead || r.behind) return 4;
  if ((r.unmerged ?? 0) > 0) return 5;
  if ((r.unrelated ?? 0) > 0) return 6;
  return 7;
}
function ago(iso?: string | null) {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const Pill = ({ tone, children }: { tone: 'branch' | 'clean' | 'dirty' | 'ahead' | 'detached' | 'pr' | 'muted' | 'diverged' | 'prunable'; children: React.ReactNode }) => {
  const cls: Record<string, string> = {
    branch: 'bg-white/8 text-white/70 border border-white/10',
    clean: 'bg-emerald-400/15 text-emerald-300',
    dirty: 'bg-rose-400/15 text-rose-300',
    ahead: 'bg-amber-400/15 text-amber-300',
    detached: 'bg-violet-400/15 text-violet-300',
    pr: 'bg-cyan-400/15 text-cyan-300',
    muted: 'text-white/40 border border-dashed border-white/15',
    diverged: 'bg-fuchsia-400/15 text-fuchsia-300',
    prunable: 'bg-emerald-400/10 text-emerald-300/80 border border-emerald-400/20',
  };
  return <span className={`font-mono text-[11px] px-1.5 py-px rounded whitespace-nowrap tabular-nums ${cls[tone]}`}>{children}</span>;
};

/**
 * Two-sided bar for one branch against the default branch: commits the default
 * branch has that this one lacks grow left of the centre line, commits only
 * this branch has grow right. Both sides are scaled against the widest branch
 * in the SAME repository, so a row reads as a shape — merged branches sit flat
 * on the line, a diverged branch pushes out both ways.
 */
const DivergenceBar = ({ ahead, behind, scale }: { ahead: number; behind: number; scale: number }) => {
  // A non-zero count always gets a visible sliver, so "1 commit" never renders
  // as nothing next to a branch that is 500 ahead.
  const pct = (n: number) => (n <= 0 ? 0 : Math.max(5, Math.round((n / scale) * 50)));
  return (
    <span className="inline-flex w-24 shrink-0" title={`${behind} behind · ${ahead} ahead of the default branch`}>
      <span className="relative flex w-full h-1.5 rounded bg-white/[0.07]">
        <span className="absolute left-1/2 -top-1 h-3.5 w-px bg-white/25" />
        <span className="absolute right-1/2 h-1.5 rounded-l bg-sky-400/70" style={{ width: `${pct(behind)}%` }} />
        <span className="absolute left-1/2 h-1.5 rounded-r bg-amber-400/80" style={{ width: `${pct(ahead)}%` }} />
      </span>
    </span>
  );
};

function RepoRow({ r, prs, open }: { r: RadarRepo; prs: RadarSnapshot['prs']; open: boolean }) {
  const list = prs[r.name] || [];
  const scale = Math.max(
    1,
    ...(r.branches || []).map((b) => Math.max(b.vsDefault?.ahead ?? 0, b.vsDefault?.behind ?? 0)),
  );
  return (
    <details open={open} className={`border-b border-white/5 last:border-b-0 border-l-[3px] ${stripe(r)}`}>
      <summary className="list-none cursor-pointer px-3 py-2 grid grid-cols-[1fr_auto] gap-3 items-center hover:bg-white/5">
        <span className="flex items-center gap-2 flex-wrap min-w-0">
          <span className="font-mono font-semibold text-[13px]">{r.name}</span>
          <Pill tone="branch">{r.detached ? 'detached' : r.head || '?'}</Pill>
          {r.unborn && <Pill tone="detached">no commits</Pill>}
          {r.error && <Pill tone="dirty">{r.error}</Pill>}
          {r.staged > 0 && <Pill tone="dirty">{r.staged} staged</Pill>}
          {r.modified > 0 && <Pill tone="dirty">{r.modified} modified</Pill>}
          {r.untracked > 0 && <Pill tone="dirty">{r.untracked} untracked</Pill>}
          {r.conflicted > 0 && <Pill tone="dirty">{r.conflicted} conflicted</Pill>}
          {!r.dirty && !r.error && !r.unborn && <Pill tone="clean">clean</Pill>}
          {r.headVsDefault && r.head && r.head !== defShort(r) && (r.headVsDefault.ahead > 0 || r.headVsDefault.behind > 0) && (
            <Pill tone={r.diverged ? 'diverged' : 'ahead'}>
              {r.diverged ? 'diverged' : 'unmerged'}{' '}
              {r.headVsDefault.behind > 0 ? `↓${r.headVsDefault.behind}` : ''}{r.headVsDefault.ahead > 0 ? ` ↑${r.headVsDefault.ahead}` : ''} vs {defShort(r)}
            </Pill>
          )}
          {(r.unmerged ?? 0) > 0 && <Pill tone="ahead">{r.unmerged} unmerged branch{(r.unmerged ?? 0) > 1 ? 'es' : ''}</Pill>}
          {(r.prunable ?? 0) > 0 && <Pill tone="prunable">{r.prunable} prunable</Pill>}
          {(r.unrelated ?? 0) > 0 && <Pill tone="detached">unrelated history</Pill>}
          {r.ahead > 0 && <Pill tone="ahead">↑{r.ahead} unpushed</Pill>}
          {r.behind > 0 && <Pill tone="ahead">↓{r.behind} behind</Pill>}
          {!r.upstream && !r.detached && !r.unborn && <Pill tone="muted">no upstream</Pill>}
          {(r.stashes ?? 0) > 0 && <Pill tone="muted">{r.stashes} stashed</Pill>}
          {list.length > 0 && <Pill tone="pr">{list.length} open PR{list.length > 1 ? 's' : ''}</Pill>}
        </span>
        <span className="font-mono text-[11px] text-white/40 whitespace-nowrap text-right">
          {r.last ? `${r.last.hash} · ${r.last.rel}` : '—'}
        </span>
      </summary>
      <div className="px-3 pb-3 bg-white/[0.03]">
        {r.branches && r.branches.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px] border-collapse">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-white/40">
                  <th className="text-left font-semibold px-2 py-1.5 border-b border-white/10">Branch</th>
                  <th className="text-left font-semibold px-2 py-1.5 border-b border-white/10">Upstream</th>
                  <th className="text-left font-semibold px-2 py-1.5 border-b border-white/10">Position</th>
                  <th className="text-left font-semibold px-2 py-1.5 border-b border-white/10">vs {defShort(r) || 'default'}</th>
                  <th className="text-left font-semibold px-2 py-1.5 border-b border-white/10">Last commit</th>
                  <th className="text-left font-semibold px-2 py-1.5 border-b border-white/10">Subject</th>
                </tr>
              </thead>
              <tbody>
                {r.branches.map((b) => (
                  <tr key={b.name} className="border-b border-white/5 last:border-b-0 align-top">
                    <td className="px-2 py-1 font-mono whitespace-nowrap">{b.name === r.head ? '● ' : ''}{b.name}</td>
                    <td className="px-2 py-1 font-mono whitespace-nowrap text-white/60">{b.upstream || '—'}</td>
                    <td className="px-2 py-1">
                      {b.gone ? <Pill tone="detached">upstream gone</Pill>
                        : !b.upstream ? <Pill tone="muted">no upstream</Pill>
                        : (b.ahead || b.behind) ? <Pill tone="ahead">{b.ahead ? `↑${b.ahead}` : ''}{b.behind ? ` ↓${b.behind}` : ''}</Pill>
                        : <Pill tone="clean">in sync</Pill>}
                    </td>
                    <td className="px-2 py-1 whitespace-nowrap">
                      {!b.vsDefault ? <span className="text-white/30">—</span>
                        : b.vsDefault.unrelated ? <Pill tone="detached">unrelated</Pill>
                        : b.name === defShort(r) ? <span className="text-white/30">default</span>
                        : b.vsDefault.ahead === 0 && b.vsDefault.behind === 0 ? <Pill tone="prunable">merged</Pill>
                        : (
                          <span className="flex items-center gap-2">
                            <DivergenceBar ahead={b.vsDefault.ahead} behind={b.vsDefault.behind} scale={scale} />
                            <span className="font-mono text-[11px] text-white/55 tabular-nums">
                              {b.vsDefault.behind > 0 ? `↓${b.vsDefault.behind}` : ''}{b.vsDefault.ahead > 0 ? ` ↑${b.vsDefault.ahead}` : ''}
                            </span>
                          </span>
                        )}
                    </td>
                    <td className="px-2 py-1 font-mono whitespace-nowrap text-white/60">{b.when ? new Date(b.when * 1000).toISOString().slice(0, 10) : ''}</td>
                    <td className="px-2 py-1 text-white/70">{b.subject}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-[12px] text-white/40 py-2">No local branches.</p>}
        {list.length > 0 && (
          <div className="mt-2 space-y-1">
            {list.map((pr) => (
              <div key={pr.number} className="text-[12px]">
                <a href={pr.url} target="_blank" rel="noopener" className="text-cyan-300 hover:underline">#{pr.number} {pr.title}</a>
                {pr.draft && <span className="ml-2"><Pill tone="muted">draft</Pill></span>}
                <span className="ml-2"><Pill tone="muted">{pr.author}</Pill></span>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}

export function RadarView() {
  const [state, setState] = useState<RadarState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [host, setHost] = useState<string>('laptop');
  const [filter, setFilter] = useState<Filter>('attention');
  const [q, setQ] = useState('');
  const [expandAll, setExpandAll] = useState(false);
  const [rescanning, setRescanning] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => fetchRadarState().then((s) => { if (alive) { setState(s); setError(null); } }).catch((e) => { if (alive) setError(e.message); });
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const hosts = useMemo(() => Object.keys(state?.hosts || {}).sort(), [state]);
  useEffect(() => { if (hosts.length && !hosts.includes(host)) setHost(hosts[0]); }, [hosts, host]);
  const snap = state?.hosts?.[host];

  const stats = useMemo(() => {
    const repos = snap?.repos || [];
    const prs = snap?.prs || {};
    const dirty = repos.filter((r) => r.dirty > 0).length;
    const ahead = repos.filter((r) => r.ahead > 0).length;
    const behind = repos.filter((r) => r.behind > 0).length;
    const noUp = repos.filter((r) => !r.upstream && !r.detached && !r.unborn).length;
    const odd = repos.filter((r) => r.detached || r.unborn || r.error).length;
    const prCount = Object.values(prs).reduce((n, a) => n + a.length, 0);
    const off = repos.reduce((n, r) => n + (r.branches || []).filter((b) => b.upstream && !b.gone && (b.ahead || b.behind)).length, 0);
    const gone = repos.reduce((n, r) => n + (r.branches || []).filter((b) => b.gone).length, 0);
    // Branch topology, aggregated: `diverged` counts repositories needing a
    // real merge; the other two count branches, not repositories.
    const diverged = repos.filter((r) => r.diverged).length;
    const unmergedBranches = repos.reduce((n, r) => n + (r.unmerged ?? 0), 0);
    const prunableBranches = repos.reduce((n, r) => n + (r.prunable ?? 0), 0);
    return { total: repos.length, dirty, ahead, behind, noUp, odd, prCount, off, gone, diverged, unmergedBranches, prunableBranches };
  }, [snap]);

  const list = useMemo(() => {
    const repos = snap?.repos || [];
    const prs = snap?.prs || {};
    let l = repos;
    if (filter === 'attention') l = l.filter((r) => needsAttention(r, (prs[r.name] || []).length));
    const qq = q.trim().toLowerCase();
    if (qq) l = l.filter((r) => r.name.toLowerCase().includes(qq) || (r.head || '').toLowerCase().includes(qq));
    return [...l].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }, [snap, filter, q]);

  const rescan = async () => {
    setRescanning(true);
    try { await rescanRadarVps(); const s = await fetchRadarState(); setState(s); } catch { /* shown by poll */ }
    setRescanning(false);
  };

  const seg = 'px-3 py-1 text-[12px] font-semibold rounded-full';
  const on = 'bg-white/15 text-white';
  const off = 'text-white/55 hover:text-white';

  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pb-28 lg:pb-6 flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-[15px] font-semibold tracking-tight mr-1">Repo Radar</div>
        <div className="glass rounded-full p-1 inline-flex">
          {hosts.length === 0 && <span className={`${seg} text-white/40`}>no snapshots yet</span>}
          {hosts.map((h) => (
            <button key={h} onClick={() => setHost(h)} className={`${seg} ${host === h ? on : off}`}>{h}</button>
          ))}
        </div>
        {snap && (
          <span className="text-[11px] text-white/45 font-mono truncate">
            {snap.root} · scanned {ago(snap.scannedAt)}{snap.scanMs != null ? ` in ${snap.scanMs} ms` : ''} · received {ago(snap.receivedAt)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="filter repos…"
            className="glass rounded-full px-3 py-1.5 text-[12px] font-mono outline-none focus:ring-2 ring-cyan-400/40 w-44" />
          <div className="glass rounded-full p-1 inline-flex">
            <button onClick={() => setFilter('attention')} className={`${seg} ${filter === 'attention' ? on : off}`}>Needs attention</button>
            <button onClick={() => setFilter('all')} className={`${seg} ${filter === 'all' ? on : off}`}>All</button>
          </div>
          <button onClick={() => setExpandAll((v) => !v)} className="glass rounded-full px-3 py-1.5 text-[12px] font-semibold">{expandAll ? 'Collapse all' : 'Expand all'}</button>
          {host === 'vps' && (
            <button onClick={rescan} disabled={rescanning} className="glass rounded-full px-3 py-1.5 text-[12px] font-semibold disabled:opacity-50">{rescanning ? 'Scanning…' : 'Rescan VPS'}</button>
          )}
        </div>
      </div>

      {error && <div className="glass rounded-2xl p-4 text-rose-300 text-sm">Repo Radar unavailable: {error}</div>}

      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <StatTile label="Repos" value={stats.total} />
        <StatTile label="Uncommitted" value={stats.dirty} accent={stats.dirty ? 'var(--status-red)' : undefined} />
        <StatTile label="Unpushed" value={stats.ahead} accent={stats.ahead ? 'var(--status-orange)' : undefined} sub="HEAD" />
        <StatTile label="Behind" value={stats.behind} accent={stats.behind ? 'var(--status-orange)' : undefined} sub="HEAD" />
        <StatTile label="Diverged" value={stats.diverged} accent={stats.diverged ? 'var(--status-red)' : undefined} sub="needs a merge" />
        <StatTile label="Unmerged" value={stats.unmergedBranches} accent={stats.unmergedBranches ? 'var(--status-orange)' : undefined} sub="branches vs default" />
        <StatTile label="Prunable" value={stats.prunableBranches} sub="branches, fully merged" />
        <StatTile label="No upstream" value={stats.noUp} />
        <StatTile label="Detached" value={stats.odd} accent={stats.odd ? 'var(--status-red)' : undefined} sub="or unborn" />
        <StatTile label="Branches off" value={stats.off} accent={stats.off ? 'var(--status-orange)' : undefined} sub="every branch" />
        <StatTile label="Upstream gone" value={stats.gone} accent={stats.gone ? 'var(--status-red)' : undefined} />
        <StatTile label="Open PRs" value={stats.prCount} accent={stats.prCount ? 'var(--vps-cyan)' : undefined} />
      </div>

      <div className="glass rounded-2xl overflow-hidden">
        {!snap ? (
          <p className="p-6 text-sm text-white/50">
            No snapshot for this host yet. The laptop scans hourly and pushes every 5 minutes (repo-radar-push.timer); the VPS scans itself every 300s.
          </p>
        ) : list.length === 0 ? (
          <p className="p-6 text-sm text-white/50">Nothing matches.{filter === 'attention' ? ' Every repository is clean, synced and has an upstream.' : ''}</p>
        ) : (
          list.map((r) => <RepoRow key={r.name} r={r} prs={snap.prs || {}} open={expandAll} />)
        )}
      </div>
      {snap && (
        <p className="text-[11px] text-white/40">
          {snap.prError ? `Pull requests: ${snap.prError}` : ''}
          {snap.fatal ? ` · scan error: ${snap.fatal}` : ''}
        </p>
      )}
    </div>
  );
}
