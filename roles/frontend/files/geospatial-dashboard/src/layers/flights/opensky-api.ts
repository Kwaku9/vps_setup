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
}

// Max flights to render at once to keep the globe responsive
const MAX_FLIGHTS = 120;

/**
 * Fetch flight states from airplanes.live ADS-B Exchange.
 * Uses point+radius query based on camera position.
 * Returns real lat/lon coordinates for each aircraft.
 */
export async function fetchFlightStates(
  lat: number,
  lon: number,
  radiusNm: number = 150
): Promise<FlightState[]> {
  // Cap radius to avoid huge responses and rate limits
  const cappedRadius = Math.min(150, Math.max(25, radiusNm));

  const response = await fetch(
    `/api/planes/v2/point/${lat.toFixed(2)}/${lon.toFixed(2)}/${cappedRadius}`
  );

  if (!response.ok) {
    // Check for rate limit — back off gracefully
    if (response.status === 429) {
      console.warn('airplanes.live rate limited, will retry next poll');
      return [];
    }
    throw new Error(`airplanes.live API error: ${response.status}`);
  }

  const data = await response.json();
  if (!data.ac) return [];

  return data.ac
    .filter((s: any) => s.lon != null && s.lat != null && !s.gnd)
    .slice(0, MAX_FLIGHTS)
    .map((s: any): FlightState => ({
      icao24: s.hex || '',
      callsign: (s.flight || '').trim(),
      longitude: s.lon,
      latitude: s.lat,
      altitude: (s.alt_geom ?? s.alt_baro ?? 0) * 0.3048,
      velocity: (s.gs ?? 0) * 0.5144, // knots → m/s
      heading: s.track ?? 0,
      onGround: false,
      lastContact: s.seen ?? 0,
      aircraftType: s.t || '',
      description: s.desc || '',
      operator: s.ownOp || '',
    }));
}
