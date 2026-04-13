/**
 * AIS WebSocket Relay — connects to AISStream.io, serves vessel positions via HTTP.
 *
 * Runs on the VPS as a sidecar service. The WorldView nginx proxies
 * /api/ais/vessels → http://localhost:9100/vessels
 *
 * Environment:
 *   AISSTREAM_API_KEY  — required
 *   AIS_PORT           — HTTP listen port (default 9100)
 *   AIS_MAX_VESSELS    — max vessels to track (default 2000)
 *   AIS_STALE_MINUTES  — drop vessels not seen for N minutes (default 15)
 */

import WebSocket from "ws";
import http from "node:http";

const API_KEY = process.env.AISSTREAM_API_KEY;
if (!API_KEY) {
  console.error("AISSTREAM_API_KEY is required");
  process.exit(1);
}

const PORT = parseInt(process.env.AIS_PORT || "9100");
const MAX_VESSELS = parseInt(process.env.AIS_MAX_VESSELS || "2000");
const STALE_MS = parseInt(process.env.AIS_STALE_MINUTES || "15") * 60_000;

// ── Vessel state store ──────────────────────────────────

/** @type {Map<string, object>} MMSI → vessel state */
const vessels = new Map();

// Ship type categories based on AIS type codes
function shipCategory(typeCode) {
  if (typeCode >= 70 && typeCode <= 79) return "cargo";
  if (typeCode >= 80 && typeCode <= 89) return "tanker";
  if (typeCode >= 60 && typeCode <= 69) return "passenger";
  if (typeCode >= 40 && typeCode <= 49) return "hsc"; // high-speed craft
  if (typeCode >= 50 && typeCode <= 59) return "special";
  if (typeCode >= 30 && typeCode <= 39) return "fishing";
  if (typeCode >= 20 && typeCode <= 29) return "military";
  return "other";
}

function shipColor(category) {
  const colors = {
    cargo: "#4FC3F7",
    tanker: "#FF7043",
    passenger: "#66BB6A",
    fishing: "#FFB300",
    military: "#EF5350",
    hsc: "#CE93D8",
    special: "#78909C",
    other: "#9E9E9E",
  };
  return colors[category] || colors.other;
}

// ── WebSocket connection to AISStream ───────────────────

let ws = null;
let reconnectTimer = null;
let messageCount = 0;

function connect() {
  if (ws) {
    try { ws.close(); } catch (_) {}
  }

  console.log(`[AIS Relay] Connecting to AISStream.io...`);
  ws = new WebSocket("wss://stream.aisstream.io/v0/stream");

  ws.on("open", () => {
    console.log(`[AIS Relay] Connected. Subscribing...`);
    const subscription = {
      APIKey: API_KEY,
      BoundingBoxes: [[[-90, -180], [90, 180]]],
      FilterMessageTypes: ["PositionReport", "ShipStaticData"],
    };
    ws.send(JSON.stringify(subscription));
    console.log(`[AIS Relay] Subscribed to global feed.`);
  });

  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data);
      messageCount++;
      handleMessage(msg);
    } catch (_) {}
  });

  ws.on("close", (code, reason) => {
    console.log(`[AIS Relay] Disconnected (${code}). Reconnecting in 5s...`);
    scheduleReconnect();
  });

  ws.on("error", (err) => {
    console.error(`[AIS Relay] WebSocket error:`, err.message);
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 5000);
}

