// What the Triage home screen shows under "Needs you", most urgent first.
// Pure: takes what the screen already fetched, returns cards.

import type { Alert, Finding, LiveSession, PendingApproval } from './types';

export type Card =
  | { kind: 'approval'; key: string; approval: PendingApproval; session?: LiveSession }
  | { kind: 'alert'; key: string; tone: 'bad' | 'warn' | 'info'; alert: Alert }
  | { kind: 'session'; key: string; session: LiveSession }
  | { kind: 'finding'; key: string; tone: 'bad' | 'warn'; finding: Finding }
  | { kind: 'findings-more'; key: string; count: number };

/** A session that ended without saying so stays 'idle' forever; a day of silence means it is gone. */
export const fresh = (s: LiveSession) =>
  s.needs_input || !!s.needs_approval || (!!s.last_event_at && Date.now() - Date.parse(s.last_event_at) < 86_400_000);

export interface FeedInput {
  approvals: PendingApproval[];
  alerts: Alert[];
  sessions: LiveSession[];
  findings: Finding[];
}

/**
 * Order: approvals (something is blocked on you, and they expire), firing
 * alerts (critical first), sessions waiting for an answer, serious inventory
 * findings, then pending alerts. Findings about alerts are dropped because the
 * live alert list already says it. Warnings are folded into one "more" card
 * so the screen stays about what needs action now.
 */
export function buildFeed({ approvals, alerts, sessions, findings }: FeedInput): Card[] {
  const cards: Card[] = [];
  const bySession = new Map(sessions.filter((s) => s.approval_id).map((s) => [s.approval_id, s]));

  for (const a of approvals) {
    cards.push({ kind: 'approval', key: `ap-${a.id}`, approval: a, session: bySession.get(a.id) });
  }
  for (const a of alerts.filter((x) => x.state === 'firing')) {
    cards.push({ kind: 'alert', key: `al-${a.name}-${a.target ?? ''}`, tone: a.severity === 'critical' ? 'bad' : 'warn', alert: a });
  }
  for (const s of sessions.filter((x) => x.needs_input && !x.needs_approval && fresh(x))) {
    cards.push({ kind: 'session', key: `se-${s.session_uuid}`, session: s });
  }
  const live = findings.filter((f) => f.kind !== 'alert');
  for (const f of live.filter((x) => x.severity === 'bad')) {
    cards.push({ kind: 'finding', key: `fi-${f.title}`, tone: 'bad', finding: f });
  }
  const warns = live.filter((x) => x.severity === 'warn').length;
  if (warns) cards.push({ kind: 'findings-more', key: 'fi-more', count: warns });
  for (const a of alerts.filter((x) => x.state === 'pending')) {
    cards.push({ kind: 'alert', key: `al-${a.name}-${a.target ?? ''}`, tone: 'info', alert: a });
  }
  return cards;
}
