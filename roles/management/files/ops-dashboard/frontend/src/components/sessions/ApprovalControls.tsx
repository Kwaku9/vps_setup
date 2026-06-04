import { useState } from 'react';
import { decideApproval } from '../../api/client';

export function ApprovalControls({ id, tool, prompt }: { id: number; tool?: string | null; prompt?: string | null }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const decide = async (e: React.MouseEvent, decision: 'approve' | 'deny') => {
    e.stopPropagation();
    setBusy(true);
    try { await decideApproval(id, decision); setDone(decision === 'approve' ? 'Approved' : 'Denied'); }
    catch { setDone('failed'); }
    finally { setBusy(false); }
  };

  if (done) return <div className="mt-2 text-[11px] text-white/50">{done}</div>;

  return (
    <div className="mt-2 rounded-xl bg-amber-400/10 border border-amber-400/30 p-2">
      <div className="text-[11px] font-semibold text-amber-300">NEEDS APPROVAL{tool ? ` · ${tool}` : ''}</div>
      {prompt && <div className="mt-1 text-[11px] text-white/60 whitespace-pre-wrap break-words max-h-20 overflow-y-auto">{prompt}</div>}
      <div className="mt-2 flex gap-2">
        <button disabled={busy} onClick={(e) => decide(e, 'approve')}
          className="flex-1 rounded-lg bg-emerald-500/80 py-1.5 text-[12px] font-semibold disabled:opacity-50">Approve</button>
        <button disabled={busy} onClick={(e) => decide(e, 'deny')}
          className="flex-1 rounded-lg bg-rose-500/80 py-1.5 text-[12px] font-semibold disabled:opacity-50">Deny</button>
      </div>
    </div>
  );
}
