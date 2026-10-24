export interface ConflictEvent {
  event_id: string;
  event_date: string;
  event_type: string;
  sub_event_type: string;
  actor1: string;
  actor2: string;
  country: string;
  location: string;
  latitude: number;
  longitude: number;
  fatalities: number;
  notes: string;
}

export const ACLED_EVENT_COLORS: Record<string, string> = {
  Battles: "#FF0000",
  "Explosions/Remote violence": "#FF6600",
  "Violence against civilians": "#FF00FF",
  Protests: "#FFFF00",
  Riots: "#FF8800",
  "Strategic developments": "#00AAFF",
};

/** Thrown when no proxy is configured — an expected state for a fresh clone,
 *  not a failure. The layer reports it once and stays empty. */
export class AcledNotConfigured extends Error {
  constructor() {
    super('ACLED layer inactive — set VITE_ACLED_PROXY_URL (see .env.example)');
    this.name = 'AcledNotConfigured';
  }
}

interface CacheEntry {
  data: ConflictEvent[];
  time: number;
}

const CACHE_TTL = 600000; // 10 minutes
let cached: CacheEntry | null = null;

export async function fetchConflictEvents(
  region?: number
): Promise<ConflictEvent[]> {
  if (cached && Date.now() - cached.time < CACHE_TTL) return cached.data;

  // ACLED needs an account AND a proxy, so the endpoint is configuration rather
  // than a constant. It used to be one deployment's personal Cloudflare Worker
  // hardcoded here, which meant every clone pointed at someone else's
  // infrastructure and got a 403.
  //
  // Why a proxy at all: ACLED has no API key. Access is a Drupal session — you
  // POST an email and password to /user/login and reuse the cookie — which
  // cannot happen in a browser (CORS, and the credentials would be public) and
  // cannot happen in nginx either. It needs something that can hold a session.
  // acled-proxy-worker/ in this package is one such thing; any equivalent works.
  const base = (import.meta.env.VITE_ACLED_PROXY_URL || '').replace(/\/+$/, '');
  if (!base) {
    throw new AcledNotConfigured();
  }

  const regionParam = region ?? 11; // Default: Middle East
  const url = `${base}/acled/acled/read?limit=500&region=${regionParam}`;

  const resp = await fetch(url);
  if (!resp.ok) {
    // 403 here is ACLED refusing the proxy's session, not the proxy being down —
    // usually an expired or unapproved account rather than a misconfiguration.
    if (resp.status === 403) {
      throw new Error(
        'ACLED denied the request (403) — the proxy reached ACLED but the ' +
        'account was rejected. Check the credentials and that the account is approved.'
      );
    }
    throw new Error("ACLED API " + resp.status);
  }

  const json = await resp.json();
  const rawData = json.data || json;

  const results: ConflictEvent[] = (Array.isArray(rawData) ? rawData : []).map(
    (r: any) => ({
      event_id: r.event_id_cnty || r.data_id || "",
      event_date: r.event_date || "",
      event_type: r.event_type || "",
      sub_event_type: r.sub_event_type || "",
      actor1: r.actor1 || "",
      actor2: r.actor2 || "",
      country: r.country || "",
      location: r.location || "",
      latitude: parseFloat(r.latitude) || 0,
      longitude: parseFloat(r.longitude) || 0,
      fatalities: parseInt(r.fatalities) || 0,
      notes: r.notes || "",
    })
  );

  cached = { data: results, time: Date.now() };
  return results;
}
