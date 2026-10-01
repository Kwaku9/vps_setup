import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { SearchHit, SearchResponse, SessionGraph, SessionTranscript, TimelineHealth } from '../../types';
import { fileSessions, searchSessions, sessionGraph, sessionTranscriptExcerpt, similarSessions, timelineHealth } from '../../api/client';

const TIMELINE_URL = 'https://timeline.aicortex.cloud';

const EXAMPLES = [
  'why did the tailscale exit node break DNS',
  'what did we decide about the LiteLLM embedding fallback',
  'neo4j ETL OOM kill',
  'how the buildfolio chat widget reaches the timeline graph',
];

function scoreBar(score: number) {
  return Math.max(4, Math.min(100, Math.round(((score || 0) - 0.4) / 0.6 * 100)));
}

function HitCard({ h, onOpen, showScore = true }: { h: SearchHit; onOpen: (uuid: string) => void; showScore?: boolean }) {
  return (
    <button onClick={() => onOpen(h.session_uuid)}
      className="glass rounded-2xl p-3 text-left w-full grid grid-cols-[6px_minmax(0,1fr)_auto] gap-3 items-start hover:bg-white/8 transition">
      <span className="relative self-stretch rounded bg-white/10 overflow-hidden">
        <span className="absolute left-0 right-0 bottom-0 bg-gradient-to-t from-cyan-400 to-blue-500" style={{ height: `${scoreBar(h.score)}%` }} />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold leading-snug">{h.title || '(untitled)'}</span>
        <span className="block mt-0.5 text-[11px] text-white/45 flex flex-wrap gap-x-2">
          {h.pillar_id && <span className="text-cyan-300/80">{h.pillar_id}</span>}
          {h.project && <span>{h.project}</span>}
          {h.date && <span>{String(h.date).slice(0, 10)}</span>}
          {h.source === 'codex' && <span className="text-emerald-300">codex</span>}
          {h.messages != null && <span>{h.messages} msgs</span>}
        </span>
        {h.snippet && (
          <span className="block mt-1.5 text-[11px] text-white/60 font-mono whitespace-pre-wrap line-clamp-3">{h.snippet}</span>
        )}
      </span>
      {showScore ? <span className="text-[12px] font-bold text-cyan-300 tabular-nums">{(h.score || 0).toFixed(2)}</span> : <span />}
    </button>
  );
}

