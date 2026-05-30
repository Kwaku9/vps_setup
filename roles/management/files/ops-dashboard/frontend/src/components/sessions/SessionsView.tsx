import { useEffect, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import type { LiveSession } from '../../types';
import { fetchActiveSessions } from '../../api/client';
import { useSessionsSocket } from '../../hooks/useSessionsSocket';
import { SessionCard } from './SessionCard';
import { TranscriptModal } from './TranscriptModal';

export function SessionsView() {
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const { lastUpdate } = useSessionsSocket();

  useEffect(() => {
    let alive = true;
    const load = () => fetchActiveSessions().then((s) => { if (alive) setSessions(s); }).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    if (!lastUpdate) return;
    setSessions((prev) => {
      const idx = prev.findIndex((p) => p.session_uuid === lastUpdate.session_uuid);
      if (lastUpdate.live_status === 'ended') return prev.filter((p) => p.session_uuid !== lastUpdate.session_uuid);
      if (idx === -1) { fetchActiveSessions().then(setSessions).catch(() => {}); return prev; }
      const next = [...prev];
      next[idx] = { ...next[idx], ...lastUpdate } as LiveSession;
      next.sort((a, b) => Number(b.needs_input) - Number(a.needs_input));
      return next;
    });
  }, [lastUpdate]);

  return (
    <div className="mx-auto max-w-7xl w-full px-4 md:px-6 pb-28 lg:pb-6">
      {sessions.length === 0 && (
        <div className="glass rounded-2xl p-8 text-center text-white/50 text-sm">No active sessions</div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <AnimatePresence>
          {sessions.map((s) => <SessionCard key={s.session_uuid} s={s} onOpen={setOpen} />)}
        </AnimatePresence>
      </div>
      <TranscriptModal uuid={open} onClose={() => setOpen(null)} />
    </div>
  );
}
