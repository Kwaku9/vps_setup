// CrowdSec threat data via VictoriaMetrics /api/v1/export
// Queries the cs_lapi_decision metric pushed by CrowdSec HTTP notifier

export interface ThreatEvent {
  ip: string;
  country: string;
  latitude: number;
  longitude: number;
  scenario: string;
  type: string;
  asname: string;
  asnumber: string;
  iprange: string;
  duration: string;
  timestamp: number;
  /** Decision origin label ("crowdsec"/"cscli" = local, "capi" = community). */
  origin: string;
  /** True for community-blocklist sampler entries — global threat atmosphere,
   *  NOT attacks on this host. Legacy samples (no origin label) are detected
   *  by the geo-feed's "AS123"-style asnumber format. */
  community: boolean;
}

export const SCENARIO_COLORS: Record<string, string> = {
  "crowdsecurity/http-cve":         "#ff0000",  // Red    — CVE exploit
  "crowdsecurity/http-bad-user-agent": "#ff0044", // Crimson — malicious UA
  "crowdsecurity/ssh-bf":           "#ff6600",  // Orange — SSH brute force
  "crowdsecurity/http-bf-wordpress":"#ff6600",  // Orange — WP brute force
  "crowdsecurity/http-bf":          "#ff8800",  // Amber  — HTTP brute force
  "crowdsecurity/http-probing":     "#ffff00",  // Yellow — HTTP probe
  "crowdsecurity/http-sensitive-files": "#ffcc00", // Gold — sensitive file scan
  "crowdsecurity/port-scan":        "#ffff00",  // Yellow — port scan
  "crowdsecurity/http-crawl-non_statics": "#cc00ff", // Purple — crawler
  "crowdsecurity/traefik":          "#00ffff",  // Cyan   — generic Traefik
};

export const DEFAULT_THREAT_COLOR = "#33ff33";

export function getScenarioLabel(scenario: string): string {
  const short = scenario.replace("crowdsecurity/", "");
  return short.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function getScenarioSeverity(scenario: string): string {
  if (scenario.includes("cve")) return "CRITICAL";
  if (scenario.includes("-bf")) return "HIGH";
  if (scenario.includes("scan") || scenario.includes("probing")) return "MEDIUM";
  return "LOW";
}

export async function fetchThreatEvents(
  lookback = "-1h"
): Promise<ThreatEvent[]> {
  const url = `/api/threats/export?match=cs_lapi_decision&start=${encodeURIComponent(lookback)}`;

  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`VictoriaMetrics: ${resp.status} ${resp.statusText}`);
  }

  const text = await resp.text();
  if (!text.trim()) return [];

  const lines = text.trim().split("\n");
  const events: ThreatEvent[] = [];

  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      const m = entry.metric;
      const lat = parseFloat(m.latitude);
      const lon = parseFloat(m.longitude);
      if (!lat && !lon) continue; // skip entries with no geo data

      events.push({
        ip: m.ip || "",
        country: m.country || "",
        latitude: lat,
        longitude: lon,
        scenario: m.scenario || "",
        type: m.type || "ban",
        asname: m.asname || "",
        asnumber: m.asnumber || "",
        iprange: m.iprange || "",
        duration: m.duration || "",
        timestamp: entry.timestamps?.[0] ?? Date.now(),
        origin: (m.origin || "").toLowerCase(),
        community: (m.origin || "").toLowerCase() === "capi"
          || (!m.origin && /^AS/i.test(m.asnumber || "")),
      });
    } catch {
      // skip malformed lines
    }
  }

  // Deduplicate: keep most recent event per ip+scenario pair
  const deduped = new Map<string, ThreatEvent>();
  for (const evt of events) {
    const key = `${evt.ip}|${evt.scenario}`;
    const existing = deduped.get(key);
    if (!existing || evt.timestamp > existing.timestamp) {
      deduped.set(key, evt);
    }
  }

  return Array.from(deduped.values());
}
