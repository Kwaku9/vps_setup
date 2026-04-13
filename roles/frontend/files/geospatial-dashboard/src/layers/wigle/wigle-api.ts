export interface WigleNetwork {
  ssid: string;
  bssid: string;
  lat: number;
  lon: number;
  encryption: string;
  channel: number;
  type: "wifi" | "cell" | "bt";
  firstSeen: string;
  lastSeen: string;
  // cell-specific
  carrier?: string;
  cellType?: string;
}

interface CacheEntry {
  data: WigleNetwork[];
  time: number;
}

const CACHE_TTL = 300000; // 5 minutes
const cache = new Map<string, CacheEntry>();

function cacheKey(lat: number, lon: number, kind: string): string {
  return kind + ":" + lat.toFixed(2) + "," + lon.toFixed(2);
}

function getCached(key: string): WigleNetwork[] | null {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.time < CACHE_TTL) return entry.data;
  return null;
}

async function wigleGet(
  endpoint: string,
  params: Record<string, string>
): Promise<any> {
  const qs = new URLSearchParams(params).toString();
  const resp = await fetch("/api/wigle/api/v2/" + endpoint + "?" + qs);
  if (!resp.ok) {
    if (resp.status === 429) throw new Error("WiGLE rate limit exceeded");
    throw new Error("WiGLE API " + resp.status);
  }
  return resp.json();
}

function bbox(
  lat: number,
  lon: number,
  radiusKm: number
): { latMin: string; latMax: string; lonMin: string; lonMax: string } {
  const dLat = radiusKm / 111;
  const dLon = radiusKm / (111 * Math.cos((lat * Math.PI) / 180));
  return {
    latMin: (lat - dLat).toFixed(6),
    latMax: (lat + dLat).toFixed(6),
    lonMin: (lon - dLon).toFixed(6),
    lonMax: (lon + dLon).toFixed(6),
  };
}

export async function fetchWifiNetworks(
  lat: number,
  lon: number,
  radiusKm: number
): Promise<WigleNetwork[]> {
  const key = cacheKey(lat, lon, "wifi");
  const cached = getCached(key);
  if (cached) return cached;

  const bb = bbox(lat, lon, radiusKm);
  const data = await wigleGet("network/search", {
    latrange1: bb.latMin,
    latrange2: bb.latMax,
    longrange1: bb.lonMin,
    longrange2: bb.lonMax,
    resultsPerPage: "100",
  });

  const results: WigleNetwork[] = (data.results || []).map((r: any) => ({
    ssid: r.ssid || "<hidden>",
    bssid: r.netid || "",
    lat: r.trilat,
    lon: r.trilong,
    encryption: r.encryption || "unknown",
    channel: r.channel || 0,
    type: "wifi" as const,
    firstSeen: r.firsttime || "",
    lastSeen: r.lasttime || "",
  }));

  cache.set(key, { data: results, time: Date.now() });
  return results;
}

export async function fetchCellTowers(
  lat: number,
  lon: number,
  radiusKm: number
): Promise<WigleNetwork[]> {
  const key = cacheKey(lat, lon, "cell");
  const cached = getCached(key);
  if (cached) return cached;

  const bb = bbox(lat, lon, radiusKm);
  const data = await wigleGet("cell/search", {
    latrange1: bb.latMin,
    latrange2: bb.latMax,
    longrange1: bb.lonMin,
    longrange2: bb.lonMax,
    resultsPerPage: "100",
  });

  const results: WigleNetwork[] = (data.results || []).map((r: any) => ({
    ssid: r.operator || r.ssid || "Cell Tower",
    bssid: r.netid || "",
    lat: r.trilat,
    lon: r.trilong,
    encryption: r.encryption || "",
    channel: r.channel || 0,
    type: "cell" as const,
    firstSeen: r.firsttime || "",
    lastSeen: r.lasttime || "",
    carrier: r.operator || "",
    cellType: r.type || "",
  }));

  cache.set(key, { data: results, time: Date.now() });
  return results;
}

export async function fetchBluetoothDevices(
  lat: number,
  lon: number,
  radiusKm: number
): Promise<WigleNetwork[]> {
  const key = cacheKey(lat, lon, "bt");
  const cached = getCached(key);
  if (cached) return cached;

  const bb = bbox(lat, lon, radiusKm);
  const data = await wigleGet("bluetooth/search", {
    latrange1: bb.latMin,
    latrange2: bb.latMax,
    longrange1: bb.lonMin,
    longrange2: bb.lonMax,
    resultsPerPage: "100",
  });

  const results: WigleNetwork[] = (data.results || []).map((r: any) => ({
    ssid: r.name || r.ssid || "BT Device",
    bssid: r.netid || "",
    lat: r.trilat,
    lon: r.trilong,
    encryption: r.type || "",
    channel: 0,
    type: "bt" as const,
    firstSeen: r.firsttime || "",
    lastSeen: r.lasttime || "",
  }));

  cache.set(key, { data: results, time: Date.now() });
  return results;
}

export async function fetchAllWigle(
  lat: number,
  lon: number,
  radiusKm: number
): Promise<WigleNetwork[]> {
  const results = await Promise.allSettled([
    fetchWifiNetworks(lat, lon, radiusKm),
    fetchCellTowers(lat, lon, radiusKm),
    fetchBluetoothDevices(lat, lon, radiusKm),
  ]);

  const all: WigleNetwork[] = [];
  for (const r of results) {
    if (r.status === "fulfilled") all.push(...r.value);
  }
  return all;
}
