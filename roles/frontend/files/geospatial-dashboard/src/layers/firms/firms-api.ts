export interface ThermalAnomaly {
  latitude: number;
  longitude: number;
  brightness: number;
  confidence: string;
  frp: number;
  acq_date: string;
  acq_time: string;
  satellite: string;
  daynight: string;
}

interface CacheEntry {
  data: ThermalAnomaly[];
  time: number;
}

const CACHE_TTL = 300000; // 5 minutes
const cache = new Map<string, CacheEntry>();

function cacheKey(w: number, s: number, e: number, n: number): string {
  return `firms:${w.toFixed(1)},${s.toFixed(1)},${e.toFixed(1)},${n.toFixed(1)}`;
}

export async function fetchFIRMS(
  west: number,
  south: number,
  east: number,
  north: number
): Promise<ThermalAnomaly[]> {
  const key = cacheKey(west, south, east, north);
  const cached = cache.get(key);
  if (cached && Date.now() - cached.time < CACHE_TTL) return cached.data;

  const mapKey = (import.meta as any).env?.VITE_FIRMS_MAP_KEY || "";
  if (!mapKey) {
    console.warn("FIRMS: No MAP_KEY configured");
    return [];
  }

  const bbox = `${west},${south},${east},${north}`;
  const url = `/api/firms/api/area/csv/${mapKey}/VIIRS_SNPP_NRT/${bbox}/2`;

  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error("FIRMS API " + resp.status);
  }

  const text = await resp.text();
  const lines = text.trim().split("\n");
  if (lines.length < 2) return []; // header only, no data

  const headers = lines[0].split(",");
  const idx = (name: string) => headers.indexOf(name);

  const results: ThermalAnomaly[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",");
    results.push({
      latitude: parseFloat(cols[idx("latitude")] || "0"),
      longitude: parseFloat(cols[idx("longitude")] || "0"),
      brightness: parseFloat(cols[idx("bright_ti4")] || cols[idx("brightness")] || "0"),
      confidence: cols[idx("confidence")] || "nominal",
      frp: parseFloat(cols[idx("frp")] || "0"),
      acq_date: cols[idx("acq_date")] || "",
      acq_time: cols[idx("acq_time")] || "",
      satellite: cols[idx("satellite")] || "VIIRS",
      daynight: cols[idx("daynight")] || "D",
    });
  }

  cache.set(key, { data: results, time: Date.now() });
  return results;
}
