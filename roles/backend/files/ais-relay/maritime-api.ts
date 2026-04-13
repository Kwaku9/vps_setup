export interface VesselState {
  mmsi: string;
  name: string;
  lat: number;
  lon: number;
  cog: number;       // course over ground (degrees)
  sog: number;       // speed over ground (knots)
  heading: number;   // true heading (degrees)
  category: string;  // cargo, tanker, passenger, fishing, military, hsc, special, other
  color: string;     // hex color for the category
  destination: string;
  navStatus: number;
  length: number;    // meters
  age: number;       // seconds since last AIS report
}

interface VesselResponse {
  count: number;
  vessels: VesselState[];
}

export async function fetchVessels(): Promise<VesselState[]> {
  const response = await fetch("/api/ais/vessels");
  if (!response.ok) throw new Error("AIS fetch failed: " + response.status);

  const data: VesselResponse = await response.json();
  return data.vessels;
}
