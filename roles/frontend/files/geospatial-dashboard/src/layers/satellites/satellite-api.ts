export interface TLERecord {
  name: string;
  line1: string;
  line2: string;
  group: string;
}

export interface SatelliteGroup {
  name: string;
  url: string;
  limit: number;
}

export const SATELLITE_GROUPS: SatelliteGroup[] = [
  { name: "stations",  url: "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",  limit: 10 },
  { name: "visual",    url: "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle",    limit: 100 },
  { name: "weather",   url: "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",   limit: 50 },
  { name: "gps-ops",   url: "https://celestrak.org/NORAD/elements/gp.php?GROUP=gps-ops&FORMAT=tle",   limit: 31 },
  { name: "starlink",  url: "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle",  limit: 200 },
  { name: "galileo",   url: "https://celestrak.org/NORAD/elements/gp.php?GROUP=galileo&FORMAT=tle",   limit: 30 },
];

export async function fetchTLEs(
  group: string = "stations"
): Promise<TLERecord[]> {
  const grp = SATELLITE_GROUPS.find((g) => g.name === group);
  if (!grp) throw new Error("Unknown satellite group: " + group);

  const text = await cachedTLEText(grp);
  const records = parseTLEText(text, group);
  return records.slice(0, grp.limit);
}

// CelesTrak refreshes element sets about every two hours and blocks clients
// that download more often than that; every page load fetching six groups
// got the browser refused (403/CORS errors and an empty layer). Cache each
// group for that window, and fall back to the last good copy on failure.
const TLE_TTL_MS = 2 * 60 * 60 * 1000;

async function cachedTLEText(grp: SatelliteGroup): Promise<string> {
  const key = `wv_tle_${grp.name}`;
  let cached: { at: number; text: string } | null = null;
  try {
    const raw = localStorage.getItem(key);
    if (raw) cached = JSON.parse(raw);
  } catch { /* private mode or corrupt entry */ }

  if (cached && Date.now() - cached.at < TLE_TTL_MS) return cached.text;

  try {
    const response = await fetch(grp.url);
    if (!response.ok) throw new Error("CelesTrak fetch failed: " + response.status);
    // Keep only the records the layer shows (3 lines each): the full
    // Starlink set alone is ~1.7 MB against a ~5 MB storage quota.
    const text = (await response.text())
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .slice(0, grp.limit * 3)
      .join("\n");
    try { localStorage.setItem(key, JSON.stringify({ at: Date.now(), text })); }
    catch { /* quota or private mode: still use the fresh copy */ }
    return text;
  } catch (e) {
    if (cached) {
      console.warn(`Satellites: ${grp.name} refresh failed, using copy from ${new Date(cached.at).toISOString()}`);
      return cached.text;
    }
    throw e;
  }
}

export async function fetchAllGroups(): Promise<TLERecord[]> {
  const results = await Promise.allSettled(
    SATELLITE_GROUPS.map((g) => fetchTLEs(g.name))
  );

  const all: TLERecord[] = [];
  for (const result of results) {
    if (result.status === "fulfilled") {
      all.push(...result.value);
    } else {
      console.warn("Satellite group fetch failed:", result.reason);
    }
  }
  return all;
}

function parseTLEText(text: string, group: string): TLERecord[] {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);

  const records: TLERecord[] = [];

  for (let i = 0; i + 2 < lines.length; i += 3) {
    const name = lines[i];
    const line1 = lines[i + 1];
    const line2 = lines[i + 2];

    if (line1.startsWith("1 ") && line2.startsWith("2 ")) {
      records.push({ name, line1, line2, group });
    }
  }

  return records;
}
