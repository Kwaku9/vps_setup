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

export interface BoundingBox {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
}

interface VesselResponse {
  count: number;
  vessels: VesselState[];
}

export async function fetchVessels(bbox?: BoundingBox): Promise<VesselState[]> {
  let url = "/api/ais/vessels";
  if (bbox) {
    const params = new URLSearchParams({
      minLat: bbox.minLat.toFixed(4),
      maxLat: bbox.maxLat.toFixed(4),
      minLon: bbox.minLon.toFixed(4),
      maxLon: bbox.maxLon.toFixed(4),
    });
    url += "?" + params.toString();
  }

  const response = await fetch(url);
  if (!response.ok) throw new Error("AIS fetch failed: " + response.status);

  const data: VesselResponse = await response.json();
  return data.vessels;
}
