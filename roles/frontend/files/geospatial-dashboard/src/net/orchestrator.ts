/**
 * Central request orchestrator — one choke point for every external API call.
 *
 * Installed once (installOrchestrator() in main.ts) as a window.fetch wrapper,
 * so all 14 layer APIs get, with zero per-layer changes:
 *   • per-upstream token buckets (rate budgets)            • global + per-policy
 *     concurrency caps                                     • FIFO queue with
 *     drop-oldest overflow                                 • in-flight coalescing
 *     of identical GETs                                    • exponential backoff
 *     + jitter honoring Retry-After (GET only)             • per-upstream circuit
 *     breaker                                              • tab-hidden pausing
 *
 * Cesium's tile traffic uses its own RequestScheduler/XHR path and is
 * deliberately NOT routed through this (tuned separately in viewer.ts).
 */

interface Policy {
  name: string;
  /** URL prefixes (path or absolute) this policy governs. First match wins. */
  match: string[];
  /** Sustained budget in requests/minute. */
  perMin: number;
  /** Bucket size — short bursts allowed above the sustained rate. */
  burst: number;
  /** Max in-flight requests for this upstream. */
  concurrent: number;
  /** Retries for idempotent (GET) requests on 429/5xx/network. */
  retries: number;
  /** Consecutive failures before the breaker opens. */
  breakerAfter: number;
  /** How long an open breaker rejects fast (ms). */
  breakerCooldownMs: number;
}

const POLICIES: Policy[] = [
  // WiGLE has a strict daily quota and the layer fires wifi+cell+bt per camera
  // settle — tightest budget here (the dev-server proxy adds a second gate).
  { name: 'wigle',     match: ['/api/wigle'], perMin: 8,  burst: 2,  concurrent: 1, retries: 1, breakerAfter: 3, breakerCooldownMs: 120_000 },
  { name: 'overpass',  match: ['/api/overpass'], perMin: 4, burst: 1, concurrent: 1, retries: 1, breakerAfter: 2, breakerCooldownMs: 180_000 },
  { name: 'firms',     match: ['/api/firms'], perMin: 4,  burst: 1,  concurrent: 1, retries: 1, breakerAfter: 3, breakerCooldownMs: 180_000 },
  { name: 'planes',    match: ['/api/planes'], perMin: 20, burst: 4, concurrent: 2, retries: 1, breakerAfter: 4, breakerCooldownMs: 90_000 },
  { name: 'ais',       match: ['/api/ais'], perMin: 30, burst: 5, concurrent: 2, retries: 1, breakerAfter: 4, breakerCooldownMs: 60_000 },
  { name: 'threats',   match: ['/api/threats'], perMin: 30, burst: 4, concurrent: 2, retries: 2, breakerAfter: 4, breakerCooldownMs: 60_000 },
  { name: 'osint',     match: ['/api/osint'], perMin: 20, burst: 4, concurrent: 2, retries: 1, breakerAfter: 4, breakerCooldownMs: 90_000 },
  { name: 'horizons',  match: ['/api/horizons'], perMin: 4, burst: 2, concurrent: 1, retries: 1, breakerAfter: 3, breakerCooldownMs: 180_000 },
  { name: 'cctv',      match: ['/api/cctv', '/api/caltrans', '/api/fl511', '/api/txdot',
                               '/api/ilcams', '/api/dccams', '/api/ga511'],
    perMin: 30, burst: 8, concurrent: 3, retries: 1, breakerAfter: 5, breakerCooldownMs: 120_000 },
  { name: 'celestrak', match: ['https://celestrak.org'], perMin: 8, burst: 4, concurrent: 2, retries: 2, breakerAfter: 3, breakerCooldownMs: 300_000 },
  { name: 'usgs',      match: ['https://earthquake.usgs.gov'], perMin: 10, burst: 3, concurrent: 2, retries: 2, breakerAfter: 4, breakerCooldownMs: 120_000 },
  { name: 'rainviewer', match: ['https://api.rainviewer.com'], perMin: 10, burst: 3, concurrent: 2, retries: 1, breakerAfter: 4, breakerCooldownMs: 120_000 },
  { name: 'acled',     match: ['https://acled-proxy'], perMin: 4, burst: 1, concurrent: 1, retries: 1, breakerAfter: 3, breakerCooldownMs: 300_000 },
];

