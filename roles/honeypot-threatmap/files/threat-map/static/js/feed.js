// Live feed + sidebar stats panels + header counters.
// All attacker-controlled strings (path, UA, city, country) rendered via
// textContent — the old innerHTML templating was an XSS vector.
import { el, flag, countryName, attackLabel, sourceMeta, timeAgo, fmtClock } from './util.js';

const FEED_LIMIT = 120;
const COLLAPSE_WINDOW_MS = 60_000;

export class Feed {
  constructor() {
    this.feedEl = document.getElementById('feed');
    this.replayMode = false;
    this._last = null;   // {ip, attack_type, ts_ms, countEl, timeEl}
  }

  setReplayMode(on) {
    this.replayMode = on;
    this.clear();
  }

  clear() {
    this.feedEl.textContent = '';
    this._last = null;
  }

  add(evt) {
    // Collapse repeat hammering: same ip+type within 60s bumps ×N instead.
    if (this._last && this._last.ip === evt.ip
        && this._last.attack_type === evt.attack_type
        && evt.ts_ms - this._last.ts_ms < COLLAPSE_WINDOW_MS) {
      this._last.count += 1;
      this._last.ts_ms = evt.ts_ms;
      this._last.countEl.textContent = `×${this._last.count}`;
      this._last.countEl.style.display = 'inline';
      this._last.timeEl.textContent = this._time(evt);
      return;
    }

    const meta = sourceMeta(evt);
    const row = el('div', 'feed-item');
    row.appendChild(el('div', 'feed-flag', evt.geo_ok || evt.country_code !== '??'
      ? flag(evt.country_code) : '🌐'));

    const body = el('div', 'feed-body');
    const pathLine = el('div', 'feed-path');
    pathLine.textContent = evt.path || '/';
    body.appendChild(pathLine);

    const metaLine = el('div', 'feed-meta');
    const srcBadge = el('span', 'src-badge', meta.label);
    srcBadge.style.color = meta.tone;
    srcBadge.style.borderColor = meta.tone;
    metaLine.appendChild(srcBadge);
    metaLine.appendChild(el('span', 'type-badge', attackLabel(evt.attack_type)));
    if (evt.host) metaLine.appendChild(el('span', 'feed-host', evt.host));
    const count = el('span', 'feed-count', '');
    count.style.display = 'none';
    metaLine.appendChild(count);
    const place = [evt.city, countryName(evt)].filter(Boolean).join(', ');
    metaLine.appendChild(el('span', 'feed-place', place || 'origin unknown'));
    body.appendChild(metaLine);
    row.appendChild(body);

    const time = el('div', 'feed-time', this._time(evt));
    row.appendChild(time);

    this.feedEl.insertBefore(row, this.feedEl.firstChild);
    while (this.feedEl.children.length > FEED_LIMIT) {
      this.feedEl.removeChild(this.feedEl.lastChild);
    }
    this._last = { ip: evt.ip, attack_type: evt.attack_type, ts_ms: evt.ts_ms,
      count: 1, countEl: count, timeEl: time };
  }

  _time(evt) {
    return this.replayMode ? fmtClock(evt.ts_ms) : timeAgo(evt.ts_ms);
  }

  refreshTimes() {
    if (this.replayMode) return;
    // cheap: only the visible top rows matter; skip full re-render
  }
}

export class StatsPanels {
  constructor() {
    this.countryList = document.getElementById('country-list');
    this.typeList = document.getElementById('type-list');
    this.pathList = document.getElementById('path-list');
    this.cntTotal = document.getElementById('cnt-total');
    this.cntRate = document.getElementById('cnt-rate');
    this.cntCountries = document.getElementById('cnt-countries');
    this.srcChips = {
      honeypot: document.getElementById('chip-honeypot'),
      probes: document.getElementById('chip-probes'),
      bans: document.getElementById('chip-bans'),
    };
  }

  render(s) {
    this.cntTotal.textContent = (s.total_24h ?? 0).toLocaleString();
    this.cntRate.textContent = (s.rate_hour ?? 0).toLocaleString();
    this.cntCountries.textContent = s.top_countries?.length ?? 0;
    for (const [k, elch] of Object.entries(this.srcChips)) {
      if (elch) elch.textContent = (s.by_source?.[k] ?? 0).toLocaleString();
    }

    this.countryList.textContent = '';
    const maxC = s.top_countries?.[0]?.count || 1;
    for (const c of (s.top_countries || []).slice(0, 7)) {
      const row = el('div', 'stat-row');
      const label = el('span');
      label.textContent = `${flag(c.country_code)} ${countryName({ country: c.country })}`;
      row.append(label, el('span', 'stat-count', String(c.count)));
      this.countryList.appendChild(row);
      const bar = el('div', 'stat-bar');
      const fill = el('div', 'stat-bar-fill');
      fill.style.width = `${Math.round((c.count / maxC) * 100)}%`;
      bar.appendChild(fill);
      this.countryList.appendChild(bar);
    }

    this.typeList.textContent = '';
    for (const t of (s.attack_types || []).slice(0, 6)) {
      const row = el('div', 'stat-row');
      row.append(el('span', 'type-badge', attackLabel(t.type)),
        el('span', 'stat-count', String(t.count)));
      this.typeList.appendChild(row);
    }

    this.pathList.textContent = '';
    for (const p of (s.top_paths || []).slice(0, 5)) {
      const row = el('div', 'stat-row');
      const path = el('span', 'stat-path');
      path.textContent = p.path;
      row.append(path, el('span', 'stat-count', String(p.count)));
      this.pathList.appendChild(row);
    }
  }

  // Replay window aggregates take over the counters.
  renderReplay(events, windowMs) {
    const countries = new Set();
    const bySrc = { honeypot: 0, probes: 0, bans: 0 };
    for (const e of events) {
      if (e.country_code && e.country_code !== '??') countries.add(e.country_code);
      bySrc[sourceMeta(e).key] += 1;
    }
    this.cntTotal.textContent = events.length.toLocaleString();
    const hours = Math.max(windowMs / 3_600_000, 1 / 60);
    this.cntRate.textContent = Math.round(events.length / hours).toLocaleString();
    this.cntCountries.textContent = countries.size;
    for (const [k, elch] of Object.entries(this.srcChips)) {
      if (elch) elch.textContent = bySrc[k].toLocaleString();
    }
  }
}
