import { motion } from 'framer-motion';
import type { LiveSession } from '../../types';
import { ApprovalControls } from './ApprovalControls';

const STATUS_COLOR: Record<string, string> = {
  running: 'bg-emerald-400',
  waiting_input: 'bg-amber-400',
  idle: 'bg-white/30',
  ended: 'bg-white/20',
};

export function SessionCard({ s, onOpen }: { s: LiveSession; onOpen: (uuid: string) => void }) {
  const tokens = (s.input_tokens ?? 0) + (s.output_tokens ?? 0);
  return (
    <motion.button
      layout
      onClick={() => onOpen(s.session_uuid)}
      className="glass rounded-2xl p-4 text-left w-full relative overflow-hidden"
    >
      {s.needs_input && !s.needs_approval && (
        <motion.span
          className="absolute right-3 top-3 text-[10px] font-bold text-amber-300"
          animate={{ opacity: [1, 0.3, 1] }}
          transition={{ repeat: Infinity, duration: 1.4 }}
        >
          NEEDS INPUT
        </motion.span>
      )}
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${STATUS_COLOR[s.live_status] ?? 'bg-white/30'}`} />
        <span className="font-semibold text-sm truncate">{s.project ?? 'unknown'}</span>
      </div>
      <div className="mt-1 text-[12px] text-white/60 truncate">{s.current_stage ?? s.live_status}</div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-white/40">
        {s.host && <span>{s.host}</span>}
        {s.git_branch && <span>⌥ {s.git_branch}</span>}
        {s.model && <span>{s.model}</span>}
        {tokens > 0 && <span>{(tokens / 1000).toFixed(1)}k tok</span>}
      </div>
      {s.needs_approval && s.approval_id != null && (
        <ApprovalControls id={s.approval_id} tool={s.approval_tool} prompt={s.approval_prompt} />
      )}
    </motion.button>
  );
}
