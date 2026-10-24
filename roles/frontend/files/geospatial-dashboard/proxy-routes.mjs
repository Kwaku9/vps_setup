/**
 * The single source of truth for every upstream this app proxies.
 *
 * WHY THIS FILE EXISTS. There were two independent proxy tables — one in
 * vite.config.ts (19 routes) and one in nginx.conf (6) — and they drifted until
 * the production image served only a third of the data layers. Nobody noticed,
 * because production was running the *dev* target, so the vite table was the one
 * in use and nginx was never exercised.
 *
 * Both now generate from this list: vite.config.ts imports it for `server.proxy`,
 * and `npm run gen:nginx` writes the matching nginx location blocks. Add a route
 * here and both get it. Add it to one of them by hand and you have recreated the
 * bug.
 *
 * FIELDS
 *   path      the local prefix the browser calls
 *   target    upstream origin
 *   rewriteTo what `path` is replaced with upstream ('' strips the prefix)
 *   strip     drop proxy/CDN headers that make some public endpoints 403
 *   headers   extra request headers to send upstream
 *   needs     env var required; when unset the layer should degrade, not crash
 *   internal  upstream is a companion service, not a public API — a recipient
 *             running this standalone will not have it (see README)
 *   why       one line, for the humans reading the generated nginx.conf
 */
export const ROUTES = [
  // ── Keyless public feeds. These work with an empty .env. ────────────────
  // OpenSky sends `access-control-allow-origin: https://opensky-network.org`,
  // not `*`, so the browser cannot call it directly — it must come through here.
  { path: '/api/opensky', target: 'https://opensky-network.org', rewriteTo: '/api',
    why: 'OpenSky Network live aircraft — open, no account, rate limited' },
  // adsb.lol replaced airplanes.live (approval-only since 2026-08): the same
  // readsb v2 JSON, open, with aircraft type codes. Backs civil and military.
  { path: '/api/adsblol', target: 'https://api.adsb.lol', rewriteTo: '',
    why: 'adsb.lol live aircraft with types, open (ODbL), no account' },
  { path: '/api/cctv', target: 'https://webcams.nyctmc.org', rewriteTo: '',
    why: 'NYC DOT traffic cameras' },
  { path: '/api/caltrans', target: 'https://cwwp2.dot.ca.gov', rewriteTo: '/data', strip: true,
    why: 'California DOT cameras' },
  { path: '/api/fl511', target: 'https://fl511.com', rewriteTo: '', strip: true,
    why: 'Florida 511 cameras' },
  { path: '/api/txdot', target: 'https://its.txdot.gov', rewriteTo: '/its', strip: true,
    why: 'Texas DOT cameras' },
  { path: '/api/ilcams', target: 'https://services2.arcgis.com', rewriteTo: '', strip: true,
    why: 'Illinois cameras (ArcGIS)' },
  { path: '/api/dccams', target: 'https://maps2.dcgis.dc.gov', rewriteTo: '', strip: true,
    why: 'Washington DC cameras' },
  { path: '/api/ga511', target: 'https://511ga.org', rewriteTo: '', strip: true,
    why: 'Georgia 511 cameras' },
  { path: '/api/overpass', target: 'https://overpass-api.de', rewriteTo: '',
    why: 'OpenStreetMap Overpass — road geometry for the traffic layer' },
  { path: '/api/osint/ipinfo/', target: 'https://ipinfo.io', rewriteTo: '',
    why: 'IP geolocation for the OSINT panel' },
  { path: '/api/osint/greynoise/', target: 'https://api.greynoise.io', rewriteTo: '/v3/community',
    why: 'GreyNoise community IP reputation' },
  { path: '/api/osint/rdns', target: 'https://cloudflare-dns.com', rewriteTo: '/dns-query',
    headers: { Accept: 'application/dns-json' },
    why: 'Reverse DNS over Cloudflare DoH' },

  // ── Keyed. The layer should say "no key" rather than fail silently. ─────
  { path: '/api/firms', target: 'https://firms.modaps.eosdis.nasa.gov', rewriteTo: '', strip: true,
    needs: 'VITE_FIRMS_MAP_KEY',
    why: 'NASA FIRMS wildfire hotspots (key is in the query string, not a header)' },

  // ── Companion services. Not public APIs — see README "Optional services". ──
  // Hostnames are env-overridable so this repo is not welded to one deployment's
  // service names. Defaults match the compose file shipped here.
  // `env` names the variable that overrides `target`; vite.config resolves it
  // after loading .env (process.env alone misses values that live only there).
  { path: '/api/ais/', target: process.env.AIS_RELAY_URL || 'http://ais-relay:9100',
    env: 'AIS_RELAY_URL', rewriteTo: '', internal: true,
    why: 'Maritime AIS relay — one upstream socket fanned out to all viewers' },
  { path: '/api/threats/', target: process.env.THREATS_URL || 'http://metrics:8428',
    env: 'THREATS_URL', rewriteTo: '/api/v1', internal: true,
    why: 'Threat telemetry from a Prometheus-compatible store' },
];

/**
 * Routes needing real server logic rather than a dumb pass-through, so they are
 * implemented as middleware in dev and as explicit blocks in nginx.
 *   wigle     — credentialed, tiny daily quota: needs a shared token bucket and
 *               a response cache, or one open tab burns the account's budget.
 *   abuseipdb — credentialed via a request header.
 */
export const SPECIAL = [
  { path: '/api/wigle', target: 'https://api.wigle.net', needs: 'WIGLE_API_TOKEN',
    why: 'WiGLE wireless-network density (rate-limited + cached server-side)' },
  { path: '/api/osint/abuseipdb', target: 'https://api.abuseipdb.com', rewriteTo: '/api/v2/check',
    needs: 'ABUSEIPDB_API_KEY',
    why: 'AbuseIPDB reputation lookups' },
];
