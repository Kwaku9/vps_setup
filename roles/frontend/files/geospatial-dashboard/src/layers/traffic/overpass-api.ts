export interface RoadSegment {
  id: number;
  highway: string;
  coords: [number, number][]; // [lon, lat] pairs
  cumulativeLengths: number[];
  totalLength: number;
}

interface CacheEntry {
  segments: RoadSegment[];
  timestamp: number;
}

const CACHE_TTL = 5 * 60 * 1000; // 5 minutes
const cache = new Map<string, CacheEntry>();

function cacheKey(lat: number, lon: number): string {
  return `${(lat * 10) | 0},${(lon * 10) | 0}`;
}

function haversineDistance(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function computeCumulativeLengths(
  coords: [number, number][]
): { cumulativeLengths: number[]; totalLength: number } {
  const cumulativeLengths = [0];
  let total = 0;
  for (let i = 1; i < coords.length; i++) {
    const d = haversineDistance(
      coords[i - 1][1],
      coords[i - 1][0],
      coords[i][1],
      coords[i][0]
    );
    total += d;
    cumulativeLengths.push(total);
  }
  return { cumulativeLengths, totalLength: total };
}

export async function fetchRoadSegments(
  lat: number,
  lon: number,
  radiusKm: number = 2
): Promise<RoadSegment[]> {
  const key = cacheKey(lat, lon);
  const cached = cache.get(key);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.segments;
  }

  const offset = radiusKm / 111;
  const south = lat - offset;
  const north = lat + offset;
  const west = lon - offset;
  const east = lon + offset;

  const query = `
    [out:json][timeout:15];
    way["highway"~"motorway|primary|secondary"](${south},${west},${north},${east});
    out geom;
  `;

  const response = await fetch("/api/overpass/api/interpreter", {
    method: "POST",
    body: "data=" + encodeURIComponent(query),
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });

  if (!response.ok) {
    throw new Error(`Overpass API error: ${response.status}`);
  }

  const data = await response.json();
  const segments: RoadSegment[] = [];

  for (const element of data.elements || []) {
    if (element.type !== "way" || !element.geometry) continue;

    const coords: [number, number][] = element.geometry.map(
      (g: { lon: number; lat: number }) => [g.lon, g.lat] as [number, number]
    );

    if (coords.length < 2) continue;

    const { cumulativeLengths, totalLength } =
      computeCumulativeLengths(coords);

    segments.push({
      id: element.id,
      highway: element.tags?.highway || "unknown",
      coords,
      cumulativeLengths,
      totalLength,
    });
  }

  cache.set(key, { segments, timestamp: Date.now() });
  console.log(
    `Fetched ${segments.length} road segments near ${lat.toFixed(2)},${lon.toFixed(2)}`
  );
  return segments;
}
