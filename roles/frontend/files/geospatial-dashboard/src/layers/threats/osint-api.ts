// OSINT enrichment APIs — fan-out to ipinfo.io, GreyNoise, AbuseIPDB
// All calls best-effort with in-memory 10min cache

export interface IPInfoResult {
  hostname: string;
  org: string;
  city: string;
  region: string;
  country: string;
  asn: string;
}

export interface GreyNoiseResult {
  classification: string; // benign | malicious | unknown
  name: string;
  noise: boolean;
  riot: boolean;
  tags: string[];
}

export interface AbuseIPDBResult {
  abuseConfidenceScore: number;
  usageType: string;
  isTor: boolean;
  totalReports: number;
  lastReportedAt: string;
  domain: string;
  isp: string;
  categories: number[];
}

export interface OSINTResult {
  ip: string;
  ipinfo: IPInfoResult | null;
  greynoise: GreyNoiseResult | null;
  abuseipdb: AbuseIPDBResult | null;
  reverseDns: string | null;
  fetchedAt: number;
}

const CATEGORY_MAP: Record<number, string> = {
  1: "DNS Compromise",
  2: "DNS Poisoning",
  3: "Fraud Orders",
  4: "DDoS Attack",
  5: "FTP Brute-Force",
  6: "Ping of Death",
  7: "Phishing",
  8: "Fraud VoIP",
  9: "Open Proxy",
  10: "Web Spam",
  11: "Email Spam",
  12: "Blog Spam",
  14: "Port Scan",
  15: "Hacking",
  18: "Brute-Force",
  19: "Bad Web Bot",
  20: "Exploited Host",
  21: "Web App Attack",
  22: "SSH",
  23: "IoT Targeted",
};

export function categoryName(id: number): string {
  return CATEGORY_MAP[id] || `Category ${id}`;
}

// In-memory cache: ip → result, 10-minute TTL
const cache = new Map<string, OSINTResult>();
const CACHE_TTL = 10 * 60 * 1000;

function getCached(ip: string): OSINTResult | null {
  const entry = cache.get(ip);
  if (entry && Date.now() - entry.fetchedAt < CACHE_TTL) return entry;
  return null;
}

async function lookupIPInfo(ip: string): Promise<IPInfoResult | null> {
  try {
    const resp = await fetch(`/api/osint/ipinfo/${ip}/json`);
    if (!resp.ok) return null;
    const data = await resp.json();
    return {
      hostname: data.hostname || "",
      org: data.org || "",
      city: data.city || "",
      region: data.region || "",
      country: data.country || "",
      asn: data.org ? data.org.split(" ")[0] : "",
    };
  } catch {
    return null;
  }
}

async function lookupGreyNoise(ip: string): Promise<GreyNoiseResult | null> {
  try {
    const resp = await fetch(`/api/osint/greynoise/${ip}`);
    if (!resp.ok) return null;
    const data = await resp.json();
    return {
      classification: data.classification || "unknown",
      name: data.name || "",
      noise: data.noise ?? false,
      riot: data.riot ?? false,
      tags: data.tags || [],
    };
  } catch {
    return null;
  }
}

async function lookupAbuseIPDB(ip: string): Promise<AbuseIPDBResult | null> {
  try {
    const resp = await fetch(
      `/api/osint/abuseipdb?ipAddress=${encodeURIComponent(ip)}&maxAgeInDays=90&verbose=true`
    );
    if (!resp.ok) return null;
    const json = await resp.json();
    const data = json.data;
    if (!data) return null;
    return {
      abuseConfidenceScore: data.abuseConfidenceScore ?? 0,
      usageType: data.usageType || "",
      isTor: data.isTor ?? false,
      totalReports: data.totalReports ?? 0,
      lastReportedAt: data.lastReportedAt || "",
      domain: data.domain || "",
      isp: data.isp || "",
      categories: data.reports
        ? ([
            ...new Set(
              data.reports.flatMap(
                (r: { categories: number[] }) => r.categories
              )
            ),
          ] as number[])
        : [],
    };
  } catch {
    return null;
  }
}

async function lookupReverseDns(ip: string): Promise<string | null> {
  try {
    const parts = ip.split(".").reverse().join(".");
    const resp = await fetch(
      `/api/osint/rdns?name=${parts}.in-addr.arpa&type=PTR`
    );
    if (!resp.ok) return null;
    const data = await resp.json();
    const answer = data.Answer?.[0]?.data;
    return answer || null;
  } catch {
    return null;
  }
}

export async function enrichIP(ip: string): Promise<OSINTResult> {
  const cached = getCached(ip);
  if (cached) return cached;

  const [ipinfo, greynoise, abuseipdb, reverseDns] = await Promise.all([
    lookupIPInfo(ip),
    lookupGreyNoise(ip),
    lookupAbuseIPDB(ip),
    lookupReverseDns(ip),
  ]);

  const result: OSINTResult = {
    ip,
    ipinfo,
    greynoise,
    abuseipdb,
    reverseDns,
    fetchedAt: Date.now(),
  };

  cache.set(ip, result);
  return result;
}
