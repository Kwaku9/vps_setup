import {
  Viewer,
  Cartesian2,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  defined,
  Entity,
  Math as CesiumMath,
} from "cesium";
import { makeRetractable, PanelToggleState } from "@/ui/panel-base";
import {
  enrichIP,
  categoryName,
  type OSINTResult,
} from "@/layers/threats/osint-api";
import {
  SCENARIO_COLORS,
  DEFAULT_THREAT_COLOR,
  getScenarioSeverity,
} from "@/layers/threats/crowdsec-api";

export class EntityInfoPanel {
  private container: HTMLDivElement;
  private handler: ScreenSpaceEventHandler;
  private snapshotRefreshTimer: number | null = null;
  private panelState: PanelToggleState;

  constructor(private viewer: Viewer) {
    this.container = document.createElement("div");
    Object.assign(this.container.style, {
      position: "absolute",
      bottom: "12px",
      right: "12px",
      backgroundColor: "rgba(0, 0, 0, 0.85)",
      border: "1px solid #1a3a1a",
      borderRadius: "4px",
      padding: "12px",
      fontFamily: '"Courier New", monospace',
      fontSize: "11px",
      color: "#33ff33",
      zIndex: "1000",
      minWidth: "220px",
      maxWidth: "360px",
      display: "none",
      userSelect: "none",
    });

    const { wrapper, state } = makeRetractable(this.container, "right");
    this.panelState = state;
    document.body.appendChild(wrapper);

    this.handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    this.handler.setInputAction(
      (click: { position: Cartesian2 }) => this.onClick(click),
      ScreenSpaceEventType.LEFT_CLICK
    );
  }

  toggle(): void {
    this.panelState.toggle();
  }

  private onClick(click: { position: Cartesian2 }): void {
    const picked = this.viewer.scene.pick(click.position);

    if (defined(picked) && picked.id instanceof Entity) {
      this.showEntity(picked.id);
    } else {
      this.hide();
    }
  }

