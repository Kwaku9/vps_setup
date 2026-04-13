export interface Earthquake {
  id: string;
  magnitude: number;
  depth: number;
  latitude: number;
  longitude: number;
  place: string;
  time: number;
  tsunami: boolean;
  url: string;
}

const USGS_URL =
  "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=200&minmagnitude=2.5";

export async function fetchEarthquakes(): Promise<Earthquake[]> {
  const response = await fetch(USGS_URL);
  if (!response.ok)
    throw new Error("USGS API error: " + response.status);

  const data = await response.json();
  if (!data.features) return [];

  return data.features.map(
    (f: any): Earthquake => ({
      id: f.id,
      magnitude: f.properties.mag ?? 0,
      depth: f.geometry.coordinates[2] ?? 0,
      latitude: f.geometry.coordinates[1],
      longitude: f.geometry.coordinates[0],
      place: f.properties.place || "Unknown",
      time: f.properties.time,
      tsunami: !!f.properties.tsunami,
      url: f.properties.url || "",
    })
  );
}
