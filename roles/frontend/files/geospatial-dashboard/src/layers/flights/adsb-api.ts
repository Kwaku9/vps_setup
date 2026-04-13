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

export async function fetchMilitaryAircraft(): Promise<MilitaryAircraft[]> {
  const response = await fetch('/api/planes/v2/mil');

  if (!response.ok) {
    throw new Error(`airplanes.live API error: ${response.status}`);
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
      altitude: (ac.alt_geom ?? ac.alt_baro ?? 0) * 0.3048,
      speed: ac.gs ?? 0,
      heading: ac.track ?? 0,
      squawk: ac.squawk || '',
      flag: ac.dbFlags?.toString() || '',
    }));
}