const DEFAULT_POLICY: Policy = {
  name: 'default', match: [], perMin: 120, burst: 30, concurrent: 6,
  retries: 1, breakerAfter: 6, breakerCooldownMs: 60_000,
};

const GLOBAL_CONCURRENCY = 8;
const QUEUE_LIMIT = 120;

interface PolicyState {
  policy: Policy;
  tokens: number;
  lastRefill: number;
  active: number;
  consecutiveFailures: number;
  breakerOpenUntil: number;
}

interface QueueItem {
  url: string;
  init: RequestInit | undefined;
  state: PolicyState;
  coalesceKey: string | null;
  resolve: (r: Response) => void;
  reject: (e: unknown) => void;
  enqueuedAt: number;
}

export interface NetStats {
  queued: number;
  active: number;
  completed: number;
  throttled: number;   // 429s observed
  retried: number;
  dropped: number;     // queue overflow
  breakers: string[];  // currently-open breakers
}

const states = new Map<string, PolicyState>();
const queue: QueueItem[] = [];
const inflight = new Map<string, Promise<Response>>();
let globalActive = 0;
let realFetch: typeof fetch | null = null;
let pumping = false;
const stats: NetStats = {
  queued: 0, active: 0, completed: 0, throttled: 0, retried: 0, dropped: 0, breakers: [],
};

function policyFor(url: string): PolicyState {
  let found = DEFAULT_POLICY;
  outer: for (const p of POLICIES) {
    for (const m of p.match) {
      if (url.startsWith(m)) { found = p; break outer; }
    }
  }
  let st = states.get(found.name);
  if (!st) {
    st = { policy: found, tokens: found.burst, lastRefill: performance.now(),
      active: 0, consecutiveFailures: 0, breakerOpenUntil: 0 };
    states.set(found.name, st);
  }
  return st;
}

function refill(st: PolicyState): void {
  const now = performance.now();
  const elapsedMin = (now - st.lastRefill) / 60_000;
  if (elapsedMin > 0) {
    st.tokens = Math.min(st.policy.burst, st.tokens + elapsedMin * st.policy.perMin);
    st.lastRefill = now;
  }
}

function canRun(st: PolicyState): boolean {
  if (document.hidden) return false;                 // resume on visibility
  if (globalActive >= GLOBAL_CONCURRENCY) return false;
  if (st.active >= st.policy.concurrent) return false;
  if (performance.now() < st.breakerOpenUntil) return false;
  refill(st);
  return st.tokens >= 1;
}

function pump(): void {
  if (pumping) return;
  pumping = true;
  try {
    for (let i = 0; i < queue.length; ) {
      const item = queue[i];
      // Fast-fail anything aimed at an open breaker instead of queue-rotting.
      if (performance.now() < item.state.breakerOpenUntil) {
        queue.splice(i, 1);
        item.reject(new Error(`${item.state.policy.name}: circuit open`));
        continue;
      }
      if (canRun(item.state)) {
        queue.splice(i, 1);
        run(item);
      } else {
        i += 1;
      }
    }
  } finally {
    stats.queued = queue.length;
    pumping = false;
  }
}