function handleMessage(msg) {
  const { MessageType, MetaData, Message } = msg;

  if (MessageType === "PositionReport" && Message?.PositionReport) {
    const pr = Message.PositionReport;
    const mmsi = String(pr.UserID);
    const lat = MetaData?.latitude ?? pr.Latitude;
    const lon = MetaData?.longitude ?? pr.Longitude;

    if (lat === 0 && lon === 0) return; // invalid position

    const existing = vessels.get(mmsi) || {};
    vessels.set(mmsi, {
      ...existing,
      mmsi,
      lat,
      lon,
      cog: pr.Cog ?? existing.cog ?? 0,        // course over ground
      sog: pr.Sog ?? existing.sog ?? 0,        // speed over ground (knots)
      heading: pr.TrueHeading !== 511 ? pr.TrueHeading : (pr.Cog ?? 0),
      navStatus: pr.NavigationalStatus ?? existing.navStatus,
      name: MetaData?.ShipName?.trim() || existing.name || "",
      ts: Date.now(),
    });

    // Enforce max vessels (drop oldest)
    if (vessels.size > MAX_VESSELS) {
      let oldestKey = null;
      let oldestTs = Infinity;
      for (const [k, v] of vessels) {
        if (v.ts < oldestTs) { oldestTs = v.ts; oldestKey = k; }
      }
      if (oldestKey) vessels.delete(oldestKey);
    }
  }

  if (MessageType === "ShipStaticData" && Message?.ShipStaticData) {
    const sd = Message.ShipStaticData;
    const mmsi = String(sd.UserID);
    const existing = vessels.get(mmsi);
    if (existing) {
      existing.name = sd.Name?.trim() || existing.name;
      existing.shipType = sd.Type ?? existing.shipType;
      existing.category = shipCategory(sd.Type ?? 0);
      existing.color = shipColor(existing.category);
      existing.destination = sd.Destination?.trim() || existing.destination;
      existing.callsign = sd.CallSign?.trim() || existing.callsign;
      existing.imo = sd.ImoNumber || existing.imo;
      existing.length = sd.Dimension?.A + sd.Dimension?.B || existing.length;
      existing.width = sd.Dimension?.C + sd.Dimension?.D || existing.width;
    }
  }
}

// ── Stale vessel cleanup ────────────────────────────────

setInterval(() => {
  const now = Date.now();
  let cleaned = 0;
  for (const [mmsi, v] of vessels) {
    if (now - v.ts > STALE_MS) {
      vessels.delete(mmsi);
      cleaned++;
    }
  }
  if (cleaned > 0) {
    console.log(`[AIS Relay] Cleaned ${cleaned} stale vessels. Active: ${vessels.size}`);
  }
}, 60_000);

// ── HTTP server ─────────────────────────────────────────

const server = http.createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "application/json");

  if (req.url?.startsWith("/vessels")) {
    const url = new URL(req.url, "http://localhost");
    const minLat = parseFloat(url.searchParams.get("minLat") ?? "-90");
    const maxLat = parseFloat(url.searchParams.get("maxLat") ?? "90");
    const minLon = parseFloat(url.searchParams.get("minLon") ?? "-180");
    const maxLon = parseFloat(url.searchParams.get("maxLon") ?? "180");
    const hasBbox = url.searchParams.has("minLat");

    const arr = [];
    for (const v of vessels.values()) {
      if (hasBbox) {
        // Handle antimeridian crossing (minLon > maxLon)
        const inLon = minLon <= maxLon
          ? (v.lon >= minLon && v.lon <= maxLon)
          : (v.lon >= minLon || v.lon <= maxLon);
        if (v.lat < minLat || v.lat > maxLat || !inLon) continue;
      }
      arr.push({
        mmsi: v.mmsi,
        name: v.name || "",
        lat: v.lat,
        lon: v.lon,
        cog: v.cog,
        sog: v.sog,
        heading: v.heading,
        category: v.category || "other",
        color: v.color || "#9E9E9E",
        destination: v.destination || "",
        navStatus: v.navStatus ?? -1,
        length: v.length || 0,
        age: Math.round((Date.now() - v.ts) / 1000),
      });
    }
    res.writeHead(200);
    res.end(JSON.stringify({ count: arr.length, vessels: arr }));
    return;
  }

  if (req.url === "/stats" || req.url === "/stats/") {
    res.writeHead(200);
    res.end(JSON.stringify({
      vessels: vessels.size,
      messagesTotal: messageCount,
      wsConnected: ws?.readyState === WebSocket.OPEN,
      uptime: Math.round(process.uptime()),
    }));
    return;
  }

  if (req.url === "/health") {
    res.writeHead(200);
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: "not found" }));
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[AIS Relay] HTTP server listening on port ${PORT}`);
  connect();
});

// Stats log every 60s
setInterval(() => {
  console.log(
    `[AIS Relay] Vessels: ${vessels.size} | Messages: ${messageCount} | WS: ${ws?.readyState === WebSocket.OPEN ? "connected" : "disconnected"}`
  );
}, 60_000);