function SessionDrawer({ uuid, onClose, onOpen }: { uuid: string | null; onClose: () => void; onOpen: (u: string) => void }) {
  const [graph, setGraph] = useState<SessionGraph | null>(null);
  const [graphErr, setGraphErr] = useState<string | null>(null);
  const [similar, setSimilar] = useState<SearchHit[] | null>(null);
  const [transcript, setTranscript] = useState<SessionTranscript | null>(null);
  const [showTurns, setShowTurns] = useState(false);
  const [fileHits, setFileHits] = useState<Record<string, { session_uuid: string; title: string; date: string | null; touches: number }[]>>({});

  useEffect(() => {
    setGraph(null); setGraphErr(null); setSimilar(null); setTranscript(null); setShowTurns(false); setFileHits({});
    if (!uuid) return;
    let alive = true;
    sessionGraph(uuid).then((g) => { if (alive) setGraph(g); }).catch((e) => { if (alive) setGraphErr(e.message); });
    similarSessions(uuid).then((r) => { if (alive) setSimilar(r.hits || []); }).catch(() => { if (alive) setSimilar([]); });
    sessionTranscriptExcerpt(uuid, 8000).then((t) => { if (alive) setTranscript(t); }).catch(() => {});
    return () => { alive = false; };
  }, [uuid]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const lookupFile = async (path: string) => {
    if (fileHits[path]) { setFileHits((f) => { const n = { ...f }; delete n[path]; return n; }); return; }
    try {
      const r = await fileSessions(path);
      setFileHits((f) => ({ ...f, [path]: r.sessions.filter((s) => s.session_uuid !== uuid) }));
    } catch { setFileHits((f) => ({ ...f, [path]: [] })); }
  };

  const H = ({ children }: { children: React.ReactNode }) => (
    <div className="text-[10px] uppercase tracking-[0.12em] text-white/45 font-semibold mb-2">{children}</div>
  );

  return (
    <AnimatePresence>
      {uuid && (
        <motion.div className="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center p-0 sm:p-6"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div className="glass glass-lg w-full sm:max-w-3xl max-h-[88vh] rounded-t-3xl sm:rounded-3xl p-5 overflow-y-auto"
            initial={{ y: 40 }} animate={{ y: 0 }} exit={{ y: 40 }} onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start gap-3 mb-3">
              <div className="min-w-0">
                <div className="text-[11px] text-white/45 flex flex-wrap gap-x-2">
                  {transcript?.pillar_id && <span className="text-cyan-300/80">{transcript.pillar_id}</span>}
                  {(transcript?.project || graph?.project) && <span>{transcript?.project || graph?.project}</span>}
                  {transcript?.date && <span>{transcript.date}</span>}
                  {graph?.branch && <span className="font-mono">⌥ {graph.branch}</span>}
                  {transcript?.source === 'codex' && <span className="text-emerald-300">codex</span>}
                </div>
                <div className="text-[15px] font-semibold leading-snug mt-0.5">{transcript?.title || graph?.title || uuid}</div>
              </div>
              <div className="flex gap-2 shrink-0">
                <a href={`${TIMELINE_URL}/#/session/${uuid}`} target="_blank" rel="noopener" className="glass rounded-full px-3 py-1.5 text-[11px] font-semibold text-cyan-300">Open in timeline ↗</a>
                <button onClick={onClose} className="glass rounded-full px-3 py-1.5 text-[11px] text-white/60">Close</button>
              </div>
            </div>

            {transcript?.paragraph && (
              <div className="rounded-xl bg-white/5 border-l-2 border-cyan-400/60 p-3 text-[12.5px] text-white/75 leading-relaxed mb-4">{transcript.paragraph}</div>
            )}

            <div className="grid sm:grid-cols-2 gap-4">
              <section>
                <H>Graph context <span className="normal-case tracking-normal text-cyan-300/80 ml-1">live · Neo4j</span></H>
                {graphErr && <div className="text-[12px] text-white/40 italic">unavailable ({graphErr})</div>}
                {!graph && !graphErr && <div className="text-[12px] text-white/40 italic">querying…</div>}
                {graph && (
                  <div className="space-y-2 text-[12px]">
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-white/60">
                      {graph.subagents > 0 && <span><b className="text-white">{graph.subagents}</b> subagents</span>}
                      {graph.tool_calls != null && <span><b className="text-white">{graph.tool_calls}</b> tool calls</span>}
                      {graph.models.length > 0 && <span>{graph.models.join(', ')}</span>}
                    </div>
                    {graph.commits.length > 0 && (
                      <div className="space-y-1">
                        {graph.commits.slice(0, 8).map((c) => (
                          <div key={c.sha} className="grid grid-cols-[auto_minmax(0,1fr)_auto] gap-2 items-center rounded-lg bg-white/5 px-2 py-1">
                            <span className="font-mono text-cyan-300">{c.sha}</span>
                            <span className="truncate text-white/80" title={c.message}>{c.message}</span>
                            <span className="text-white/40 text-[11px]">{String(c.date || '').slice(0, 10)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {graph.shared_file_sessions.length > 0 && (
                      <div>
                        <div className="text-[11px] text-white/40 mb-1">Sessions sharing files with this one</div>
                        <div className="space-y-1">
                          {graph.shared_file_sessions.map((n) => (
                            <button key={n.session_uuid} onClick={() => onOpen(n.session_uuid)} title={(n.sample || []).join('\n')}
                              className="w-full text-left rounded-lg bg-white/5 hover:bg-white/10 px-2 py-1 grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2 items-center">
                              <span className="truncate">{n.title || n.session_uuid}</span>
                              <span className="text-[10px] font-semibold text-cyan-300 bg-cyan-400/10 rounded px-1.5">{n.shared} shared</span>
                              <span className="text-white/40 text-[11px]">{String(n.date || '').slice(0, 10)}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {graph.files.length > 0 && (
                      <div>
                        <div className="text-[11px] text-white/40 mb-1">Files touched · click for every session that touched it</div>
                        <div className="space-y-1">
                          {graph.files.slice(0, 10).map((f) => (
                            <div key={f.path}>
                              <button onClick={() => lookupFile(f.path)} className="w-full text-left rounded-lg bg-white/5 hover:bg-white/10 px-2 py-1 flex justify-between gap-2 font-mono text-[11px]">
                                <span className="truncate">{f.path.replace(/^.*?(vps_setup|VScdeProjects|vscode-projects)\//, '')}</span>
                                <span className="text-cyan-300 shrink-0">{f.touches}×</span>
                              </button>
                              {fileHits[f.path] && (
                                <div className="ml-3 mt-1 pl-2 border-l border-cyan-400/30 space-y-1">
                                  {fileHits[f.path].length === 0 && <div className="text-[11px] text-white/40 italic">no other session touched this file</div>}
                                  {fileHits[f.path].map((s) => (
                                    <button key={s.session_uuid} onClick={() => onOpen(s.session_uuid)} className="w-full text-left text-[11px] rounded bg-white/5 hover:bg-white/10 px-2 py-1 flex justify-between gap-2">
                                      <span className="truncate">{s.title || s.session_uuid}</span>
                                      <span className="text-white/40 shrink-0">{String(s.date || '').slice(0, 10)}</span>
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </section>

              <section>
                <H>Similar by meaning <span className="normal-case tracking-normal text-cyan-300/80 ml-1">live · pgvector</span></H>
                {similar === null && <div className="text-[12px] text-white/40 italic">comparing embeddings…</div>}
                {similar && similar.length === 0 && <div className="text-[12px] text-white/40 italic">no embedded chunks for this session yet</div>}
                <div className="space-y-2">
                  {(similar || []).map((h) => <HitCard key={h.session_uuid} h={h} onOpen={onOpen} />)}
                </div>
              </section>
            </div>

            <section className="mt-4">
              <H>Transcript excerpt {transcript && <span className="normal-case tracking-normal text-white/40 ml-1">{transcript.turns.length} turns · secrets redacted</span>}</H>
              {!transcript && <div className="text-[12px] text-white/40 italic">loading…</div>}
              {transcript && !showTurns && (
                <button onClick={() => setShowTurns(true)} className="glass rounded-full px-3 py-1.5 text-[12px] font-semibold">Show {transcript.turns.length} turns</button>
              )}
              {transcript && showTurns && (
                <div className="space-y-2">
                  {transcript.turns.map((t, i) => (
                    <div key={i} className={`rounded-xl p-2.5 text-[12px] whitespace-pre-wrap break-words ${t.role === 'user' ? 'bg-white/8' : 'bg-white/[0.03]'}`}>
                      <span className={`block text-[10px] uppercase tracking-wider font-bold mb-1 ${t.role === 'user' ? 'text-sky-300' : 'text-emerald-300'}`}>{t.role}</span>
                      {t.text}{t.truncated ? ' …' : ''}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function SearchView() {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [health, setHealth] = useState<TimelineHealth | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => { timelineHealth().then(setHealth).catch(() => setHealth({ status: 'down', postgres: false, neo4j: false, embedder: false })); }, []);

  const run = useCallback(async (query: string) => {
    const qq = query.trim();
    if (qq.length < 2) return;
    setBusy(true); setErr(null);
    try { setRes(await searchSessions(qq, 15)); }
    catch (e) { setErr((e as Error).message); setRes(null); }
    finally { setBusy(false); }
  }, []);

  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pb-28 lg:pb-6 flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-[15px] font-semibold tracking-tight mr-1">Session Search</div>
        <span className={`glass px-3 py-1 rounded-full text-[11px] font-medium flex items-center gap-2 ${health?.status === 'ok' ? 'text-emerald-300' : 'text-amber-300'}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${health?.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'}`} />
          {!health ? 'checking…' : health.status === 'ok'
            ? `${(health.recall_chunks || 0).toLocaleString()} embedded chunks · ${(health.sessions_in_graph || 0).toLocaleString()} sessions in graph`
            : `degraded: ${health.postgres ? '' : 'postgres '}${health.neo4j ? '' : 'neo4j '}${health.embedder ? '' : 'embedder'}`}
        </span>
        <a href={TIMELINE_URL} target="_blank" rel="noopener" className="ml-auto text-[11px] text-cyan-300 hover:underline">timeline.aicortex.cloud ↗</a>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); run(q); }} className="glass rounded-2xl p-2 flex items-center gap-2">
        <span className="text-white/40 pl-2">🔍</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask across every Claude Code and Codex session by meaning…"
          className="flex-1 bg-transparent outline-none text-[14px] py-2 min-w-0" autoFocus />
        <button type="submit" disabled={busy || q.trim().length < 2}
          className="rounded-full px-4 py-2 text-[12px] font-bold bg-gradient-to-r from-cyan-400 to-blue-600 text-white disabled:opacity-40">
          {busy ? 'Searching…' : 'Ask'}
        </button>
      </form>

      {!res && !busy && !err && (
        <div className="text-[12px] text-white/50 flex flex-wrap gap-2 items-center">
          <span>Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => { setQ(ex); run(ex); }} className="glass rounded-full px-3 py-1 hover:text-white">{ex}</button>
          ))}
        </div>
      )}
      {err && <div className="glass rounded-2xl p-4 text-rose-300 text-sm">Search unavailable: {err}</div>}
      {busy && <div className="glass rounded-2xl p-4 text-white/60 text-sm">Embedding “{q}” and scanning every session transcript…</div>}
      {res && !busy && (
        <>
          <div className="text-[11px] text-white/45">
            {res.hits.length} sessions by meaning · embedded in {res.timing_ms.embed} ms, searched in {res.timing_ms.search} ms
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {res.hits.map((h) => <HitCard key={h.session_uuid} h={h} onOpen={setOpen} />)}
          </div>
          {res.hits.length === 0 && <div className="glass rounded-2xl p-6 text-white/50 text-sm">No matches. This searches meaning, not keywords, so try different wording.</div>}
        </>
      )}

      <SessionDrawer uuid={open} onClose={() => setOpen(null)} onOpen={setOpen} />
    </div>
  );
}
