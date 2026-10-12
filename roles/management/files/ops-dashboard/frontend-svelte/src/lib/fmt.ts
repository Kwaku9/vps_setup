// Small display helpers. Times are shown in the phone's own time zone.

export function ago(iso: string | number | null | undefined): string {
  if (iso == null || iso === '') return '—';
  const t = typeof iso === 'number' ? iso * 1000 : Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  return dur((Date.now() - t) / 1000) + ' ago';
}

export function dur(s: number | null | undefined): string {
  if (s == null || Number.isNaN(s)) return '—';
  s = Math.max(0, s);
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.round((s % 86400) / 3600)}h`;
}

export function until(iso: string | null | undefined): string {
  if (!iso) return '';
  const s = (Date.parse(iso) - Date.now()) / 1000;
  return s <= 0 ? 'expired' : `expires in ${dur(s)}`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${u[i]}`;
}

export const pct = (f: number | null | undefined) => (f == null ? '—' : `${Math.round(f * 100)}%`);
export const num = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString());

/** Any value -> one readable line, for detail sheets. */
export function show(v: unknown): string {
  if (v == null || v === '') return '—';
  if (Array.isArray(v)) return v.length ? v.map(show).join(', ') : '—';
  if (typeof v === 'object') return JSON.stringify(v);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  return String(v);
}