  private showEntity(entity: Entity): void {
    const props = entity.properties;
    if (!props) {
      this.hide();
      return;
    }

    const t = this.viewer.clock.currentTime;
    const type = props.type?.getValue(t);
    let html = "";

    if (type === "satellite" && props.noradId?.getValue(t) === "25544") {
      // ISS hero entity - gold header
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px;color:#FFD700">INTERNATIONAL SPACE STATION</div>';
      html += this.row("NORAD ID", "25544");
      const group = props.group?.getValue(t);
      if (group) html += this.row("Group", group.toUpperCase());
      html += this.row("Orbit", "LEO (Low Earth Orbit)");

      const pos = entity.position?.getValue(t);
      if (pos) {
        const carto =
          this.viewer.scene.globe?.ellipsoid.cartesianToCartographic(pos);
        if (carto) {
          const altKm = carto.height / 1000;
          const lat = CesiumMath.toDegrees(carto.latitude);
          const lon = CesiumMath.toDegrees(carto.longitude);
          html += this.row("Altitude", altKm.toFixed(1) + " km");
          html += this.row("Velocity", "~7.66 km/s");
          html += this.row("Latitude", lat.toFixed(4) + "\u00B0");
          html += this.row("Longitude", lon.toFixed(4) + "\u00B0");
          html += this.row("Period", "~92.7 min");
        }
      }
    } else if (type === "satellite") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
      html += this.row("NORAD ID", props.noradId?.getValue(t));
      const group = props.group?.getValue(t);
      if (group) {
        html += this.row("Group", group.toUpperCase());
        const orbitType = this.getOrbitType(group);
        if (orbitType) html += this.row("Orbit", orbitType);
      }
    } else if (type === "flight") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
      html += this.row("ICAO", props.icao24?.getValue(t));
      html += this.row("Callsign", props.callsign?.getValue(t));
      html += this.row("Type", props.aircraftType?.getValue(t));
      html += this.row("Aircraft", props.description?.getValue(t));
      html += this.row("Operator", props.operator?.getValue(t));
      html += this.row("Altitude", this.fmtAlt(props.altitude?.getValue(t)));
      html += this.row("Speed", this.fmtSpeed(props.velocity?.getValue(t)));
      html += this.row("Heading", this.fmtDeg(props.heading?.getValue(t)));
    } else if (type === "military") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
      html += this.row("ICAO", props.icao?.getValue(t));
      html += this.row("Callsign", props.callsign?.getValue(t));
      html += this.row("Type", props.aircraftType?.getValue(t));
      html += this.row("Aircraft", props.description?.getValue(t));
      html += this.row("Operator", props.operator?.getValue(t));
      html += this.row("Altitude", this.fmtAlt(props.altitude?.getValue(t)));
      html += this.row(
        "Speed",
        `${(props.speed?.getValue(t) ?? 0).toFixed(0)} kts`
      );
      html += this.row("Heading", this.fmtDeg(props.heading?.getValue(t)));
      html += this.row("Squawk", props.squawk?.getValue(t));
    } else if (type === "earthquake") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
      const mag = props.magnitude?.getValue(t);
      const depth = props.depth?.getValue(t);
      const place = props.place?.getValue(t);
      const time = props.time?.getValue(t);
      const tsunami = props.tsunami?.getValue(t);

      html += this.row("Magnitude", mag?.toFixed(1));
      html += this.row("Depth", depth?.toFixed(1) + " km");
      html += this.row("Location", place);
      if (time) {
        html += this.row("Time", new Date(time).toUTCString());
      }
      html += this.row(
        "Tsunami",
        tsunami
          ? '<span style="color:#ff4444">WARNING</span>'
          : "No"
      );
    } else if (type === "cctv") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
      const city = props.city?.getValue(t);
      const direction = props.direction?.getValue(t);
      const snapshotUrl = props.snapshotUrl?.getValue(t);

      html += this.row("City", city);
      html += this.row("Direction", direction);
      html += this.row(
        "Status",
        '<span style="color:#22ff22">LIVE</span>'
      );

      if (snapshotUrl) {
        html +=
          '<div style="margin-top:8px;border:1px solid #1a3a1a;background:#000;text-align:center;min-height:120px">';
        html +=
          '<img id="cctv-snapshot" src="' +
          snapshotUrl +
          '" style="max-width:100%;display:block" />';
        html += "</div>";
        this.startSnapshotRefresh(snapshotUrl);
      }
    } else if (type === "wigle") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
      const netType = props.netType?.getValue(t);
      const ssid = props.ssid?.getValue(t);
      const bssid = props.bssid?.getValue(t);
      const encryption = props.encryption?.getValue(t);
      const channel = props.channel?.getValue(t);
      const firstSeen = props.firstSeen?.getValue(t);
      const lastSeen = props.lastSeen?.getValue(t);
      const carrier = props.carrier?.getValue(t);
      const cellType = props.cellType?.getValue(t);

      const typeLabel =
        netType === "cell"
          ? "Cell Tower"
          : netType === "bt"
            ? "Bluetooth"
            : "WiFi AP";
      html += this.row("Type", typeLabel);
      html += this.row("SSID", ssid);
      html += this.row("BSSID", bssid);
      if (netType === "wifi") {
        const encColor = encryption?.toLowerCase().includes("wpa")
          ? "#22ff22"
          : encryption?.toLowerCase().includes("wep")
            ? "#ffaa00"
            : encryption?.toLowerCase().includes("none")
              ? "#ff4444"
              : "#ffff00";
        html += this.row(
          "Encryption",
          '<span style="color:' +
            encColor +
            '">' +
            (encryption || "unknown") +
            "</span>"
        );
        if (channel) html += this.row("Channel", channel);
      }
      if (netType === "cell") {
        if (carrier) html += this.row("Carrier", carrier);
        if (cellType) html += this.row("Cell Type", cellType);
      }
      if (firstSeen) html += this.row("First Seen", firstSeen);
      if (lastSeen) html += this.row("Last Seen", lastSeen);
    } else if (type === "firms") {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px;color:#FF6600">THERMAL ANOMALY</div>';
      const brightness = props.brightness?.getValue(t);
      const confidence = props.confidence?.getValue(t);
      const frp = props.frp?.getValue(t);
      const satellite = props.satellite?.getValue(t);
      const acqDate = props.acqDate?.getValue(t);
      const acqTime = props.acqTime?.getValue(t);
      const daynight = props.daynight?.getValue(t);

      html += this.row("Brightness", brightness?.toFixed(1) + " K");
      html += this.row("Confidence", confidence);
      html += this.row("FRP", (frp ?? 0).toFixed(1) + " MW");
      html += this.row("Satellite", satellite);
      html += this.row("Date", acqDate);
      html += this.row("Time", acqTime);
      html += this.row("Day/Night", daynight === "D" ? "Day" : "Night");
    } else if (type === "threat") {
      const scenario = props.scenario?.getValue(t) || "";
      const headerColor = SCENARIO_COLORS[scenario] || DEFAULT_THREAT_COLOR;
      const severity = getScenarioSeverity(scenario);
      const sevColor =
        severity === "CRITICAL"
          ? "#ff0000"
          : severity === "HIGH"
            ? "#ff6600"
            : severity === "MEDIUM"
              ? "#ffff00"
              : "#33ff33";
      const scenarioLabel = props.scenarioLabel?.getValue(t) || scenario;
      const ip = props.ip?.getValue(t) || "";
      const ts = props.timestamp?.getValue(t);
      const ago = ts ? this.timeAgo(ts) : "--";

      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px;color:' +
        headerColor +
        '">THREAT: ' +
        scenarioLabel +
        "</div>";
      html += this.row(
        "Severity",
        '<span style="color:' + sevColor + '">' + severity + "</span>"
      );
      html += this.row("IP", ip);
      html += this.row("Country", props.country?.getValue(t));
      html += this.row("ASN", props.asname?.getValue(t));
      html += this.row("AS Number", props.asnumber?.getValue(t));
      html += this.row("IP Range", props.iprange?.getValue(t));
      html += this.row(
        "Decision",
        '<span style="color:#ff4444">' +
          (props.decisionType?.getValue(t) || "ban").toUpperCase() +
          "</span>"
      );
      html += this.row("Duration", props.duration?.getValue(t));
      html += this.row("Detected", ago);

      // OSINT enrichment placeholder
      html +=
        '<div id="osint-panel" style="margin-top:8px;border-top:1px solid #1a3a1a;padding-top:6px">' +
        '<div style="opacity:0.6;font-size:9px;letter-spacing:1px">OSINT ENRICHMENT</div>' +
        '<div id="osint-loading" style="color:#00ffff;font-size:10px;margin-top:4px">Enriching target...</div>' +
        "</div>";

      // Async OSINT — updates panel after render
      if (ip) {
        this.loadOSINT(ip);
      }
    } else if (type === "acled") {
      const eventType = props.eventType?.getValue(t);
      const headerColor = this.getAcledColor(eventType);
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px;color:' +
        headerColor +
        '">' +
        (entity.name || "CONFLICT EVENT") +
        "</div>";
      html += this.row("Event Type", eventType);
      html += this.row("Sub-type", props.subEventType?.getValue(t));
      html += this.row("Actor 1", props.actor1?.getValue(t));
      html += this.row("Actor 2", props.actor2?.getValue(t));
      const fatalities = props.fatalities?.getValue(t);
      if (fatalities > 0) {
        html += this.row(
          "Fatalities",
          '<span style="color:#ff4444">' + fatalities + "</span>"
        );
      } else {
        html += this.row("Fatalities", fatalities);
      }
      html += this.row("Date", props.eventDate?.getValue(t));
      html += this.row("Country", props.country?.getValue(t));
      html += this.row("Location", props.location?.getValue(t));
      const notes = props.notes?.getValue(t);
      if (notes) {
        const truncated =
          notes.length > 150 ? notes.substring(0, 150) + "..." : notes;
        html +=
          '<div style="margin-top:6px;opacity:0.7;font-size:9px;line-height:1.3">' +
          truncated +
          "</div>";
      }
    } else {
      html +=
        '<div style="font-weight:bold;margin-bottom:6px;letter-spacing:1px">' +
        (entity.name || "Unknown") +
        "</div>";
    }

    this.container.innerHTML = html;
    this.container.style.display = "block";

    if (type === "cctv") {
      const img = this.container.querySelector(
        "#cctv-snapshot"
      ) as HTMLImageElement;
      if (img) {
        img.onerror = () => {
          const parent = img.parentElement;
          if (parent) {
            parent.innerHTML =
              '<div style="padding:20px;color:#ff4444;font-size:10px">FEED UNAVAILABLE</div>';
          }
        };
      }
    }
  }

  private getAcledColor(eventType: string): string {
    const map: Record<string, string> = {
      Battles: "#FF0000",
      "Explosions/Remote violence": "#FF6600",
      "Violence against civilians": "#FF00FF",
      Protests: "#FFFF00",
      Riots: "#FF8800",
      "Strategic developments": "#00AAFF",
    };
    return map[eventType] || "#33ff33";
  }

  private startSnapshotRefresh(baseUrl: string): void {
    this.stopSnapshotRefresh();
    this.snapshotRefreshTimer = window.setInterval(() => {
      const img = this.container.querySelector(
        "#cctv-snapshot"
      ) as HTMLImageElement;
      if (img) {
        img.src = baseUrl + "&_t=" + Date.now();
      }
    }, 60000);
  }

  private stopSnapshotRefresh(): void {
    if (this.snapshotRefreshTimer !== null) {
      clearInterval(this.snapshotRefreshTimer);
      this.snapshotRefreshTimer = null;
    }
  }

  private getOrbitType(group: string): string | null {
    const map: Record<string, string> = {
      stations: "LEO (Low Earth Orbit)",
      visual: "LEO (Bright)",
      weather: "LEO/Polar",
      "gps-ops": "MEO (20,200 km)",
      starlink: "LEO (~550 km)",
      galileo: "MEO (23,222 km)",
    };
    return map[group] || null;
  }

  private row(label: string, value: any): string {
    return (
      '<div style="display:flex;justify-content:space-between;margin-bottom:2px">' +
      '<span style="opacity:0.6">' +
      label +
      "</span>" +
      "<span>" +
      (value ?? "--") +
      "</span>" +
      "</div>"
    );
  }

  private fmtAlt(meters: number | undefined): string {
    if (meters == null) return "--";
    const feet = meters * 3.28084;
    return `${feet.toFixed(0)} ft (${(meters / 1000).toFixed(1)} km)`;
  }

  private fmtSpeed(ms: number | undefined): string {
    if (ms == null) return "--";
    const knots = ms * 1.944;
    return `${knots.toFixed(0)} kts`;
  }

  private timeAgo(timestamp: number): string {
    const diff = Date.now() - timestamp;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m ago`;
  }

  private async loadOSINT(ip: string): Promise<void> {
    try {
      const result = await enrichIP(ip);
      const panel = this.container.querySelector("#osint-panel");
      if (!panel) return;

      let html =
        '<div style="opacity:0.6;font-size:9px;letter-spacing:1px;margin-bottom:4px">OSINT ENRICHMENT</div>';

      // Reverse DNS
      if (result.reverseDns) {
        html += this.row("Hostname", result.reverseDns);
      }

      // ipinfo.io
      if (result.ipinfo) {
        const i = result.ipinfo;
        if (i.org) html += this.row("Org", i.org);
        if (i.city)
          html += this.row("Location", `${i.city}, ${i.region || i.country}`);
        if (i.hostname && i.hostname !== result.reverseDns)
          html += this.row("Host", i.hostname);
      }

      // GreyNoise
      if (result.greynoise) {
        const g = result.greynoise;
        const classColor =
          g.classification === "malicious"
            ? "#ff0000"
            : g.classification === "benign"
              ? "#33ff33"
              : "#ffff00";
        html += this.row(
          "GreyNoise",
          '<span style="color:' +
            classColor +
            '">' +
            g.classification.toUpperCase() +
            "</span>"
        );
        if (g.name) html += this.row("Actor", g.name);
        if (g.noise) html += this.row("Mass Scanner", "Yes");
        if (g.riot)
          html += this.row(
            "RIOT",
            '<span style="color:#33ff33">Legitimate Service</span>'
          );
        if (g.tags.length > 0)
          html += this.row("Tags", g.tags.slice(0, 3).join(", "));
      }

      // AbuseIPDB
      if (result.abuseipdb) {
        const a = result.abuseipdb;
        const scoreColor =
          a.abuseConfidenceScore >= 75
            ? "#ff0000"
            : a.abuseConfidenceScore >= 30
              ? "#ff6600"
              : "#33ff33";
        html += this.row(
          "Abuse Score",
          '<span style="color:' +
            scoreColor +
            ';font-weight:bold">' +
            a.abuseConfidenceScore +
            "%</span>"
        );
        html += this.row("Reports", String(a.totalReports));
        if (a.isp) html += this.row("ISP", a.isp);
        if (a.domain) html += this.row("Domain", a.domain);
        if (a.usageType) html += this.row("Usage", a.usageType);
        if (a.isTor)
          html += this.row(
            "Tor Exit",
            '<span style="color:#ff4444">YES</span>'
          );
        if (a.categories.length > 0) {
          const cats = a.categories
            .slice(0, 4)
            .map((c: number) => categoryName(c))
            .join(", ");
          html += this.row("Categories", cats);
        }
        if (a.lastReportedAt) {
          html += this.row(
            "Last Reported",
            new Date(a.lastReportedAt).toLocaleDateString()
          );
        }
      }

      // No data from any source
      if (!result.ipinfo && !result.greynoise && !result.abuseipdb && !result.reverseDns) {
        html +=
          '<div style="color:#ffff00;font-size:10px">No OSINT data available</div>';
      }

      panel.innerHTML = html;
    } catch {
      const loading = this.container.querySelector("#osint-loading");
      if (loading) {
        loading.textContent = "OSINT lookup failed";
        (loading as HTMLElement).style.color = "#ff4444";
      }
    }
  }

  private fmtDeg(deg: number | undefined): string {
    if (deg == null) return "--";
    return `${deg.toFixed(1)}deg`;
  }

  hide(): void {
    this.stopSnapshotRefresh();
    this.container.style.display = "none";
  }

  destroy(): void {
    this.stopSnapshotRefresh();
    this.handler.destroy();
    this.container.remove();
  }
}
