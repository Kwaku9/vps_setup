import { defineConfig, loadEnv, type Plugin } from "vite";
import cesium from "vite-plugin-cesium-build";
import { resolve } from "path";
import { ROUTES } from "./proxy-routes.mjs";

/**
 * WiGLE proxy as a middleware (replaces the raw proxy entry) so the server can
 * enforce a shared rate budget + short response cache across every open tab.
 * WiGLE's daily quota is tiny — the browser-side orchestrator throttles per
 * client, this gate protects the account globally.
 */
function wigleProxy(): Plugin {
  const CACHE_TTL_MS = 120_000;
  const BUCKET_PER_MIN = 10;
  const BUCKET_BURST = 3;
  const cache = new Map<string, { ts: number; status: number; body: string }>();
  let tokens = BUCKET_BURST;
  let lastRefill = Date.now();

  const WIGLE_ORIGIN = "https://api.wigle.net";

  return {
    name: "wigle-proxy",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        // Strict prefix: next char must be / or ? (or end) so "/api/wiglexyz"
        // and userinfo-smuggling paths like "/api/wigle@host" don't match.
        if (!req.url || !/^\/api\/wigle(?:[/?]|$)/.test(req.url)) return next();
        const token = process.env.WIGLE_API_TOKEN;
        if (!token) {
          res.writeHead(503, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "WIGLE_API_TOKEN not configured" }));
          return;
        }

        // Build the upstream URL by RELATIVE resolution against a fixed base
        // (never string concatenation — that let "/api/wigle@evil.com" resolve
        // to https://api.wigle.net@evil.com, leaking the token to evil.com).
        // Then assert the origin is exactly WiGLE before sending credentials.
        let targetUrl: URL;
        try {
          const rel = req.url.replace(/^\/api\/wigle/, "") || "/";
          targetUrl = new URL(rel, WIGLE_ORIGIN);
        } catch {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "bad request path" }));
          return;
        }
        if (targetUrl.origin !== WIGLE_ORIGIN) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "target host not allowed" }));
          return;
        }
        const target = targetUrl.toString();

        const hit = cache.get(target);
        if (hit && Date.now() - hit.ts < CACHE_TTL_MS) {
          res.writeHead(hit.status, { "Content-Type": "application/json", "X-Cache": "HIT" });
          res.end(hit.body);
          return;
        }

        tokens = Math.min(BUCKET_BURST, tokens + ((Date.now() - lastRefill) / 60_000) * BUCKET_PER_MIN);
        lastRefill = Date.now();
        if (tokens < 1) {
          res.writeHead(429, { "Content-Type": "application/json", "Retry-After": "30" });
          res.end(JSON.stringify({ error: "wigle budget exhausted, retry later" }));
          return;
        }
        tokens -= 1;

        try {
          const proxyResp = await fetch(target, {
            headers: { Authorization: "Basic " + token, Accept: "application/json" },
          });
          const body = await proxyResp.text();
          if (proxyResp.ok) {
            cache.set(target, { ts: Date.now(), status: proxyResp.status, body });
            if (cache.size > 300) {
              const oldest = cache.keys().next().value;
              if (oldest) cache.delete(oldest);
            }
          }
          res.writeHead(proxyResp.status, { "Content-Type": "application/json", "X-Cache": "MISS" });
          res.end(body);
        } catch (err: any) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: err.message }));
        }
      });
    },
  };
}

function abuseipdbProxy(): Plugin {
  return {
    name: "abuseipdb-proxy",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith("/api/osint/abuseipdb")) return next();
        const apiKey = process.env.ABUSEIPDB_API_KEY;
        if (!apiKey) {
          res.writeHead(503, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "ABUSEIPDB_API_KEY not configured" }));
          return;
        }
        try {
          const qs = req.url.split("?")[1] || "";
          const targetUrl = "https://api.abuseipdb.com/api/v2/check?" + qs;
          const proxyResp = await fetch(targetUrl, {
            headers: { Key: apiKey, Accept: "application/json" },
          });
          const body = await proxyResp.text();
          res.writeHead(proxyResp.status, {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          });
          res.end(body);
        } catch (err: any) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: err.message }));
        }
      });
    },
  };
}


export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (env.ABUSEIPDB_API_KEY) process.env.ABUSEIPDB_API_KEY = env.ABUSEIPDB_API_KEY;
  if (env.WIGLE_API_TOKEN) process.env.WIGLE_API_TOKEN = env.WIGLE_API_TOKEN;

  return {
    plugins: [cesium(), abuseipdbProxy(), wigleProxy()],
    resolve: {
      alias: { "@": resolve(__dirname, "src") },
    },
    server: {
      host: true,
      port: 5173,
      // Hostnames the dev server will answer to when reverse-proxied. One
      // deployment's domain does not belong in a package other people run, so
      // this is configuration: DEV_ALLOWED_HOSTS="globe.example.com,foo.test".
      allowedHosts: (env.DEV_ALLOWED_HOSTS || "")
        .split(",").map((h) => h.trim()).filter(Boolean),
      watch: {
        usePolling: true,
        interval: 1000,
        ignored: ["**/node_modules/**", "**/.git/**", "**/dist/**"],
      },
      // GENERATED FROM proxy-routes.mjs — do not hand-edit entries here.
      // This block and nginx.conf used to be maintained independently, which is
      // how the container ended up serving a third of the routes the dev server
      // did. Both now read the same table: add a route there and both get it.
      proxy: Object.fromEntries(
        ROUTES.map((r: any) => {
          const prefix = r.path.replace(/\/$/, "");
          return [
            r.path,
            {
              // Companion hostnames differ per deployment; .env wins.
              target: (r.env && env[r.env]) || r.target,
              changeOrigin: true,
              // An empty result would be an invalid request line, so a bare
              // prefix maps to "/" — matching the nginx rule for the same route.
              rewrite: (path: string) =>
                path.replace(new RegExp(`^${prefix}`), r.rewriteTo || "") || "/",
              configure: (proxy: any) => {
                proxy.on("proxyReq", (proxyReq: any) => {
                  // Several public endpoints 403 when they can tell the request
                  // arrived via a proxy or CDN.
                  if (r.strip) {
                    for (const h of proxyReq.getHeaderNames()) {
                      const l = h.toLowerCase();
                      if (
                        l.startsWith("cf-") || l.startsWith("x-forwarded") ||
                        l === "origin" || l === "referer" || l === "cookie" ||
                        l.startsWith("sec-fetch")
                      ) {
                        proxyReq.removeHeader(h);
                      }
                    }
                  }
                  for (const [k, v] of Object.entries(r.headers || {})) {
                    proxyReq.setHeader(k, v as string);
                  }
                });
              },
            },
          ];
        })
      ),
    },
  };
});
