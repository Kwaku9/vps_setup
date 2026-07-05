// Shared helpers. Everything that renders attacker-controlled strings goes
// through DOM textContent — never innerHTML — so hostile paths/UAs can't XSS
// the dashboard.

export function el(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

export function flag(cc) {
  if (!cc || cc.length !== 2 || /[^A-Za-z]/.test(cc)) return '🌐';
  const up = cc.toUpperCase();
  if (up === 'XX' || up === '??') return '🌐';
  const base = 0x1F1E6 - 65;
  return String.fromCodePoint(base + up.charCodeAt(0), base + up.charCodeAt(1));
}

const regionNames = (() => {
  try { return new Intl.DisplayNames(['en'], { type: 'region' }); }
  catch { return null; }
})();

export function countryName(evt) {
  const c = evt.country || '';
  // Backends sometimes only know the ISO code — expand it for display.
  if (regionNames && /^[A-Z]{2}$/i.test(c) && c !== '??' && c !== 'XX') {
    try { return regionNames.of(c.toUpperCase()) || c; } catch { return c; }
  }
  return c || 'Unknown';
}

export const ATTACK_LABELS = {
  wordpress_probe: 'WordPress', env_probe: '.env scan', git_probe: '.git probe',
  db_probe: 'DB probe', admin_probe: 'Admin probe', shell_probe: 'Shell probe',
  api_probe: 'API scan', backup_probe: 'Backup scan', path_traversal: 'Traversal',
  credential_probe: 'Cred probe', cms_probe: 'CMS probe', generic_probe: 'Generic',
  recon: 'Recon', banned: 'BANNED', auth_failure: 'Auth fail',
  access_denied: 'Denied', rate_limited: 'Ratelimit', malformed_request: 'Malformed',
};

export function attackLabel(type) { return ATTACK_LABELS[type] || type || '—'; }

// Event source → validated data tones (chart marks, chips, badges).
export const SOURCE_META = {
  honeypot:      { key: 'honeypot', label: 'HONEYPOT', tone: '#00a95e', glow: '#00ff88' },
  traefik_probe: { key: 'probes',   label: 'PROBE',    tone: '#2789cc', glow: '#38b6ff' },
  crowdsec_ban:  { key: 'bans',     label: 'BAN',      tone: '#e8304b', glow: '#ff3355' },
};
export function sourceMeta(evt) {
  return SOURCE_META[evt.type] || SOURCE_META.honeypot;
}

export function timeAgo(ts_ms) {
  const diff = Math.round((Date.now() - ts_ms) / 1000);
  if (diff < 5) return 'now';
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.round(diff / 60)}m`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h`;
  return `${Math.round(diff / 86400)}d`;
}

export function fmtClock(ts_ms) {
  return new Date(ts_ms).toLocaleTimeString([], { hour12: false });
}

export function fmtSpan(start_ms, end_ms) {
  const s = new Date(start_ms), e = new Date(end_ms);
  const sameDay = s.toDateString() === e.toDateString();
  const d = (x) => x.toLocaleDateString([], { month: 'short', day: 'numeric' });
  const t = (x) => x.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  return sameDay ? `${d(s)} ${t(s)}–${t(e)}` : `${d(s)} ${t(s)} → ${d(e)} ${t(e)}`;
}

export function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

export const store = {
  get(k, fallback) {
    try {
      const v = localStorage.getItem(k);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