async function run(item: QueueItem): Promise<void> {
  const st = item.state;
  st.tokens -= 1;
  st.active += 1;
  globalActive += 1;
  stats.active = globalActive;
  try {
    const resp = await fetchWithRetry(item.url, item.init, st);
    st.consecutiveFailures = 0;
    stats.completed += 1;
    item.resolve(resp);
  } catch (err) {
    st.consecutiveFailures += 1;
    if (st.consecutiveFailures >= st.policy.breakerAfter) {
      st.breakerOpenUntil = performance.now() + st.policy.breakerCooldownMs;
      st.consecutiveFailures = 0;
      refreshBreakerStat();
      setTimeout(refreshBreakerStat, st.policy.breakerCooldownMs + 50);
    }
    item.reject(err);
  } finally {
    st.active -= 1;
    globalActive -= 1;
    stats.active = globalActive;
    if (item.coalesceKey) inflight.delete(item.coalesceKey);
    pump();
  }
}

function refreshBreakerStat(): void {
  const now = performance.now();
  stats.breakers = [...states.values()]
    .filter((s) => now < s.breakerOpenUntil)
    .map((s) => s.policy.name);
}

async function fetchWithRetry(
  url: string, init: RequestInit | undefined, st: PolicyState,
): Promise<Response> {
  const method = (init?.method || 'GET').toUpperCase();
  const maxAttempts = method === 'GET' ? st.policy.retries + 1 : 1;
  let lastErr: unknown;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (attempt > 0) {
      stats.retried += 1;
      const backoff = Math.min(8000, 300 * 2 ** (attempt - 1));
      await sleep(backoff + Math.random() * backoff * 0.5);   // full jitter
    }
    try {
      const resp = await realFetch!(url, init);
      if (resp.status === 429 || resp.status === 503) {
        stats.throttled += resp.status === 429 ? 1 : 0;
        const ra = parseFloat(resp.headers.get('Retry-After') || '');
        if (attempt + 1 < maxAttempts) {
          // Drain the bucket so siblings back off too, then honor Retry-After.
          st.tokens = 0;
          await sleep(Number.isFinite(ra) ? Math.min(ra * 1000, 30_000) : 1000);
          continue;
        }
        return resp;   // out of retries — let the layer see the 429
      }
      return resp;
    } catch (err) {
      lastErr = err;   // network error — retry if attempts remain
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('network failure');
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function shouldBypass(url: string): boolean {
  // Only real API traffic (/api/* or absolute http[s]) is orchestrated.
  const isApi = url.startsWith('/api/') || url.startsWith('http://')
    || url.startsWith('https://');
  return !isApi;
}

export function installOrchestrator(): void {
  if (realFetch) return;   // idempotent
  realFetch = window.fetch.bind(window);

  window.fetch = ((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input
      : input instanceof URL ? input.href : input.url;
    if (shouldBypass(url)) return realFetch!(input as RequestInfo, init);

    const st = policyFor(url);
    const method = (init?.method || 'GET').toUpperCase();
    const coalesceKey = method === 'GET' ? url : null;

    // Identical GET already in flight → share it (clone the response).
    if (coalesceKey) {
      const existing = inflight.get(coalesceKey);
      if (existing) return existing.then((r) => r.clone());
    }

    if (performance.now() < st.breakerOpenUntil) {
      return Promise.reject(new Error(`${st.policy.name}: circuit open`));
    }

    const p = new Promise<Response>((resolve, reject) => {
      if (queue.length >= QUEUE_LIMIT) {
        const dropped = queue.shift();
        stats.dropped += 1;
        dropped?.reject(new Error('request queue overflow'));
      }
      queue.push({ url, init, state: st, coalesceKey, resolve, reject,
        enqueuedAt: performance.now() });
      stats.queued = queue.length;
      pump();
    });

    if (coalesceKey) {
      inflight.set(coalesceKey, p);
      return p.then((r) => r.clone());
    }
    return p;
  }) as typeof fetch;

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pump();
  });
  // Safety pump: catches token refills when nothing else triggers one.
  setInterval(pump, 1500);

  console.log('Request orchestrator installed',
    `(${POLICIES.length} upstream policies, global concurrency ${GLOBAL_CONCURRENCY})`);
}

export function getNetStats(): NetStats {
  refreshBreakerStat();
  return { ...stats, queued: queue.length, active: globalActive };
}
