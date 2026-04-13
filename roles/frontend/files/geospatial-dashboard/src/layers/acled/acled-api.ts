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

  const regionParam = region ?? 11; // Default: Middle East
  const url = `https://acled-proxy.aicortex.workers.dev/acled/acled/read?limit=500&region=${regionParam}`;

  const resp = await fetch(url);
  if (!resp.ok) {
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
