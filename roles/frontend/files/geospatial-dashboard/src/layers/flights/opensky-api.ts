export interface FlightState {
  icao24: string;
  callsign: string;
  longitude: number;
  latitude: number;
  altitude: number;
  velocity: number;
  heading: number;
  onGround: boolean;
  lastContact: number;
  aircraftType: string;
  description: string;
  operator: string;
  /** Emitter category: OpenSky integer (extended states, index 17) or ADS-B
   *  string ("A3") from adsb.lol; null when unknown. */
  category: number | string | null;
}

// Max flights to render at once to keep the globe responsive
const MAX_FLIGHTS = 120;

/**
 * Fetch live aircraft from the OpenSky Network.
 *
 * WHY OPENSKY. This module was named for OpenSky, then quietly rewritten to
 * call airplanes.live. As of 2026-08-21 airplanes.live answers anonymous
 * requests with 403 and "contact us at contact@airplanes.live" — confirmed from
 * two unrelated IPs, so it is a policy change, not a block on one host. That
 * makes it unusable for anyone running this from a fresh clone.
 *
 * OpenSky's /states/all is open with no account, no key and no signup. It is
 * rate limited for anonymous callers (roughly one query per 10s of resolution,
 * with a daily credit budget), which is why callers should poll on a timer
 * rather than per camera move.
 *
 * The trade: OpenSky takes a BOUNDING BOX, not a point and radius, and it does
 * not expose a military filter — see military-layer for what that costs.
 */
// Proxied: OpenSky restricts CORS to its own origin, so a direct browser call
// is blocked. The proxy route is declared in proxy-routes.mjs.
const OPENSKY_URL = "/api/opensky/states/all";

/** Rough nautical-miles-to-degrees box around a point. Longitude degrees shrink
 *  with latitude, so the cosine term matters near the poles; clamped so a view
 *  near 90° does not produce an infinite box. */
function boxAround(lat: number, lon: number, radiusNm: number) {
  const degLat = radiusNm / 60;
  const cos = Math.max(0.1, Math.cos((lat * Math.PI) / 180));
  const degLon = radiusNm / (60 * cos);
  return {
    lamin: Math.max(-90, lat - degLat),
    lamax: Math.min(90, lat + degLat),
    lomin: Math.max(-180, lon - degLon),
    lomax: Math.min(180, lon + degLon),
  };
}

/**
 * OpenSky returns each aircraft as a positional array rather than an object.
 * Indices are fixed by the API contract:
 *   0 icao24 · 1 callsign · 2 origin_country · 3 time_position · 4 last_contact
 *   5 longitude · 6 latitude · 7 baro_altitude · 8 on_ground · 9 velocity
 *   10 true_track · 11 vertical_rate · 12 sensors · 13 geo_altitude
 */
export async function fetchFlightStates(
  lat: number,
  lon: number,
  radiusNm: number = 150
): Promise<FlightState[]> {
  const capped = Math.min(150, Math.max(25, radiusNm));
  const b = boxAround(lat, lon, capped);
  const qs = new URLSearchParams({
    lamin: b.lamin.toFixed(4), lomin: b.lomin.toFixed(4),
    lamax: b.lamax.toFixed(4), lomax: b.lomax.toFixed(4),
    // Adds the emitter category (index 17), which picks the aircraft icon.
    extended: "1",
  });

  let response: Response;
  try {
    response = await fetch(`${OPENSKY_URL}?${qs}`);
  } catch (e) {
    // Network failure should empty the layer, not throw into the render loop.
    console.warn('OpenSky unreachable:', e);
    return [];
  }

  if (!response.ok) {
    // 429 is expected on the anonymous tier under load — back off quietly and
    // keep the previous frame rather than surfacing an error to the viewer.
    if (response.status === 429) {
      console.warn('OpenSky rate limited (anonymous tier), will retry next poll');
      return [];
    }
    console.warn(`OpenSky API error: ${response.status}`);
    return [];
  }

  const data = await response.json();
  const states: any[] = data?.states ?? [];

  return states
    .filter((s) => s[5] != null && s[6] != null && s[8] !== true)
    .slice(0, MAX_FLIGHTS)
    .map((s): FlightState => ({
      icao24: s[0] || '',
      callsign: (s[1] || '').trim(),
      longitude: s[5],
      latitude: s[6],
      // geo_altitude when present, else barometric. Already metres — unlike the
      // previous source, which reported feet and needed converting.
      altitude: s[13] ?? s[7] ?? 0,
      velocity: s[9] ?? 0,          // already m/s
      heading: s[10] ?? 0,
      onGround: s[8] === true,
      lastContact: s[4] ?? 0,
      // OpenSky's open feed carries no type/operator metadata. Left blank so the
      // info panel shows nothing rather than something invented; origin_country
      // is the one extra fact it does give us.
      aircraftType: '',
      description: s[2] || '',
      operator: '',
      category: typeof s[17] === 'number' ? s[17] : null,
    }));
}
