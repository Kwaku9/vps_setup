import { defineConfig, loadEnv, type Plugin } from "vite";
import cesium from "vite-plugin-cesium-build";
import { resolve } from "path";

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

  return {
    plugins: [cesium(), abuseipdbProxy()],
    resolve: {
      alias: { "@": resolve(__dirname, "src") },
    },
    server: {
      host: true,
      port: 5173,
      allowedHosts: ["geo.aicortex.cloud"],
      watch: {
        usePolling: true,
        interval: 1000,
        ignored: ["**/node_modules/**", "**/.git/**", "**/dist/**"],
      },
      proxy: {
        "/api/planes": {
          target: "https://api.airplanes.live",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/planes/, ""),
        },
        "/api/cctv": {
          target: "https://webcams.nyctmc.org",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/cctv/, ""),
        },
        "/api/caltrans": {
          target: "https://cwwp2.dot.ca.gov",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/caltrans/, "/data"),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },
        "/api/fl511": {
          target: "https://fl511.com",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/fl511/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },

        "/api/txdot": {
          target: "https://its.txdot.gov",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/txdot/, "/its"),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },
        "/api/ilcams": {
          target: "https://services2.arcgis.com",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/ilcams/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },
        "/api/dccams": {
          target: "https://maps2.dcgis.dc.gov",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/dccams/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },
        "/api/ga511": {
          target: "https://511ga.org",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/ga511/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },

        "/api/overpass": {
          target: "https://overpass-api.de",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/overpass/, ""),
        },
        "/api/wigle": {
          target: "https://api.wigle.net",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/wigle/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              const token = env.WIGLE_API_TOKEN || "";
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower.startsWith("x-real") || lower === "origin" ||
                    lower === "referer" || lower === "cookie" ||
                    lower === "authorization" || lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
              if (token) proxyReq.setHeader("Authorization", "Basic " + token);
            });
          },
        },
        "/api/ais": {
          target: "http://backend-pod:9100",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/ais/, ""),
        },
        "/api/threats/": {
          target: "http://metrics-pod:8428",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/threats/, "/api/v1"),
        },
        "/api/osint/ipinfo/": {
          target: "https://ipinfo.io",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/osint\/ipinfo/, ""),
        },
        "/api/osint/greynoise/": {
          target: "https://api.greynoise.io",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/osint\/greynoise/, "/v3/community"),
        },
        "/api/osint/rdns": {
          target: "https://cloudflare-dns.com",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/osint\/rdns/, "/dns-query"),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              proxyReq.setHeader("Accept", "application/dns-json");
            });
          },
        },
        "/api/horizons": {
          target: "https://ssd.jpl.nasa.gov",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/horizons/, "/api/horizons.api"),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },
        "/api/firms": {
          target: "https://firms.modaps.eosdis.nasa.gov",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/firms/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              for (const h of proxyReq.getHeaderNames()) {
                const lower = h.toLowerCase();
                if (lower.startsWith("cf-") || lower.startsWith("x-forwarded") ||
                    lower === "origin" || lower === "referer" || lower === "cookie" ||
                    lower.startsWith("sec-fetch")) {
                  proxyReq.removeHeader(h);
                }
              }
            });
          },
        },
      },
    },
  };
});
