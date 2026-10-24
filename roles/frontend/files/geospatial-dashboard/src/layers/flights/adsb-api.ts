import { FlightState } from "./opensky-api";
export interface MilitaryAircraft {
  icao: string;
  callsign: string;
  type: string;
  description: string;
  operator: string;
  longitude: number;
  latitude: number;
  altitude: number;
  speed: number;
  heading: number;
  squawk: string;
  flag: string;
}

/**
 * Aircraft from adsb.lol (api.adsb.lol, ODbL data, no account or key).
 *
 * WHY ADSB.LOL. airplanes.live went approval-only in 2026-08 (anonymous
 * callers get 403), which emptied the military layer, and OpenSky's open feed
 * carries no aircraft TYPE, so every civil plane drew as the same generic jet.
 * adsb.lol serves the same readsb v2 JSON airplanes.live did, open, with the
 * ICAO type code (`t`) and ADS-B emitter category on each aircraft, and a
 * /v2/mil filter. Verified 2026-10-24: 174 aircraft around JFK, nearly all
 * typed, and /v2/mil answering 200.
 */
const ADSBLOL = '/api/adsblol';

/** Feet (readsb altitude) to metres; "ground" and missing read as 0. */
function altitudeMetres(ac: any): number {
  const ft = typeof ac.alt_geom === 'number' ? ac.alt_geom
    : typeof ac.alt_baro === 'number' ? ac.alt_baro : 0;
  return ft * 0.3048;
}

/** Civil + general traffic within radiusNm of a point (adsb.lol caps 250). */
export async function fetchAircraftNear(
  lat: number,
  lon: number,
  radiusNm: number
): Promise<FlightState[]> {
  const r = Math.round(Math.min(250, Math.max(10, radiusNm)));
  const response = await fetch(`${ADSBLOL}/v2/point/${lat.toFixed(4)}/${lon.toFixed(4)}/${r}`);
  if (!response.ok) throw new Error(`adsb.lol API error: ${response.status}`);
  const data = await response.json();
  return (data.ac ?? [])
    .filter((ac: any) => ac.lon != null && ac.lat != null && ac.alt_baro !== 'ground')
    .map((ac: any): FlightState => ({
      icao24: ac.hex || '',
      callsign: (ac.flight || '').trim(),
      longitude: ac.lon,
      latitude: ac.lat,
      altitude: altitudeMetres(ac),
      velocity: (ac.gs ?? 0) * 0.514444, // knots → m/s, as FlightState expects
      heading: ac.track ?? ac.true_heading ?? 0,
      onGround: false,
      lastContact: Math.round(Date.now() / 1000 - (ac.seen ?? 0)),
      aircraftType: ac.t || '',
      description: ac.desc || '',
      operator: ac.ownOp || '',
      category: ac.category ?? null,
    }));
}
export class MilitaryFeedUnavailable extends Error {
  constructor(public readonly status: number) {
    super(
      status === 403
        ? 'Military feed refused (403) by adsb.lol'
        : `adsb.lol API error: ${status}`
    );
    this.name = 'MilitaryFeedUnavailable';
  }
}

export async function fetchMilitaryAircraft(): Promise<MilitaryAircraft[]> {
  let response: Response;
  try {
    response = await fetch(`${ADSBLOL}/v2/mil`);
  } catch (e) {
    throw new MilitaryFeedUnavailable(0);
  }

  if (!response.ok) {
    throw new MilitaryFeedUnavailable(response.status);
  }

  const data = await response.json();
  if (!data.ac) return [];

  return data.ac
    .filter((ac: any) => ac.lon != null && ac.lat != null)
    .map((ac: any): MilitaryAircraft => ({
      icao: ac.hex || '',
      callsign: (ac.flight || '').trim(),
      type: ac.t || 'Unknown',
      description: ac.desc || '',
      operator: ac.ownOp || '',
      longitude: ac.lon,
      latitude: ac.lat,
      altitude: altitudeMetres(ac),
      speed: ac.gs ?? 0,
      heading: ac.track ?? 0,
      squawk: ac.squawk || '',
      flag: ac.dbFlags?.toString() || '',
    }));
}
