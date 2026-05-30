import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { TranscriptMessage } from '../../types';
import { fetchTranscript } from '../../api/client';

export function TranscriptModal({ uuid, onClose }: { uuid: string | null; onClose: () => void }) {
  const [msgs, setMsgs] = useState<TranscriptMessage[]>([]);
  const sinceRef = useRef(0);

  useEffect(() => {
    if (!uuid) { setMsgs([]); sinceRef.current = 0; return; }
    let alive = true;
    const tick = () => fetchTranscript(uuid, sinceRef.current).then((rows) => {
      if (!alive || rows.length === 0) return;
      sinceRef.current = rows[rows.length - 1].sequence_num;
      setMsgs((prev) => [...prev, ...rows]);
    }).catch(() => {});
    tick();
    const t = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [uuid]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <AnimatePresence>
      {uuid && (
        <motion.div
          className="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center p-0 sm:p-6"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="glass w-full sm:max-w-2xl max-h-[80vh] rounded-t-3xl sm:rounded-3xl p-4 overflow-y-auto"
            initial={{ y: 40 }} animate={{ y: 0 }} exit={{ y: 40 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-3">
              <span className="text-sm font-semibold">Live transcript</span>
              <button onClick={onClose} className="text-white/50 text-sm">Close</button>
            </div>
            <div className="space-y-2">
              {msgs.map((m) => (
                <div key={m.uuid} className="text-[12px]">
                  <span className={m.role === 'user' ? 'text-sky-300' : 'text-emerald-300'}>{m.role}</span>
                  <div className="text-white/70 whitespace-pre-wrap break-words">{m.content_text}</div>
                </div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
